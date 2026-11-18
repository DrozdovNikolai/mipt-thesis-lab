"""One frozen EN selection-policy experiment; no new labels or decoder variants."""

import argparse
import hashlib
import io
import json
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.asr import local_model_manifest
from north55_speech.core import atomic_json, file_hash, now, settings
from north55_speech.datasets import Sample, decoded_audio_hash, load_manifest, write_manifest
from north55_speech.lora import train_asr, validate_references
from north55_speech.sampling import balanced_selection
from scripts import decoding_diagnostics as decoder
from scripts.assemble_quality_pairs import checked_groups
from scripts.retrain_asr import EXPECTED

STUDY, DATA = Path('/study'), Path('/dataset')
SYSTEMS = ('parent', 'augmented', 'balanced')
MODEL = 'whisper-small-balanced-v1'
POLICY = {'id': 'speaker_round_robin_hash55_v1', 'count': 200, 'seed': 55,
          'duration_seconds': [1, 30], 'split': 'train', 'audio_selection_by_ASR': False}


def read(path):
    return json.loads(path.read_bytes())


def identity():
    decoder.ROOT = STUDY
    return decoder.identity() | {'experiment_driver_sha256': file_hash(Path(__file__)),
        'training_implementation_sha256': file_hash(Path('/app/src/north55_speech/lora.py'))}


def is_support_en(sample):
    return sample.source_dataset == 'openslr/librispeech_asr' and sample.language == 'en'


def prepare():
    import pyarrow.parquet as pq

    if (STUDY / 'plan.json').exists():
        raise ValueError('Existing plan must be preserved')
    for name, expected in EXPECTED.items():
        if file_hash(Path('/app') / name) != expected:
            raise ValueError('Original contract changed')
    old_plan = read(Path('/previous-plan.json'))
    old_train = Path('/old/train.jsonl')
    old_dev = Path('/old/dev.jsonl')
    if (file_hash(old_train) != old_plan['data']['augmented']['train_sha256']
            or file_hash(old_dev) != old_plan['data']['augmented']['dev_sha256']):
        raise ValueError('Previous training manifests changed')
    if file_hash(Path('/app/src/north55_speech/lora.py')) != file_hash(Path('/old-lora.py')):
        raise ValueError('Training implementation must remain identical')
    acquisition = read(Path('/sources/training-support-acquisition.json'))
    if acquisition['status'] != 'ACQUIRED' or acquisition['license'] != 'CC-BY-4.0':
        raise ValueError('Verified acquisition required')
    entry = next(e for e in acquisition['files'] if e['local'] == 'librispeech-0000.parquet')
    parquet = Path('/sources') / entry['local']
    if file_hash(parquet) != entry['actual_sha256']:
        raise ValueError('Acquired train source changed')
    originals, dev = load_manifest(old_train), load_manifest(old_dev)
    protected = [s for s in originals if not is_support_en(s)]
    if len(originals) != 433 or len(protected) != 233 or len(dev) != 35:
        raise ValueError('Unexpected fixed composition')
    prior_inputs = read(Path('/input-source.json'))
    quiet_inputs = [r for r in read(Path('/quiet-source.json')) if r['gain_db']]
    if (file_hash(Path('/input-source.json')) != old_plan['inputs_sha256']
            or len(prior_inputs) != 661 or len(quiet_inputs) != 14):
        raise ValueError('Unexpected diagnostic population')
    items = [{**i, 'reference_id': i['id'], 'gain_db': 0.} for i in prior_inputs] + quiet_inputs
    excluded_speakers = {str(i['speaker_id']) for i in read(Path('/clean-plan.json'))['items']}
    excluded_pcm = {s.decoded_audio_sha256 for s in protected + dev}
    for item in prior_inputs:
        path = settings.audio_root / item['audio_path']
        if file_hash(path) != item['audio_sha256']:
            raise ValueError('Diagnostic audio changed')
        excluded_pcm.add(decoded_audio_hash([path]))
    reviewed = load_manifest(Path('/reviewed-dev.jsonl'))
    preflight = {'policy': POLICY, **identity(), 'prior_plan_sha256': file_hash(Path('/previous-plan.json')),
                 'source_sha256': file_hash(parquet), 'test_accessed': False,
                 'data_selection_uses_reference_answers': False}
    atomic_json(STUDY / 'preflight.json', preflight)
    eligible, excluded, seen = [], Counter(), set()
    for batch in pq.ParquetFile(parquet).iter_batches(batch_size=32):
        for row in batch.to_pylist():
            if str(row['speaker_id']) in excluded_speakers:
                excluded['known_dev_speaker'] += 1
                continue
            content = row['audio']['bytes']
            audio, rate = sf.read(io.BytesIO(content), dtype='float32')
            if rate != 16000 or audio.ndim != 1 or not np.isfinite(audio).all():
                raise ValueError('Malformed publisher waveform')
            if not row['text'].strip() or not 16000 <= len(audio) <= 480000:
                excluded['duration_or_empty_text'] += 1
                continue
            digest = hashlib.sha256(json.dumps({'rate': 16000, 'channels': 1}, sort_keys=True).encode())
            digest.update(audio.astype('<f4').tobytes())
            pcm = digest.hexdigest()
            if pcm in excluded_pcm or pcm in seen:
                excluded['duplicate_audio'] += 1
                continue
            seen.add(pcm)
            eligible.append({'id': row['id'], 'speaker_id': str(row['speaker_id']),
                'chapter_id': str(row['chapter_id']), 'split': 'train', 'reference_text': row['text'],
                'audio': audio, 'source_audio_sha256': hashlib.sha256(content).hexdigest(), 'pcm': pcm})
    selection = sorted(balanced_selection(eligible, POLICY['count'], POLICY['seed']), key=lambda r: r['id'])
    imported = []
    for r in selection:
        name = 'libri-train-' + r['id']
        path = settings.audio_root / 'balanced-v1' / (name + '.wav')
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if decoded_audio_hash([path]) != r['pcm']:
                raise ValueError('Existing prepared audio changed')
        else:
            sf.write(path, r['audio'], 16000, subtype='FLOAT')
        imported.append(Sample(sample_id=name, audio_path=str(path.relative_to(settings.audio_root)),
            audio_sha256=file_hash(path), decoded_audio_sha256=decoded_audio_hash([path]),
            source_dataset='openslr/librispeech_asr', source_version='71cacbfb7e2354c4226d01e70d77d5fca3d04ba1',
            recording_id='librispeech-'+r['id'], session_id='librispeech-chapter-'+r['chapter_id'],
            original_utterance_id='librispeech-'+r['id'], speaker_ids=['librispeech-reader-'+r['speaker_id']],
            language='en', input_language='en', scope='general_control', scope_verified=False,
            speech_origin='recorded_human', duration_sec=len(r['audio'])/16000,
            license_id='CC-BY-4.0', rights_confirmed=True, transcript_status='human_verified',
            reference_text=r['reference_text'], split='train', primary=False, clean_control=False,
            provenance='https://huggingface.co/datasets/openslr/librispeech_asr/tree/71cacbfb7e2354c4226d01e70d77d5fca3d04ba1',
            annotation_provenance={'method': 'publisher_supervised_corpus_import',
                'annotator': 'openslr/librispeech_asr', 'reviewed_audio': False,
                'local_manual_verification': False, 'source_split': 'train',
                'verification_scope': 'publisher_provided_human_reference_not_local_audio_audit',
                'original_audio_sha256': r['source_audio_sha256'],
                'acquisition_sha256': file_hash(Path('/sources/training-support-acquisition.json')),
                'speaker_partition_basis': 'explicit LibriSpeech IDs', 'selection_policy': POLICY['id']}))
    it = iter(imported)
    train = [next(it) if is_support_en(s) else s.model_copy(deep=True) for s in originals]
    groups = checked_groups(train, dev)
    checked_groups([s.model_copy(deep=True) for s in train], reviewed)
    for before, after in zip(originals, train, strict=True):
        if not is_support_en(before) and before.model_dump() != after.model_dump():
            raise ValueError('Protected RU/weak content or ordering changed')
    config = old_plan['configs']['augmented'] | {'train_manifest': '/dataset/train.jsonl', 'output': MODEL}
    validate_references(train, dev, config)
    for s in train + dev:
        path = settings.audio_root / s.audio_path
        if file_hash(path) != s.audio_sha256 or decoded_audio_hash([path]) != s.decoded_audio_sha256:
            raise ValueError('Training audio validation failed')
    DATA.mkdir(exist_ok=True)
    write_manifest(DATA / 'train.jsonl', train)
    (DATA / 'dev.jsonl').write_bytes(old_dev.read_bytes())
    atomic_json(STUDY / 'inputs.json', items)
    distribution = dict(Counter(r['speaker_id'] for r in selection))
    report = {'eligible_EN': len(eligible), 'selected_EN': len(imported), 'known_EN_speakers': len(distribution),
        'speaker_counts': distribution, 'exclusions': dict(excluded), 'pairs': len(train),
        'minutes': sum(s.duration_sec for s in train)/60,
        'EN_support_minutes': sum(s.duration_sec for s in imported)/60,
        'old_EN_support_minutes': sum(s.duration_sec for s in originals if is_support_en(s))/60,
        'groups': groups, 'protected_233_records_unchanged': True,
        'new_EN_overlap_with_old_selection': len({s.sample_id for s in imported} & {s.sample_id for s in originals}),
        'test_accessed': False, 'local_manual_verification': False}
    atomic_json(STUDY / 'preparation.json', report)
    atomic_json(STUDY / 'selection-ids.json', [{'id': r['id'], 'speaker_id': r['speaker_id'], 'pcm': r['pcm']} for r in selection])
    atomic_json(STUDY / 'plan.json', {**preflight, 'frozen_at': now().isoformat(), 'config': config,
        'train_sha256': file_hash(DATA / 'train.jsonl'), 'dev_sha256': file_hash(DATA / 'dev.jsonl'),
        'inputs_sha256': file_hash(STUDY / 'inputs.json'), 'references_sha256': old_plan['references_sha256'],
        'base_manifest': old_plan['base_manifest'], 'inference_template': old_plan['inference_template'],
        'preparation_sha256': file_hash(STUDY / 'preparation.json'), 'data': report,
        'budget': {'prior_configurations_conservative': 30, 'new_training_arms': 1, 'cumulative': 31,
            'steps': 120, 'seed': 55, 'authorization': 'user: делай, following speaker-balanced one-arm proposal'},
        'selection_allowed': False, 'quality_evidence': False, 'release_promoted': False})
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


def validate_training():
    plan = read(STUDY / 'plan.json')
    if any(plan[k] != v for k, v in identity().items()):
        raise ValueError('Frozen implementation changed')
    if file_hash(DATA / 'train.jsonl') != plan['train_sha256'] or file_hash(DATA / 'dev.jsonl') != plan['dev_sha256']:
        raise ValueError('Frozen training data changed')
    if read(settings.model_root / 'whisper-small-transformers/manifest.json') != plan['base_manifest']:
        raise ValueError('Training parent changed')
    return plan


def train():
    plan = validate_training()
    result = train_asr(plan['config'])
    atomic_json(STUDY / 'training.json', result)
    coverage = result['training_coverage']
    if coverage['unique_samples_loaded'] != 433 or coverage['global_optimizer_steps'] != 120:
        raise ValueError('Incomplete declared training')
    print(json.dumps({'coverage': coverage, 'loss': result['train_metrics'], 'converted_inference': result['converted_inference']}), flush=True)


def freeze_eval():
    plan = validate_training()
    trained = read(STUDY / 'training.json')
    output = STUDY / 'evaluation'
    if (output / 'plan.json').exists():
        raise ValueError('Evaluation already frozen')
    names = {'parent': 'whisper-small-publisher-base-ct2', 'augmented': 'whisper-small-retraining-v1-augmented-ct2', 'balanced': MODEL+'-ct2'}
    models = {s: {'name': n, 'manifest': local_model_manifest(n),
              'manifest_sha256': file_hash(settings.model_root / n / 'manifest.json')} for s, n in names.items()}
    if trained['converted_model'] != models['balanced']['manifest'] or trained['config'] != plan['config']:
        raise ValueError('Saved checkpoint identity differs')
    old = read(Path('/previous-eval/plan.json'))
    for system in ('parent', 'augmented'):
        if models[system] != old['models'][system]:
            raise ValueError('Historical reference checkpoint changed')
    items = read(STUDY / 'inputs.json')
    historical = {}
    for system in ('parent', 'augmented'):
        execution = read(Path('/previous-eval') / system / 'execution.json')
        quiet = read(Path('/quiet-history') / (system+'_baseline') / 'execution.json')
        records = {}
        for item in items:
            root, hashes = (Path('/quiet-history') / (system+'_baseline'), quiet) if item['gain_db'] else (Path('/previous-eval') / system, execution)
            path = root / 'predictions' / (item['id']+'.json')
            if file_hash(path) != hashes['prediction_sha256'][path.name]:
                raise ValueError('Historical prediction changed')
            record = read(path)
            if record['audio_sha256'] != item['audio_sha256'] or record['config']['model'] != names[system]:
                raise ValueError('Historical request differs')
            records[item['id']] = record
        atomic_json(output / 'historical' / (system+'.json'), records)
        historical[system] = file_hash(output / 'historical' / (system+'.json'))
    (output / 'inputs.json').write_bytes((STUDY / 'inputs.json').read_bytes())
    (output / 'protocol.md').write_bytes((STUDY / 'protocol.md').read_bytes())
    atomic_json(output / 'plan.json', {**identity(), 'frozen_at': now().isoformat(),
        'models': models, 'systems': list(SYSTEMS),
        'configs': {s: plan['inference_template'] | {'model': n} for s, n in names.items()},
        'options_overrides': {s: {'without_timestamps': False} for s in SYSTEMS},
        'inputs_sha256': plan['inputs_sha256'], 'references_sha256': plan['references_sha256'],
        'training_plan_sha256': file_hash(STUDY / 'plan.json'), 'historical_sha256': historical,
        'test_accessed': False, 'release_promoted': False})
    print('Frozen evaluation: 675 new predictions; 1350 historical reference responses', flush=True)


def infer(cpu=False):
    decoder.ROOT = Path('/eval')
    plan = decoder.validate()
    if plan['experiment_driver_sha256'] != file_hash(Path(__file__)):
        raise ValueError('Experiment source differs')
    decoder.infer('balanced', cpu=cpu)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('prepare', 'train', 'freeze-eval', 'infer', 'cpu'))
    stage = parser.parse_args().stage
    {'prepare': prepare, 'train': train, 'freeze-eval': freeze_eval,
     'infer': infer, 'cpu': lambda: infer(cpu=True)}[stage]()
