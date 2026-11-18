"""Mine student errors using two teachers, preserve uncertain audio for human review."""

import argparse
import hashlib
import json
import math
import statistics
import time
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.core import atomic_json, file_hash, settings
from north55_speech.datasets import (
    Sample,
    decoded_audio_hash,
    load_manifest,
    validate_groups,
    write_manifest,
)
from north55_speech.metrics import edit_counts
from scripts.expand_publisher_pairs import FAMILIES
from scripts.publisher_alignment import number_tokens
from scripts.publisher_phrase_support import critical, support
from scripts.publisher_recovery_rules_v3 import normalize, word_list

WORK = Path('/workspace')
OUT = Path('/output')
DATA = Path('/dataset')
PACKET = Path('/packet')
POLICY = {'version': 'cockpit_hard_v4', 'student_minimum_errors': 2, 'student_disagreement': .12,
    'teacher_disagreement': .08, 'short_exact_below_words': 8, 'minimum_words': 4,
    'minimum_seconds': 3., 'maximum_seconds': 25., 'publisher_coverage': .9,
    'median_word_probability': .65, 'max_zero_duration_fraction': .25,
    'human_verified': False, 'dev_used_for_selection': False, 'test_accessed': False}


def read(path):
    return json.loads(path.read_bytes())


def save_new(path, value):
    if path.exists():
        raise ValueError('Preserve existing artifact: ' + str(path))
    atomic_json(path, value)


def identity():
    return {n: file_hash(Path('/code') / n) for n in (
        'scripts/cockpit_hard_v4.py', 'scripts/publisher_recovery_rules_v3.py',
        'scripts/publisher_phrase_support.py', 'scripts/publisher_alignment.py',
        'scripts/audit_bleriot_remaining.py', 'src/north55_speech/asr.py',
        'src/north55_speech/schemas.py', 'src/north55_speech/metrics.py')}


def disagreement(target, hypothesis):
    counts = edit_counts(normalize(target), normalize(hypothesis))
    errors = counts['S'] + counts['D'] + counts['I']
    return {'errors': errors, 'words': counts['N'], 'rate': errors/max(1, counts['N'])}


def teacher_decision(medium, large, documents, duration):
    reasons = []
    target = medium['hypothesis'].strip()
    agree = disagreement(target, large['hypothesis'])
    if any(p.get('error') for p in (medium, large)):
        reasons.append('teacher_runtime_failure')
    if not POLICY['minimum_seconds'] <= duration <= POLICY['maximum_seconds'] or agree['words'] < POLICY['minimum_words']:
        reasons.append('length')
    allowed = 0 if agree['words'] < POLICY['short_exact_below_words'] else POLICY['teacher_disagreement']
    if agree['rate'] > allowed:
        reasons.append('teacher_disagreement')
    if number_tokens(target) != number_tokens(large['hypothesis']):
        reasons.append('numeric_disagreement')
    if critical(target) != critical(large['hypothesis']):
        reasons.append('state_or_negation_disagreement')
    evidence = []
    for name, doc in documents.items():
        script = '\n'.join(line['text'] for line in doc['lines'] if not line.get('excluded_layout', False))
        evidence.append({'document': name, **support(normalize(target), normalize(script))})
    best = max(evidence, key=lambda d: (d['coverage'], d['critical_supported']))
    if best['coverage'] < POLICY['publisher_coverage'] or not best['critical_supported']:
        reasons.append('publisher_support')
    for name, prediction in [('medium', medium), ('large', large)]:
        words = word_list(prediction)
        probs = [w.get('probability') for w in words]
        if not probs or any(p is None or not math.isfinite(p) or not 0 <= p <= 1 for p in probs) or statistics.median(probs) < POLICY['median_word_probability']:
            reasons.append(name + '_confidence')
        if not words or any(w['start_sec'] is None or w['end_sec'] is None or not 0 <= w['start_sec'] <= w['end_sec'] <= duration+.05 for w in words):
            reasons.append(name + '_timeline')
        elif sum(w['start_sec'] == w['end_sec'] for w in words)/len(words) > POLICY['max_zero_duration_fraction']:
            reasons.append(name + '_collapsed_timeline')
    return {'accepted': not reasons, 'reasons': reasons, 'target': target, 'teacher_agreement': agree,
            'publisher': best, 'human_verified': False}


def prepare():
    from north55_speech.asr import local_model_manifest

    old = WORK / 'data/curated/pair-quality-v1'
    phrases = WORK / 'reports/publisher-phrases-v2'
    source_plan = read(old / 'plan.json')
    phrase_plan = read(phrases / 'inference/plan.json')
    small_execution = read(old / 'small/execution.json')
    medium_execution = read(phrases / 'predictions/execution.json')
    for path, expected in [(old / 'sources.json', source_plan['sources_sha256']),
            (phrases / 'scoring/documents.json', phrase_plan['documents_sha256'])]:
        if file_hash(path) != expected:
            raise ValueError('Source metadata changed')
    sources = read(old / 'sources.json')
    if any(s['split'] != 'train' for s in sources.values()):
        raise ValueError('Only training sources admitted')
    inputs, cached = [], {}
    for item in source_plan['items']:
        small_path = old / 'small/predictions' / (item['id'] + '.json')
        medium_path = phrases / 'predictions' / (item['id'] + '.json')
        if file_hash(small_path) != small_execution['prediction_sha256'][small_path.name] or file_hash(medium_path) != medium_execution['predictions'][item['id']]:
            raise ValueError('Historical teacher/student prediction changed')
        small, medium = read(small_path), read(medium_path)
        difficulty = disagreement(medium['hypothesis'], small['hypothesis'])
        if small.get('error') or medium.get('error') or not POLICY['minimum_seconds'] <= item['duration_sec'] <= POLICY['maximum_seconds']:
            continue
        if difficulty['errors'] < POLICY['student_minimum_errors'] or difficulty['rate'] < POLICY['student_disagreement']:
            continue
        inputs.append(item)
        cached[item['id']] = {'small': small, 'medium': medium, 'difficulty': difficulty,
            'small_sha256': file_hash(small_path), 'medium_sha256': file_hash(medium_path)}
    save_new(OUT / 'inference/inputs.json', inputs)
    save_new(OUT / 'scoring/cached.json', cached)
    save_new(OUT / 'scoring/sources.json', sources)
    save_new(OUT / 'scoring/documents.json', read(phrases / 'scoring/documents.json'))
    model = 'whisper-large-v3-systran-ct2'
    plan = {'policy': POLICY, 'code_sha256': identity(), 'model': model, 'model_manifest': local_model_manifest(model),
        'inputs_sha256': file_hash(OUT / 'inference/inputs.json'),
        'scoring_sha256': {p.name: file_hash(p) for p in (OUT / 'scoring').iterdir()},
        'old_train_sha256': file_hash(WORK / 'data/curated/publisher-recovery-v3/train.jsonl'),
        'old_dev_sha256': file_hash(WORK / 'data/curated/publisher-recovery-v3/dev.jsonl'),
        'raw_train_sha256': file_hash(WORK / 'data/curated/bleriot-v2/manifests/train-dev/train.jsonl'),
        'raw_dev_sha256': file_hash(WORK / 'data/curated/bleriot-v2/manifests/train-dev/dev.jsonl'),
        'medium_model_manifest': phrase_plan['model_manifest'], 'source_plan_sha256': file_hash(old / 'plan.json'),
        'planned_large_EN_calls': len(inputs), 'quality_evidence': False, 'test_accessed': False}
    save_new(OUT / 'inference/plan.json', plan)
    print(json.dumps({'hard_candidates': len(inputs), 'minutes': sum(i['duration_sec'] for i in inputs)/60,
                      'sources': dict(Counter(i['source'] for i in inputs))}, indent=2), flush=True)


def infer():
    from north55_speech.asr import AsrProvider
    from north55_speech.schemas import PipelineConfig

    study = Path('/study')
    plan = read(study / 'plan.json')
    if identity() != plan['code_sha256'] or POLICY != plan['policy'] or file_hash(study / 'inputs.json') != plan['inputs_sha256']:
        raise ValueError('Frozen inference changed')
    provider = AsrProvider(PipelineConfig(model=plan['model'], device='cuda', compute_type='float16', condition_on_previous_text=False))
    if provider.manifest != plan['model_manifest']:
        raise ValueError('Teacher model changed')
    hashes, failures, new = {}, [], 0
    items = read(study / 'inputs.json')
    started = time.perf_counter()
    for index, item in enumerate(items):
        path = Path('/predictions') / (item['id'] + '.json')
        identity_fields = {'id': item['id'], 'audio_sha256': item['audio_sha256'],
            'plan_sha256': file_hash(study / 'plan.json'), 'options': provider.options('en')}
        if path.exists():
            result = read(path)
            if any(result.get(k) != v for k, v in identity_fields.items()) or result.get('error'):
                raise ValueError('Cannot overwrite differing or failed inference')
        else:
            audio_path = settings.audio_root / item['audio_path']
            if file_hash(audio_path) != item['audio_sha256']:
                raise ValueError('Audio changed')
            audio, rate = sf.read(audio_path, dtype='float32')
            if rate != 16000 or audio.ndim != 1 or abs(len(audio)/rate-item['duration_sec']) > .001:
                raise ValueError('Audio contract mismatch')
            result = {**identity_fields, 'hypothesis': '', 'segments': [], 'error': None}
            try:
                segments = provider.transcribe(audio, 0, 'en', item['id'], lambda: None)
                result.update(hypothesis=' '.join(s.raw_asr_text.strip() for s in segments),
                    segments=[s.model_dump(mode='json') for s in segments])
            except Exception as error:
                result['error'] = f'{type(error).__name__}: {error}'
            save_new(path, result)
            new += 1
        hashes[path.name] = file_hash(path)
        if result['error']:
            failures.append(item['id'])
        if (index+1) % 25 == 0:
            print('large EN', index+1, '/', len(items), flush=True)
    destination = Path('/predictions/execution.json')
    value = {'plan_sha256': file_hash(study / 'plan.json'), 'prediction_sha256': hashes,
        'new_ASR_calls': new, 'failures': failures, 'seconds': time.perf_counter()-started,
        'device': provider.model.model.device, 'precision': provider.model.model.compute_type}
    save_new(destination if not destination.exists() else destination.with_name(f'replay-{time.time_ns()}.json'), value)
    print(json.dumps({k: v for k, v in value.items() if k != 'prediction_sha256'}), flush=True)


def clipped(parent, identity, start, end, directory):
    """Crop only the named source channel; no ASR-driven boundary changes."""
    from scipy.signal import resample_poly

    path = settings.audio_root / parent.audio_path
    if file_hash(path) != parent.audio_sha256:
        raise ValueError('Source waveform changed')
    with sf.SoundFile(path) as stream:
        rate = stream.samplerate
        a, b = round(start*rate), round(end*rate)
        if not 0 <= a < b <= len(stream):
            raise ValueError('Crop exceeds original')
        stream.seek(a)
        wave = stream.read(b-a, dtype='float32', always_2d=True)[:, parent.channel]
    common = math.gcd(rate, 16000)
    wave = resample_poly(wave, 16000//common, rate//common).astype('float32')
    destination = settings.audio_root / directory / (identity + '.wav')
    if destination.exists():
        raise ValueError('Preserve existing derived waveform')
    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(destination, wave, 16000, subtype='FLOAT')
    return {'sample_id': identity, 'audio_path': str(destination.relative_to(settings.audio_root)),
        'audio_sha256': file_hash(destination), 'decoded_audio_sha256': decoded_audio_hash([destination]),
        'duration_sec': len(wave)/16000, 'channel': 0}


def overlaps(a, b):
    return max(a[0], b[0]) < min(a[1], b[1]) - .001


def assemble():
    from scipy import signal

    from north55_speech.training import check_training_partitions

    plan = read(OUT / 'inference/plan.json')
    if identity() != plan['code_sha256'] or POLICY != plan['policy']:
        raise ValueError('Preparation implementation changed')
    for name, expected in plan['scoring_sha256'].items():
        if file_hash(OUT / 'scoring' / name) != expected:
            raise ValueError('Cached source changed')
    old_path = WORK / 'data/curated/publisher-recovery-v3'
    raw_path = WORK / 'data/curated/bleriot-v2/manifests/train-dev'
    for prefix, root in [('', old_path), ('raw_', raw_path)]:
        for split in ('train', 'dev'):
            key = ('old_' if not prefix else prefix) + split + '_sha256'
            if file_hash(root / (split + '.jsonl')) != plan[key]:
                raise ValueError('Source partition changed')
    if file_hash(OUT / 'inference/inputs.json') != plan['inputs_sha256']:
        raise ValueError('Candidate list changed')
    items = read(OUT / 'inference/inputs.json')
    execution = read(OUT / 'predictions/execution.json')
    if execution['plan_sha256'] != file_hash(OUT / 'inference/plan.json') or execution['failures']:
        raise ValueError('Incomplete teacher execution')
    sources = {k: Sample.model_validate(v) for k, v in read(OUT / 'scoring/sources.json').items()}
    docs, cached = read(OUT / 'scoring/documents.json'), read(OUT / 'scoring/cached.json')
    accepted, decisions = [], []
    by_id = {i['id']: i for i in items}
    for item in items:
        path = OUT / 'predictions' / (item['id'] + '.json')
        if file_hash(path) != execution['prediction_sha256'][path.name]:
            raise ValueError('Teacher prediction changed')
        large = read(path)
        family_docs = {k: v for k, v in docs.items() if Path(k).stem in FAMILIES[item['family']]}
        if not family_docs:
            raise ValueError('Missing publisher document family')
        decision = teacher_decision(cached[item['id']]['medium'], large, family_docs, item['duration_sec'])
        decision.update(id=item['id'], source=item['source'], difficulty=cached[item['id']]['difficulty'])
        decisions.append(decision)
        if not decision['accepted']:
            continue
        parent = sources[item['source']]
        identity_id = hashlib.sha256(('hard-v4:' + item['id']).encode()).hexdigest()[:32]
        row = parent.model_copy(deep=True, update={
            'sample_id': identity_id, 'audio_path': item['audio_path'], 'audio_sha256': item['audio_sha256'],
            'decoded_audio_sha256': decoded_audio_hash([settings.audio_root / item['audio_path']]),
            'duration_sec': item['duration_sec'], 'channel': 0, 'variant_of': None, 'group_id': None,
            'original_utterance_id': parent.original_utterance_id + '@hard-v4:' + item['id'],
            'language': 'en', 'input_language': 'en', 'scope': 'read_cockpit', 'scope_verified': False,
            'primary': False, 'clean_control': False, 'continuous_recording': False,
            'reference_text': decision['target'], 'transcript_status': 'weak',
            'annotation_provenance': {'method': 'cockpit_hard_teacher_consensus_v4', 'reviewed_audio': False,
                'annotator': None, 'human_verified': False, 'automatic_training_eligible': True,
                'source_sample_id': parent.sample_id, 'original_start_sec': item['original_start_sec'],
                'original_end_sec': item['original_end_sec'], 'source_audio_sha256': parent.audio_sha256,
                'original_item_id': item['id'], 'target_origin': 'unprompted_medium_en_prediction',
                'small_sha256': cached[item['id']]['small_sha256'],
                'medium_sha256': cached[item['id']]['medium_sha256'], 'large_sha256': file_hash(path),
                'preparation_plan_sha256': file_hash(OUT / 'inference/plan.json'),
                'student_difficulty': decision['difficulty'], 'teacher_agreement': decision['teacher_agreement'],
                'publisher_support': decision['publisher'], 'eligibility_reasons': []}})
        accepted.append(row)
    old_train, dev = (load_manifest(old_path / (s + '.jsonl')) for s in ('train', 'dev'))
    replaced, retained = [], []
    for row in old_train:
        p = row.annotation_provenance
        replacing = [s.sample_id for s in accepted if s.annotation_provenance['source_sample_id'] == p['source_sample_id']
            and overlaps((p['original_start_sec'], p['original_end_sec']),
                         (s.annotation_provenance['original_start_sec'], s.annotation_provenance['original_end_sec']))]
        (replaced if replacing else retained).append({'id': row.sample_id, 'replaced_by': replacing} if replacing else row)
    clean = retained + accepted
    raw_train, raw_dev = (load_manifest(raw_path / (s + '.jsonl')) for s in ('train', 'dev'))
    variants = {s.variant_of: s for s in raw_train if s.variant_of
        and s.augmentation.get('parent_link_status') == 'ACOUSTICALLY_CONFIRMED'}
    noise, noise_audit = [], []
    for row in clean:
        p = row.annotation_provenance
        parent = variants.get(p['source_sample_id'])
        if parent is None:
            continue
        identity_id = hashlib.sha256(('noise-hard-v4:' + row.sample_id).encode()).hexdigest()[:32]
        crop = clipped(parent, identity_id, p['original_start_sec'], p['original_end_sec'], 'cockpit-hard-v4-noisy')
        first, _ = sf.read(settings.audio_root / row.audio_path, dtype='float32')
        second, _ = sf.read(settings.audio_root / crop['audio_path'], dtype='float32')
        length = min(len(first), len(second))
        frequencies, values = signal.coherence(first[:length], second[:length], fs=16000, nperseg=1024, noverlap=512)
        coherence = float(np.mean(values[(frequencies >= 300) & (frequencies <= 3000)]))
        audit = {'id': identity_id, 'parent_clip': row.sample_id, 'noisy_source': parent.sample_id,
            'mean_coherence': coherence, 'duration_difference_sec': abs(len(first)-len(second))/16000,
            'accepted': math.isfinite(coherence) and coherence >= .20 and abs(len(first)-len(second)) <= 2}
        noise_audit.append(audit)
        if not audit['accepted']:
            continue
        new = row.model_copy(deep=True, update={**crop, 'variant_of': row.sample_id, 'group_id': None,
            'source_dataset': 'BLeRIOT-C', 'acoustic_condition': 'publisher_CVR_simulation_single_chain',
            'provenance': parent.provenance, 'augmentation': parent.augmentation | {'original_clip': row.sample_id,
                'noisy_source_sample_id': parent.sample_id, 'local_coherence': coherence,
                'noisy_source_sha256': parent.audio_sha256}})
        new.annotation_provenance.update(method='cockpit_hard_paired_noise_v4',
            target_origin='unchanged_paired_clean_weak_transcript', paired_clean_id=row.sample_id,
            paired_clean_text_sha256=hashlib.sha256(row.reference_text.encode()).hexdigest(),
            source_noisy_audio_sha256=parent.audio_sha256, local_coherence=coherence)
        noise.append(new)
    train = clean + noise
    for s in train:
        s.group_id = None
    validate_groups(train)
    check_training_partitions(train, dev)
    validate_groups([s.model_copy(deep=True, update={'group_id': None}) for s in train + dev])
    if DATA.joinpath('train.jsonl').exists():
        raise ValueError('Preserve assembled dataset')
    DATA.mkdir(parents=True, exist_ok=True)
    write_manifest(DATA / 'train.jsonl', train)
    write_manifest(DATA / 'clean.jsonl', clean)
    write_manifest(DATA / 'hard.jsonl', accepted)
    write_manifest(DATA / 'noisy.jsonl', noise)
    (DATA / 'dev.jsonl').write_bytes((old_path / 'dev.jsonl').read_bytes())
    # A balanced disagreement queue. None of these disputed texts enters training.
    rejected = [d for d in decisions if not d['accepted']]
    selected_review, per_source = [], Counter()
    for d in sorted(rejected, key=lambda d: (-min(d['difficulty']['rate'], 1.), d['id'])):
        if per_source[d['source']] < 8 and len(selected_review) < 60:
            selected_review.append(d)
            per_source[d['source']] += 1
    review = []
    for d in selected_review:
        item, parent = by_id[d['id']], sources[d['source']]
        identity_id = hashlib.sha256(('review-hard-v4:' + d['id']).encode()).hexdigest()[:32]
        row = parent.model_copy(deep=True, update={'sample_id': identity_id, 'audio_path': item['audio_path'],
            'audio_sha256': item['audio_sha256'], 'decoded_audio_sha256': decoded_audio_hash([settings.audio_root / item['audio_path']]),
            'duration_sec': item['duration_sec'], 'channel': 0, 'group_id': None, 'variant_of': None,
            'original_utterance_id': parent.original_utterance_id + '@review-hard-v4:' + d['id'],
            'reference_text': None, 'transcript_status': 'missing', 'scope': 'unknown', 'scope_verified': False,
            'primary': False, 'continuous_recording': False,
            'annotation_provenance': {'annotator': None, 'reviewed_audio': False, 'queue': 'disputed_train',
                'source_sample_id': parent.sample_id, 'source_audio_sha256': parent.audio_sha256,
                'original_start_sec': item['original_start_sec'], 'original_end_sec': item['original_end_sec'],
                'automatic_training_eligible': False, 'review_reasons': d['reasons']}})
        review.append(row)
        drafts = cached[d['id']]
        large = read(OUT / 'predictions' / (d['id'] + '.json'))
        save_new(PACKET / 'drafts' / (identity_id + '.json'), {'status': 'machine', 'human_verified': False,
            'text': 'SMALL:\n' + drafts['small']['hypothesis'] + '\n\nMEDIUM:\n' + drafts['medium']['hypothesis']
                + '\n\nLARGE:\n' + large['hypothesis']})
    # New dev windows selected by metadata and time only, never ASR quality.
    held = list(dev) + load_manifest(WORK / 'data/curated/annotation-packet-v1/dev.jsonl')
    dev_queue = []
    for parent in [s for s in raw_dev if not s.variant_of]:
        existing = [(s.annotation_provenance['original_start_sec'], s.annotation_provenance['original_end_sec'])
            for s in held if s.annotation_provenance['source_sample_id'] == parent.sample_id]
        candidates = [(float(start), float(start+10)) for start in range(5, int(parent.duration_sec)-10, 15)
            if not any(overlaps((start, start+10), span) for span in existing)]
        # Spread six clips throughout every available recording (at most 42 clips).
        indices = np.linspace(0, len(candidates)-1, min(6, len(candidates))).round().astype(int) if candidates else []
        for index in indices:
            start, end = candidates[index]
            identity_id = hashlib.sha256(f'blind-dev-v4:{parent.sample_id}:{start}:{end}'.encode()).hexdigest()[:32]
            crop = clipped(parent, identity_id, start, end, 'cockpit-hard-v4-review')
            row = parent.model_copy(deep=True, update={**crop, 'group_id': None, 'variant_of': None,
                'original_utterance_id': parent.original_utterance_id + f'@blind-dev-v4:{start}:{end}',
                'reference_text': None, 'transcript_status': 'missing', 'scope': 'unknown', 'scope_verified': False,
                'primary': False, 'continuous_recording': False,
                'annotation_provenance': {'annotator': None, 'reviewed_audio': False, 'queue': 'blind_dev',
                    'source_sample_id': parent.sample_id, 'source_audio_sha256': parent.audio_sha256,
                    'original_start_sec': start, 'original_end_sec': end,
                    'automatic_training_eligible': False, 'selection': 'six_time_stratified_unseen_windows_per_original_dev_recording',
                    'draft_available': False}})
            dev_queue.append(row)
            save_new(PACKET / 'drafts' / (identity_id + '.json'), {'status': 'missing', 'human_verified': False,
                'text': 'Для независимой проверки этот фрагмент подготовлен без машинной расшифровки. Запишите услышанное по аудио.'})
    packet_rows = review + dev_queue
    validate_groups(packet_rows)
    check_training_partitions(review, dev_queue)
    write_manifest(PACKET / 'train.jsonl', review)
    write_manifest(PACKET / 'dev.jsonl', dev_queue)
    save_new(PACKET / 'packet.json', {'items': [{'id': r.sample_id, 'split': r.split, 'source': r.annotation_provenance['source_sample_id'],
        'duration_sec': r.duration_sec, 'queue': r.annotation_provenance['queue']} for r in packet_rows],
        'human_verified': 0, 'quality_evidence': False, 'drafts_hidden_by_default': True})
    save_new(OUT / 'decisions.json', decisions)
    save_new(OUT / 'noise-audit.json', noise_audit)
    save_new(OUT / 'replaced-old-intervals.json', replaced)
    result = {'hard_candidates': len(items), 'accepted_hard': len(accepted), 'hard_minutes': sum(s.duration_sec for s in accepted)/60,
        'retained_old': len(retained), 'replaced_old_overlaps': len(replaced), 'clean_pairs': len(clean),
        'noisy_pairs': len(noise), 'noisy_minutes': sum(s.duration_sec for s in noise)/60,
        'train_pairs': len(train), 'train_minutes': sum(s.duration_sec for s in train)/60,
        'unique_clean_minutes': sum(s.duration_sec for s in clean)/60,
        'train_speakers': len({sp for s in train for sp in s.speaker_ids}),
        'review_train': len(review), 'review_dev': len(dev_queue),
        'review_dev_recordings': len({s.recording_id for s in dev_queue}),
        'review_dev_speakers': len({sp for s in dev_queue for sp in s.speaker_ids}),
        'review_minutes': sum(s.duration_sec for s in packet_rows)/60,
        'teacher_rejection_reasons': dict(Counter(reason for d in rejected for reason in d['reasons'])),
        'train_sha256': file_hash(DATA / 'train.jsonl'), 'dev_sha256': file_hash(DATA / 'dev.jsonl'),
        'human_verified_added': 0, 'quality_evidence': False, 'test_accessed': False}
    save_new(OUT / 'result.json', result)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'infer', 'assemble'])
    args = parser.parse_args()
    {'prepare': prepare, 'infer': infer, 'assemble': assemble}[args.stage]()
