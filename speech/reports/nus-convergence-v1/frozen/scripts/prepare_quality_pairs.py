"""Train-only, conservative publisher pairs; never promotes machine text to gold."""

import argparse
import json
import math
import time
from collections import Counter
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from north55_speech.asr import load_model, local_model_manifest
from north55_speech.core import atomic_json, digest, file_hash, now, settings
from north55_speech.datasets import (
    decoded_audio_hash,
    load_manifest,
    validate_groups,
    write_manifest,
)
from north55_speech.lora import validate_references
from north55_speech.metrics import lexical_normalizer_v1
from scripts.expand_publisher_pairs import FAMILIES, family_for
from scripts.publisher_alignment import align, locate, number_tokens

ROOT = Path('/pairs')
REPORT = Path('/study')
OLD = Path('/old')
RATE = 16000
MODELS = {'small': 'small', 'large': 'whisper-large-v3-systran-ct2'}
POLICY = {
    'version': 'publisher_pause_consensus_v1',
    'train_only': True,
    'target_min_seconds': 8,
    'maximum_span_seconds': 24,
    'maximum_joined_pause_seconds': 2,
    'padding_seconds': .2,
    'minimum_words': 8,
    'boundary_margin_seconds': .08,
    'minimum_word_probability': .35,
    'small_language': 'en',
    'large_language': 'auto',
    'require_large_detected_language': 'en',
    'require_exact_lexical_three_way_agreement': True,
    'old_alignment_thresholds_unchanged': True,
    'human_verified': False,
    'quality_evidence': False,
    'release_promoted': False,
}
VAD = {'threshold': .5, 'min_speech_duration_ms': 100, 'min_silence_duration_ms': 300,
       'speech_pad_ms': 0, 'max_speech_duration_s': float('inf')}


def read(path):
    return json.loads(path.read_bytes())


def identity():
    names = [Path(__file__), Path('/app/scripts/publisher_alignment.py'),
             Path('/app/scripts/expand_publisher_pairs.py'), Path('/app/uv.lock'),
             Path('/app/ACCEPTANCE.yaml'), Path('/app/SPEC.md'), Path('/app/SOURCES.md')]
    names += sorted(Path('/app/src/north55_speech').glob('*.py'))
    return {str(p.relative_to('/app')): file_hash(p) for p in names}


def pause_windows(intervals, total):
    """Never cut a continuous VAD speech interval to fit the duration budget."""
    groups, held, current = [], [], None
    for start, end in intervals:
        if not 0 <= start < end <= total:
            raise ValueError('Invalid VAD timeline')
        if current is not None and start < current[1]:
            raise ValueError('Overlapping VAD intervals')
        if end - start > POLICY['maximum_span_seconds'] * RATE:
            if current:
                groups.append(current)
                current = None
            held.append({'start_sample': start, 'end_sample': end, 'reason': 'no_safe_pause_before_limit'})
            continue
        if current is None:
            current = [start, end]
        elif (current[1] - current[0] < POLICY['target_min_seconds'] * RATE
              and start - current[1] <= POLICY['maximum_joined_pause_seconds'] * RATE
              and end - current[0] <= POLICY['maximum_span_seconds'] * RATE):
            current[1] = end
        else:
            groups.append(current)
            current = [start, end]
    if current:
        groups.append(current)
    result = []
    # Padding cannot cross another speech interval, including a held long span.
    all_spans = sorted(groups + [[x['start_sample'], x['end_sample']] for x in held])
    for start, end in groups:
        i = all_spans.index([start, end])
        previous = all_spans[i-1][1] if i else 0
        following = all_spans[i+1][0] if i+1 < len(all_spans) else total
        left = min(round(POLICY['padding_seconds'] * RATE), (start-previous)//2)
        right = min(round(POLICY['padding_seconds'] * RATE), (following-end)//2)
        result.append((start-left, end+right))
    return result, held


def immutable_audio(path, audio):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        previous, rate = sf.read(path, dtype='float32')
        if rate != RATE or not np.array_equal(previous, audio):
            raise ValueError('Existing clip changed')
    else:
        tmp = path.with_suffix('.tmp')
        sf.write(tmp, audio, RATE, subtype='FLOAT', format='WAV')
        tmp.replace(path)


def prepare():
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    if (ROOT / 'plan.json').exists():
        validate()
        print('Existing immutable plan verified; no preparation rerun')
        return
    sources = load_manifest(Path('/source-train.jsonl'))
    if any(s.split != 'train' for s in sources):
        raise ValueError('Preparation accepts train originals only')
    validate_groups(sources)
    parents = [s for s in sources if s.variant_of is None and family_for(s.sample_id)]
    documents = {p.name: read(p) for p in (OLD / 'documents').glob('*.json')}
    ROOT.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    # Persist assumptions and hashes before data selection or ASR.
    preflight = {'policy': POLICY, 'code_sha256': identity(),
                 'source_manifest_sha256': file_hash(Path('/source-train.jsonl')),
                 'documents_sha256': {n: digest(v) for n, v in documents.items()},
                 'models': {s: local_model_manifest(n) for s, n in MODELS.items()},
                 'source_audio_sha256': {s.sample_id: s.audio_sha256 for s in parents},
                 'protocol_sha256': file_hash(REPORT / 'protocol.md')}
    preflight_path = ROOT / 'preflight.json'
    if preflight_path.exists() and read(preflight_path) != preflight:
        raise ValueError('Preparation identity changed; preserve previous attempt')
    atomic_json(preflight_path, preflight)
    rows, held = [], []
    for parent in parents:
        path = settings.audio_root / parent.audio_path
        if file_hash(path) != parent.audio_sha256:
            raise ValueError('Source audio changed')
        audio, rate = sf.read(path, dtype='float32', always_2d=True)
        if parent.channel >= audio.shape[1] or not np.isfinite(audio).all():
            raise ValueError('Invalid original audio/channel')
        divisor = math.gcd(rate, RATE)
        audio = resample_poly(audio[:, parent.channel], RATE//divisor, rate//divisor).astype(np.float32)
        timestamps = get_speech_timestamps(audio, VadOptions(**VAD), sampling_rate=RATE)
        spans, rejected = pause_windows([(int(x['start']), int(x['end'])) for x in timestamps], len(audio))
        held.extend({'source': parent.sample_id, **r} for r in rejected)
        for start, end in spans:
            sample_id = digest({'version': POLICY['version'], 'parent': parent.sample_id,
                                'start': start, 'end': end})[:32]
            output = settings.audio_root / 'pair-quality-v1' / f'{sample_id}.wav'
            immutable_audio(output, audio[start:end])
            rows.append({'id': sample_id, 'source': parent.sample_id, 'family': family_for(parent.sample_id),
                         'start_sample': start, 'end_sample': end, 'original_start_sec': start/RATE,
                         'original_end_sec': end/RATE, 'duration_sec': (end-start)/RATE,
                         'audio_path': str(output.relative_to(settings.audio_root)), 'audio_sha256': file_hash(output)})
        print(json.dumps({'source': parent.sample_id, 'windows': len(spans), 'held': len(rejected)}), flush=True)
    atomic_json(ROOT / 'sources.json', {s.sample_id: s.model_dump() for s in parents})
    atomic_json(ROOT / 'documents.json', documents)
    plan = {**preflight, 'frozen_at': now().isoformat(), 'items': rows, 'held_spans': held,
            'sources_sha256': file_hash(ROOT / 'sources.json'), 'documents_file_sha256': file_hash(ROOT / 'documents.json'),
            'test_accessed': False, 'dev_used_for_pair_selection': False,
            'dev_search_budget': {'previous_used': 16, 'limit': 16, 'new_configurations': 0,
                                  'training_comparison': 'BLOCKED_SEARCH_BUDGET_EXHAUSTED'},
            'limitations': ['Consensus is a filter, not human verification or calibrated reliability.',
                            'Both recognizers belong to the Whisper family and can share errors.',
                            'Pause and word-margin checks cannot guarantee complete audible words.',
                            'English publisher family is not human-verified language/scope.',
                            'Clean originals only; no copied targets for noisy variants or dev-to-train moves.']}
    atomic_json(ROOT / 'plan.json', plan)
    atomic_json(REPORT / 'plan.json', plan)
    print(json.dumps({'status': 'FROZEN', 'train_sources': len(parents), 'windows': len(rows)}))


def validate():
    plan = read(ROOT / 'plan.json')
    if plan['code_sha256'] != identity() or plan['policy'] != POLICY:
        raise ValueError('Frozen code or policy changed')
    if plan['protocol_sha256'] != file_hash(REPORT / 'protocol.md'):
        raise ValueError('Frozen protocol changed')
    for s, name in MODELS.items():
        if local_model_manifest(name) != plan['models'][s]:
            raise ValueError('Frozen model manifest changed')
    return plan


def options(system):
    return {'beam_size': 5, 'temperature': 0, 'task': 'transcribe', 'vad_filter': False,
            'word_timestamps': True, 'condition_on_previous_text': False, 'initial_prompt': None,
            'hotwords': None, 'language': 'en' if system == 'small' else None}


def infer(system):
    plan = validate()
    model = load_model(MODELS[system], 'cuda', 'float16', digest(plan['models'][system]))
    folder = ROOT / system / 'predictions'
    runtime = {'started_at': now().isoformat(), 'plan_sha256': file_hash(ROOT / 'plan.json'),
               'system': system, 'options': options(system), 'new_calls': 0, 'reused': 0}
    started = time.perf_counter()
    for i, item in enumerate(plan['items']):
        path = folder / f'{item["id"]}.json'
        request = digest({'item': item, 'plan': runtime['plan_sha256'], 'system': system, 'options': options(system)})
        if path.exists():
            if read(path)['request_sha256'] != request:
                raise ValueError('Resume identity mismatch')
            runtime['reused'] += 1
            continue
        audio_path = settings.audio_root / item['audio_path']
        if file_hash(audio_path) != item['audio_sha256']:
            raise ValueError('Frozen clip changed')
        audio, rate = sf.read(audio_path, dtype='float32')
        if rate != RATE or audio.ndim != 1 or not np.isfinite(audio).all():
            raise ValueError('Invalid prepared audio')
        record = {'id': item['id'], 'request_sha256': request, 'hypothesis': '', 'words': [], 'error': None}
        begin = time.perf_counter()
        try:
            segments, info = model.transcribe(audio, **options(system))
            segments = list(segments)
            record.update(hypothesis=' '.join(s.text.strip() for s in segments),
                          detected_language=info.language, language_probability=float(info.language_probability),
                          words=[{'word': w.word, 'start': float(w.start), 'end': float(w.end),
                                  'probability': float(w.probability)} for s in segments for w in s.words or []])
        except Exception as exc:
            record['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        record['asr_seconds'] = time.perf_counter() - begin
        atomic_json(path, record)
        runtime['new_calls'] += 1
        if i % 25 == 0 or i == len(plan['items'])-1:
            print(json.dumps({'system': system, 'completed': i+1, 'total': len(plan['items'])}), flush=True)
    runtime.update(finished_at=now().isoformat(), wall_seconds=time.perf_counter()-started,
                   prediction_sha256={p.name: file_hash(p) for p in sorted(folder.glob('*.json'))})
    # Each invocation keeps its own runtime; successful record identities are immutable.
    atomic_json(ROOT / system / f'runtime-{time.time_ns()}.json', runtime)
    atomic_json(ROOT / system / 'execution.json', runtime)


def agreement_reasons(small, large, target, duration):
    reasons = []
    if small.get('error') or large.get('error'):
        return ['asr_failure']
    if large.get('detected_language') != 'en':
        reasons.append('large_unforced_language_not_english')
    texts = [lexical_normalizer_v1(r['hypothesis']) for r in (small, large)]
    normalized = lexical_normalizer_v1(target)
    if len(normalized.split()) < POLICY['minimum_words']:
        reasons.append('insufficient_words')
    if not normalized or any(t != normalized for t in texts):
        reasons.append('lexical_disagreement')
    if any(number_tokens(t) != number_tokens(target) for t in texts):
        reasons.append('numeric_disagreement')
    for system, record in [('small', small), ('large', large)]:
        words = record['words']
        if not words or any(not 0 <= w['start'] < w['end'] <= duration+.02 for w in words):
            reasons.append(f'{system}_invalid_word_times')
        elif (words[0]['start'] < POLICY['boundary_margin_seconds']
              or words[-1]['end'] > duration-POLICY['boundary_margin_seconds']):
            reasons.append(f'{system}_word_at_clip_boundary')
        if not words or any(not math.isfinite(w['probability']) or not POLICY['minimum_word_probability'] <= w['probability'] <= 1 for w in words):
            reasons.append(f'{system}_low_word_score')
    return reasons


def assemble():
    from north55_speech.datasets import Sample

    plan = validate()
    for name, key in [('sources.json', 'sources_sha256'), ('documents.json', 'documents_file_sha256')]:
        if file_hash(ROOT / name) != plan[key]:
            raise ValueError('Frozen source metadata changed')
    sources = {k: Sample.model_validate(v) for k, v in read(ROOT / 'sources.json').items()}
    documents = read(ROOT / 'documents.json')
    executions = {s: read(ROOT / s / 'execution.json') for s in MODELS}
    for execution in executions.values():
        if execution['plan_sha256'] != file_hash(ROOT / 'plan.json') or len(execution['prediction_sha256']) != len(plan['items']):
            raise ValueError('Incomplete frozen inference population')
    model = None
    accepted, diagnostics = [], []
    for item in plan['items']:
        responses = {}
        for system in MODELS:
            path = ROOT / system / 'predictions' / f'{item["id"]}.json'
            if file_hash(path) != executions[system]['prediction_sha256'][path.name]:
                raise ValueError('Frozen prediction changed')
            responses[system] = read(path)
        small, large = responses['small'], responses['large']
        document = max((documents[f'{n}.json'] for n in FAMILIES[item['family']]),
                       key=lambda d: locate(small['hypothesis'], d)['matched_tokens'])
        proposal = locate(small['hypothesis'], document)
        reasons = agreement_reasons(small, large, proposal['text'], item['duration_sec'])
        if not reasons:
            if model is None:
                model = load_model('small', 'cuda', 'float16', digest(plan['models']['small']))
            audio_path = settings.audio_root / item['audio_path']
            if file_hash(audio_path) != item['audio_sha256']:
                raise ValueError('Alignment audio changed')
            audio, _ = sf.read(audio_path, dtype='float32')
            proposal = align(model, audio, document, small['hypothesis'], item['original_start_sec'])
            reasons += proposal['reasons']
        proposal.update(selection_method=POLICY['version'], extra_reasons=reasons, item=item)
        path = ROOT / 'proposals' / f'{item["id"]}.json'
        if path.exists() and read(path) != proposal:
            raise ValueError('Immutable proposal changed')
        atomic_json(path, proposal)
        diagnostics.append({'id': item['id'], 'source': item['source'], 'eligible': not reasons, 'reasons': reasons})
        if reasons:
            continue
        parent = sources[item['source']]
        row = parent.model_dump() | {
            'sample_id': item['id'], 'audio_path': item['audio_path'], 'audio_sha256': item['audio_sha256'],
            'decoded_audio_sha256': decoded_audio_hash([settings.audio_root / item['audio_path']]),
            'duration_sec': item['duration_sec'], 'channel': 0, 'variant_of': None,
            'original_utterance_id': f'{parent.original_utterance_id}@{item["start_sample"]}:{item["end_sample"]}',
            'language': 'en', 'reference_text': proposal['text'], 'transcript_status': 'weak',
            'scope': 'read_cockpit', 'scope_verified': False, 'primary': False, 'clean_control': False,
            'entities_status': 'missing', 'events_status': 'missing', 'temporal_status': 'missing',
            'diarization_status': 'missing', 'critical_entities': None, 'events': None,
            'labels': None, 'salient_for_review': None, 'unintelligible': [],
            'annotation_provenance': {
                'method': proposal['method'], 'selection_method': POLICY['version'],
                'publisher_transcript': True, 'reviewed_audio': False, 'annotator': None,
                'source_file': proposal['source_file'], 'source_sha256': proposal['source_sha256'],
                'alignment_sha256': file_hash(path), 'preparation_plan_sha256': file_hash(ROOT / 'plan.json'),
                'automatic_training_eligible': True, 'eligibility_reasons': [],
                'source_sample_id': parent.sample_id, 'original_start_sec': item['original_start_sec'],
                'original_end_sec': item['original_end_sec'],
                'language_basis': 'English document + small EN / large unforced consensus; not human verification'},
        }
        accepted.append(Sample.model_validate(row))
    dev_path = OLD / 'training/dev.jsonl'
    dev = load_manifest(dev_path)
    groups = validate_groups(accepted + dev)
    if accepted:
        validate_references(accepted, dev, {'reference_policy': 'publisher_weak_exploratory_v1',
                                          'quality_evidence': False, 'selection_allowed': False, 'max_steps': 40})
    write_manifest(ROOT / 'training/train.jsonl', accepted)
    target_dev = ROOT / 'training/dev.jsonl'
    if target_dev.exists() and target_dev.read_bytes() != dev_path.read_bytes():
        raise ValueError('Existing development manifest changed')
    target_dev.write_bytes(dev_path.read_bytes())
    old_train = load_manifest(OLD / 'training/train.jsonl')
    result = {'status': 'READY_WEAK_PAIRS' if accepted else 'NEEDS_MORE_DATA',
              'plan_sha256': file_hash(ROOT / 'plan.json'), 'policy': POLICY,
              'considered_train_windows': len(plan['items']), 'accepted_train_pairs': len(accepted),
              'accepted_minutes': sum(s.duration_sec for s in accepted)/60,
              'accepted_speakers': len({v for s in accepted for v in s.speaker_ids}),
              'old_train_pairs': len(old_train), 'old_train_minutes': sum(s.duration_sec for s in old_train)/60,
              'unchanged_dev_pairs': len(dev), 'dev_sha256': file_hash(target_dev), 'groups': groups,
              'rejection_reasons': dict(Counter(r for d in diagnostics for r in d['reasons'])),
              'items': diagnostics, 'asr_calls': len(plan['items'])*2,
              'asr_failures': {s: sum(read(ROOT / s / 'predictions' / f'{i["id"]}.json')['error'] is not None for i in plan['items']) for s in MODELS},
              'true_pair_accuracy': None, 'human_verified_pairs': 0, 'quality_gate': 'NEEDS_MORE_DATA',
              'training_comparison': plan['dev_search_budget']['training_comparison'],
              'test_accessed': False, 'release_promoted': False, 'limitations': plan['limitations']}
    atomic_json(ROOT / 'preparation-report.json', result)
    atomic_json(REPORT / 'preparation-report.json', {k: v for k, v in result.items() if k != 'items'})
    print(json.dumps({k: v for k, v in result.items() if k not in {'items', 'limitations', 'groups'}}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'infer', 'assemble'])
    parser.add_argument('--system', choices=list(MODELS))
    args = parser.parse_args()
    if args.action == 'infer':
        if not args.system:
            parser.error('--system is required for inference')
        infer(args.system)
    else:
        {'prepare': prepare, 'assemble': assemble}[args.action]()
