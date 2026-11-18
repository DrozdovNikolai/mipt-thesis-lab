"""Prepare SOTERIA speech clips and compare two machine drafts, without gold labels."""
import argparse
import itertools
import json
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.core import atomic_json, digest, file_hash
from north55_speech.datasets import Sample, decoded_audio_hash, load_manifest, validate_groups, write_manifest

STUDY = Path('/study')
RAW = Path('/raw')
AUDIO = Path('/audio')
PACKET = Path('/packet')
RATE = 16000
POLICY = {
    'vad': {'threshold': 0.5, 'min_speech_duration_ms': 200,
            'max_speech_duration_s': 20, 'min_silence_duration_ms': 500, 'speech_pad_ms': 300},
    'merge_gap_seconds': 1.2, 'merge_shorter_than_seconds': 8, 'maximum_clip_seconds': 22,
    'channels': 'arithmetic_mean_of_all_channels; retain stereo source; fail on severe cancellation',
    'models': ['whisper-small-publisher-base-ct2', 'whisper-large-v3-systran-ct2'],
    'decoding': {'device': 'cuda', 'compute_type': 'float16', 'condition_on_previous_text': False},
    'language': 'auto', 'selection': 'all VAD intervals; no ASR-based exclusions or per-recording quota',
    'references': 'missing; no WER or automatic human labels',
}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def immutable(path, value):
    if path.exists():
        if read(path) != value:
            raise ValueError('Preserve differing artifact: ' + str(path))
    else:
        atomic_json(path, value)


def combine_intervals(intervals, frames, rate=RATE):
    """Merge nearby short speech turns, retaining every VAD sample exactly once."""
    result = []
    for span in intervals:
        a, b = int(span['start']), int(span['end'])
        if not 0 <= a < b <= frames:
            raise ValueError('VAD interval outside source')
        if result and a < result[-1][1]:
            raise ValueError('VAD intervals overlap or are out of order')
        merge = result and a-result[-1][1] <= POLICY['merge_gap_seconds']*rate
        merge = merge and b-result[-1][0] <= POLICY['maximum_clip_seconds']*rate
        merge = merge and (result[-1][1]-result[-1][0] < POLICY['merge_shorter_than_seconds']*rate or b-a < 3*rate)
        if merge:
            result[-1][1] = b
        else:
            result.append([a, b])
    if any(b-a > POLICY['maximum_clip_seconds']*rate for a,b in result):
        raise ValueError('VAD produced an unexpectedly long interval')
    if not all(sum(a <= s['start'] and s['end'] <= b for a,b in result) == 1 for s in intervals):
        raise ValueError('VAD coverage was lost or duplicated')
    return result


def validate_plan():
    p = read(STUDY/'experiment-plan.json')
    if p['policy'] != POLICY or p['acquisition_plan_sha256'] != file_hash(STUDY/'acquisition-plan.json'):
        raise ValueError('Experiment plan changed')
    if p['script_sha256'] != file_hash(Path(__file__)):
        raise ValueError('Experiment script changed')
    return p


def prepare():
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    validate_plan()
    if (PACKET/'packet.json').exists():
        verify_packet()
        print('Existing packet verified; no regeneration', flush=True)
        return
    acquired = read(STUDY/'acquisition.json')
    if acquired['plan_sha256'] != file_hash(STUDY/'acquisition-plan.json'):
        raise ValueError('Acquisition belongs to another plan')
    by_crew, source_stats = {}, []
    for source in acquired['sources']:
        original = RAW/source['filename']
        if original.stat().st_size != source['size'] or file_hash(original) != source['sha256']:
            raise ValueError('Original source changed')
        probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries',
            'stream=index,codec_type,codec_name,sample_rate,channels,duration:format=duration,size',
            '-of','json',str(original)], text=True))
        streams = [s for s in probe['streams'] if s['codec_type'] == 'audio']
        if len(streams) != 1 or streams[0]['channels'] not in (1, 2):
            raise ValueError('Unexpected audio layout; inspect before choosing streams')
        stereo_path = AUDIO/'sources'/(source['crew']+'.wav')
        stereo_path.parent.mkdir(parents=True, exist_ok=True)
        if not stereo_path.exists():
            temporary = stereo_path.with_suffix('.partial.wav')
            subprocess.run(['ffmpeg','-nostdin','-v','error','-n','-i',str(original),'-map','0:a:0',
                '-vn','-ar',str(RATE),'-c:a','pcm_f32le',str(temporary)], check=True)
            temporary.rename(stereo_path)
        stereo, rate = sf.read(stereo_path, dtype='float32', always_2d=True)
        if rate != RATE or not np.all(np.isfinite(stereo)):
            raise ValueError('Invalid decoded waveform')
        expected = float(streams[0].get('duration', probe['format']['duration']))
        if abs(len(stereo)/rate-expected) > 0.15:
            raise ValueError('Audio decoding duration mismatch')
        rms = np.sqrt(np.mean(stereo.astype('float64')**2, axis=0))
        mono = stereo.mean(axis=1).astype('float32')
        mixed_rms = float(np.sqrt(np.mean(mono.astype('float64')**2)))
        if max(rms) < 1e-5 or mixed_rms < float(max(rms))*0.4:
            raise ValueError('Silent source or channel cancellation; inspect before segmentation')
        spans = get_speech_timestamps(mono, VadOptions(**POLICY['vad']), sampling_rate=RATE)
        spans = [{'start':int(s['start']), 'end':int(s['end'])} for s in spans]
        merged = combine_intervals(spans, len(mono))
        immutable(STUDY/'segmentation'/(source['crew']+'.json'), {
            'source_sha256': source['sha256'], 'decoded_sha256':file_hash(stereo_path),
            'frames':len(mono), 'rate':RATE, 'vad':spans, 'clips':merged, 'policy':POLICY})
        samples = []
        for a,b in merged:
            sid = digest({'source_sha256':source['sha256'],'start_frame':a,'end_frame':b,'policy':POLICY})[:32]
            relative = Path('clips')/(sid+'.wav')
            output = AUDIO/relative
            output.parent.mkdir(parents=True, exist_ok=True)
            if output.exists():
                old, old_rate = sf.read(output, dtype='float32')
                if old_rate != RATE or not np.array_equal(old, mono[a:b]):
                    raise ValueError('Existing audio differs')
            else:
                sf.write(output, mono[a:b], RATE, subtype='FLOAT')
            samples.append(Sample(sample_id=sid, audio_path=relative.as_posix(), audio_sha256=file_hash(output),
                decoded_audio_sha256=decoded_audio_hash([output]), source_dataset='NASA SOTERIA',
                source_version='S3 ETag '+source['etag'].strip('"'), recording_id='soteria:'+source['key'],
                session_id='soteria:'+source['crew'], original_utterance_id='soteria:'+source['key']+f'@{a}:{b}',
                speaker_ids=[], language='unknown', input_language='auto', scope='unknown',
                scope_verified=False, speech_origin='recorded_human', acoustic_condition='simulator_dvr',
                duration_sec=(b-a)/RATE, license_id='CC-BY-4.0', rights_confirmed=True,
                provenance='NASA SOTERIA; '+source['url']+'; CC BY 4.0; stereo arithmetic mean and VAD crops',
                primary=False, split=source['split'],
                annotation_provenance={'source_sample_id':source['crew']+f' / DVR Case {source["case"]}',
                    'source_key':source['key'], 'source_audio_sha256':source['sha256'],
                    'original_start_sec':a/RATE, 'original_end_sec':b/RATE,
                    'start_frame':a, 'end_frame':b, 'source_sample_rate':RATE,
                    'crew_id':source['crew'], 'annotator':None, 'reviewed_audio':False,
                    'draft_available':False, 'automatic_training_eligible':False,
                    'shared_actors_across_crews_unresolved':True,
                    'selection':'all_speech_intervals_before_ASR',
                    'timeline_mapping':'source audio seconds = clip seconds + original_start_sec'}))
        by_crew[source['crew']] = samples
        source_stats.append({'crew':source['crew'], 'split':source['split'], 'case':source['case'],
            'source_minutes':len(mono)/RATE/60, 'clip_minutes':sum(s.duration_sec for s in samples)/60,
            'vad_minutes':sum(s['end']-s['start'] for s in spans)/RATE/60,
            'clips':len(samples), 'channels':stereo.shape[1], 'channel_rms':rms.tolist(),
            'mixed_rms':mixed_rms, 'probe':probe})
        print(json.dumps({k:v for k,v in source_stats[-1].items() if k != 'probe'}), flush=True)
    # Interleave crews within each split so the annotation queue offers variety immediately.
    all_samples = [s for batch in itertools.zip_longest(*by_crew.values()) for s in batch if s is not None]
    groups = validate_groups(all_samples)
    for split in ('train','dev'):
        write_manifest(PACKET/(split+'.jsonl'), [s for s in all_samples if s.split == split])
    immutable(PACKET/'packet.json', {'sources':source_stats, 'groups':groups, 'items':len(all_samples),
        'manifest_sha256':{s+'.jsonl':file_hash(PACKET/(s+'.jsonl')) for s in ('train','dev')},
        'plan_sha256':file_hash(STUDY/'experiment-plan.json'), 'human_verified':0,
        'speaker_independence_verified':False, 'shared_actors_require_review':True})
    immutable(STUDY/'preparation.json', read(PACKET/'packet.json'))
    verify_packet()


def verify_packet():
    validate_plan()
    packet = read(PACKET/'packet.json')
    rows = []
    for split in ('train','dev'):
        if file_hash(PACKET/(split+'.jsonl')) != packet['manifest_sha256'][split+'.jsonl']:
            raise ValueError('Manifest changed')
        rows.extend(load_manifest(PACKET/(split+'.jsonl')))
    validate_groups(rows)
    by_crew = defaultdict(list)
    for s in rows:
        by_crew[s.annotation_provenance['crew_id']].append(s)
        if s.reference_text is not None or s.transcript_status != 'missing' or s.scope_verified or s.speaker_ids:
            raise ValueError('Unverified labels were asserted in base packet')
    for crew,samples in by_crew.items():
        stereo,rate = sf.read(AUDIO/'sources'/(crew+'.wav'), dtype='float32', always_2d=True)
        mono = stereo.mean(axis=1).astype('float32')
        segmentation = read(STUDY/'segmentation'/(crew+'.json'))
        if file_hash(AUDIO/'sources'/(crew+'.wav')) != segmentation['decoded_sha256']:
            raise ValueError('Decoded source changed')
        expected = combine_intervals(segmentation['vad'],len(mono))
        actual = sorted((s.annotation_provenance['start_frame'],s.annotation_provenance['end_frame']) for s in samples)
        if actual != [tuple(x) for x in expected]:
            raise ValueError('Speech coverage differs')
        for s in samples:
            path = AUDIO/s.audio_path
            clip,clip_rate = sf.read(path,dtype='float32')
            p=s.annotation_provenance
            if rate != RATE or clip_rate != RATE or not np.array_equal(clip,mono[p['start_frame']:p['end_frame']]):
                raise ValueError('Crop does not match actual source samples')
            if file_hash(path) != s.audio_sha256 or decoded_audio_hash([path]) != s.decoded_audio_sha256:
                raise ValueError('Crop checksum changed')
    immutable(STUDY/'packet-verification.json', {'status':'PASS','clips':len(rows),
        'all_crops_equal_source_samples':True, 'all_vad_intervals_covered_once':True,
        'crew_split_disjoint':True, 'speaker_split_independence':'unverified_shared_actors',
        'base_human_labels':0, 'test_accessed':False})
    print('Packet verification PASS: '+str(len(rows))+' clips',flush=True)


def drafts(model):
    from north55_speech.asr import AsrProvider
    from north55_speech.schemas import PipelineConfig

    validate_plan()
    rows = load_manifest(PACKET/'dev.jsonl')+load_manifest(PACKET/'train.jsonl')
    config = PipelineConfig(model=model, **POLICY['decoding'])
    provider = AsrProvider(config)
    arm = 'large' if 'large-v3' in model else 'small'
    immutable(STUDY/('model-'+arm+'.json'), {'manifest':provider.manifest,
        'effective_options':provider.options('auto'), 'config':config.model_dump(mode='json'),
        'plan_sha256':file_hash(STUDY/'experiment-plan.json')})
    failures, calls, started = [], 0, time.monotonic()
    for i,s in enumerate(rows):
        path=STUDY/'predictions'/arm/(s.sample_id+'.json')
        identity={'sample_id':s.sample_id,'audio_sha256':s.audio_sha256,
            'model':model,'model_manifest_sha256':digest(provider.manifest),'config_hash':config.config_hash,
            'language_mode':'auto','plan_sha256':file_hash(STUDY/'experiment-plan.json')}
        if path.exists():
            result=read(path)
            if any(result.get(k)!=v for k,v in identity.items()):
                raise ValueError('Prediction belongs to another input or model')
        else:
            if file_hash(AUDIO/s.audio_path)!=s.audio_sha256:
                raise ValueError('Audio changed')
            audio,rate=sf.read(AUDIO/s.audio_path,dtype='float32')
            if rate!=RATE or audio.ndim!=1:
                raise ValueError('Invalid model input')
            result={**identity,'text':'','segments':[],'status':'machine','human_verified':False,'error':None}
            try:
                segments=provider.transcribe(audio,0,'auto',s.sample_id,lambda:None)
                result.update(text=' '.join(x.raw_asr_text.strip() for x in segments),
                              segments=[x.model_dump(mode='json') for x in segments])
            except Exception as error:
                result['error']=type(error).__name__+': '+str(error)
            immutable(path,result)
            calls+=1
        if result['error']:
            failures.append(s.sample_id)
        if arm=='large':
            immutable(PACKET/'assisted-drafts'/(s.sample_id+'.json'),result)
        if (i+1)%10==0 or i+1==len(rows):
            progress={'arm':arm,'completed':i+1,'total':len(rows),'failures':len(failures),
                      'new_ASR_calls':calls,'seconds':round(time.monotonic()-started,1)}
            atomic_json(STUDY/('progress-'+arm+'.json'),progress)
            print(json.dumps(progress),flush=True)
    if arm=='large':
        enabled=[s.sample_id for s in rows if not read(PACKET/'assisted-drafts'/(s.sample_id+'.json'))['error']]
        immutable(PACKET/'draft-policy.json',{'version':1,'enabled_sample_ids':enabled,
            'manifest_sha256':{split+'.jsonl':file_hash(PACKET/(split+'.jsonl')) for split in ('train','dev')},
            'draft_sha256':{sid:file_hash(PACKET/'assisted-drafts'/(sid+'.json')) for sid in enabled},
            'requested_by':'user','reason':'SOTERIA experiment with machine drafts for listening and correction',
            'evaluation_note':'Machine-assisted references only after user verification; no automatic attestations'})
    atomic_json(STUDY/('execution-'+arm+'.json'),{'completed':len(rows),'failures':failures,
        'new_ASR_calls':calls,'seconds':time.monotonic()-started})


def report():
    from north55_speech.metrics import edit_counts, lexical_normalizer_v1

    verify_packet()
    rows=load_manifest(PACKET/'dev.jsonl')+load_manifest(PACKET/'train.jsonl')
    diagnostics, languages=[],Counter()
    for s in rows:
        large=read(STUDY/'predictions/large'/(s.sample_id+'.json'))
        small=read(STUDY/'predictions/small'/(s.sample_id+'.json'))
        for p in (large,small):
            if p['audio_sha256']!=s.audio_sha256 or p['plan_sha256']!=file_hash(STUDY/'experiment-plan.json'):
                raise ValueError('Wrong diagnostic prediction')
        langs={x['language'] for x in large['segments']}
        language=next(iter(langs)) if len(langs)==1 else 'mixed' if langs else 'unknown'
        languages[language]+=1
        distance=edit_counts(large['text'],small['text'])
        denom=max(len(lexical_normalizer_v1(large['text']).split()),len(lexical_normalizer_v1(small['text']).split()),1)
        diagnostics.append({'sample_id':s.sample_id,'crew':s.annotation_provenance['crew_id'],'split':s.split,
            'start_sec':s.annotation_provenance['original_start_sec'],'duration_sec':s.duration_sec,
            'language_hint':language,'large_text':large['text'],'small_text':small['text'],
            'large_error':large['error'],'small_error':small['error'],
            'draft_disagreement':(distance['S']+distance['D']+distance['I'])/denom,
            'identical_lexical_text':lexical_normalizer_v1(large['text'])==lexical_normalizer_v1(small['text'])})
    immutable(STUDY/'diagnostics.json',diagnostics)
    stats=read(PACKET/'packet.json')['sources']
    result={'status':'READY_FOR_HUMAN_REVIEW','sources':stats,'clips':len(rows),
        'splits':{split:{'clips':sum(s.split==split for s in rows),'minutes':sum(s.duration_sec for s in rows if s.split==split)/60} for split in ('train','dev')},
        'source_minutes':sum(s['source_minutes'] for s in stats),
        'clip_minutes':sum(s.duration_sec for s in rows)/60,'language_hints':dict(languages),
        'identical_drafts':sum(d['identical_lexical_text'] for d in diagnostics),
        'empty_large_drafts':sum(not d['large_text'].strip() for d in diagnostics),
        'failures':{arm:sum(bool(d[arm+'_error']) for d in diagnostics) for arm in ('small','large')},
        'human_references_created':0,'WER':None,'quality_improvement_proven':False,
        'scope_note':'Simulator recording includes crew, ATC and researchers; segment scope remains unverified',
        'split_note':'Crew split is provisional; shared ATC/research actors unresolved',
        'test_accessed':False,'queue_url':'http://localhost:8013/?split=dev'}
    immutable(STUDY/'result.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='sources'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=['prepare','verify','small','large','report'])
    args=parser.parse_args()
    if args.stage in ('small','large'):
        drafts(POLICY['models'][args.stage=='large'])
    else:
        {'prepare':prepare,'verify':verify_packet,'report':report}[args.stage]()
