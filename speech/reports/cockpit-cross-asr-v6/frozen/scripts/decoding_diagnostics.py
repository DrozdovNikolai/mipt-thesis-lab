"""Frozen, offline decoding/VAD diagnostics; no training or release selection."""

import argparse
import importlib.metadata
import json
import platform
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.asr import AsrProvider, local_model_manifest
from north55_speech.audio import RATE, VadProvider
from north55_speech.benchmark import code_hash, scorer_hash
from north55_speech.core import atomic_json, file_hash, now
from north55_speech.metrics import corpus_counts, edit_counts, paired_cluster_bootstrap
from north55_speech.schemas import PipelineConfig

ROOT = Path('/study')
PRIOR = Path('/prior')
REFERENCES = Path('/scoring/references.json')
SYSTEMS = tuple(f'{model}_{mode}' for model in ('parent', 'augmented')
                for mode in ('baseline', 'text', 'vad'))
VAD = dict(enabled=True, threshold=.4, min_speech_duration_ms=50,
           min_silence_duration_ms=400, speech_pad_ms=250, max_speech_duration_s=30.)


def read(path):
    return json.loads(path.read_bytes())


def identity():
    import faster_whisper
    asset = Path(faster_whisper.__file__).parent / 'assets/silero_vad_v6.onnx'
    return {'driver_sha256': file_hash(Path(__file__)), 'code_sha256': code_hash(),
            'scorer_sha256': scorer_hash(), 'vad_weights_sha256': file_hash(asset),
            'acceptance_sha256': file_hash(Path('/app/ACCEPTANCE.yaml')),
            'baseline_sha256': file_hash(Path('/app/configs/baseline.yaml')),
            'uv_lock_sha256': file_hash(Path('/app/uv.lock')),
            'protocol_sha256': file_hash(ROOT / 'protocol.md')}


def select_inputs(items):
    """Select by existing metadata only; never read answers for membership."""
    selected = [dict(i) for i in items if i['cohort'] in {
        'general_clean', 'general_ru', 'partial_human_dev'} or (
        i['cohort'] in {'publisher_weak_dev', 'voici_mix_0dB', 'voici_mix_10dB'}
        and i.get('reference_eligible') is True)]
    for cohort in ('noise_only', 'bleriot_b_noise'):
        duration = 0
        for item in sorted((i for i in items if i['cohort'] == cohort),
                           key=lambda i: (i['audio_sha256'], i['id'])):
            selected.append(dict(item))
            duration += item['duration_sec']
            if duration >= 300:
                break
        if duration < 300:
            raise ValueError('Less than five minutes of noise in a declared cohort')
    originals = sorted(selected, key=lambda i: i['id'])
    quiet = []
    for item in originals:
        if item['cohort'] == 'partial_human_dev' or (
                item['cohort'] == 'general_clean' and item['duration_sec'] <= 4):
            quiet.append({**item, 'id': item['id'] + '--quiet12', 'reference_id': item['id'],
                          'cohort': 'quiet_' + item['cohort'], 'gain_db': -12.,
                          'condition': 'diagnostic_amplitude_minus12dB', 'primary': False})
    return [{**i, 'reference_id': i['id'], 'gain_db': 0.} for i in originals] + quiet


def prepare():
    if (ROOT / 'plan.json').exists():
        raise ValueError('Preserve the existing frozen plan')
    previous = read(PRIOR / 'plan.json')
    if file_hash(PRIOR / 'inputs.json') != previous['inputs_sha256']:
        raise ValueError('Previous input manifest changed')
    items = select_inputs(read(PRIOR / 'inputs.json'))
    configs, models = {}, {}
    for model in ('parent', 'augmented'):
        config = previous['configs'][model]
        if (config['device'] != 'cuda' or config['compute_type'] != 'float16'
                or config['vad']['enabled'] or config['denoise']['enabled']
                or config['hotwords'] or config['redecode'] or not config['word_timestamps']):
            raise ValueError('Unexpected previous baseline')
        models[model] = {'name': config['model'], 'manifest': local_model_manifest(config['model']),
                         'manifest_sha256': file_hash(Path('/models') / config['model'] / 'manifest.json')}
        for mode in ('baseline', 'text', 'vad'):
            configs[f'{model}_{mode}'] = PipelineConfig.model_validate(
                config | ({'name': 'diagnostic-vad', 'vad': VAD} if mode == 'vad' else {})).model_dump()
    # Save immutable controls separately. Inference never mounts this directory.
    for model in ('parent', 'augmented'):
        execution = read(PRIOR / model / 'execution.json')
        if execution['plan_sha256'] != file_hash(PRIOR / 'plan.json'):
            raise ValueError('Prior execution identity differs')
        records = {}
        for item in items:
            if item['gain_db']:
                continue
            path = PRIOR / model / 'predictions' / f'{item["id"]}.json'
            if file_hash(path) != execution['prediction_sha256'][path.name]:
                raise ValueError('Prior prediction changed')
            record = read(path)
            if (record['config'] != previous['configs'][model]
                    or record['audio_sha256'] != item['audio_sha256']
                    or record['effective_options']['without_timestamps'] is not False
                    or record['effective_options']['word_timestamps'] is not True):
                raise ValueError('Incompatible reused baseline')
            records[item['id']] = record
        atomic_json(ROOT / 'controls' / f'{model}.json', records)
    atomic_json(ROOT / 'inputs.json', items)
    atomic_json(ROOT / 'plan.json', {'frozen_at': now().isoformat(), **identity(),
        'previous_plan_sha256': file_hash(PRIOR / 'plan.json'),
        'references_sha256': previous['references_sha256'],
        'inputs_sha256': file_hash(ROOT / 'inputs.json'), 'input_count': len(items),
        'configs': configs, 'models': models, 'systems': list(SYSTEMS),
        'controls_sha256': {m: file_hash(ROOT / 'controls' / f'{m}.json') for m in models},
        'options_overrides': {s: {'without_timestamps': s.endswith('_text')} for s in SYSTEMS},
        'new_configuration_budget': 4, 'previous_configurations': 18, 'cumulative_configurations': 22,
        'additional_budget_authorization': 'User approved two fixed diagnostics on both saved checkpoints; SPEC section 362; ACCEPTANCE unchanged.',
        'test_accessed': False, 'release_promoted': False,
        'selection_policy': 'Two separate effects; no combination, tuning, retraining or release selection.',
        'limitations': [
            'All originals are exposed dev/diagnostic data, never final test.',
            'Only five partially reviewed cockpit utterances; weak publisher alignments stay weak.',
            'Quiet variants inherit references and groups; they are not independent observations.',
            'Short general EN utterances are not gold cockpit commands. Human word boundaries and critical entity labels are insufficient.',
            'Reused baseline outputs are hash-verified historical results; timing is not a fresh speed comparison.',
            'Noise references rely on publisher declarations, not independent local listening.',
            'Two weights are assessed separately; adaptation is not a same-checkpoint comparison.']})
    print(json.dumps({'status': 'FROZEN', 'inputs': len(items), 'quiet': sum(bool(i['gain_db']) for i in items)}), flush=True)


def validate():
    plan = read(ROOT / 'plan.json')
    if any(plan[k] != v for k, v in identity().items()):
        raise ValueError('Frozen implementation/protocol/weights changed')
    if file_hash(ROOT / 'inputs.json') != plan['inputs_sha256']:
        raise ValueError('Frozen input population changed')
    for value in plan['models'].values():
        if file_hash(Path('/models') / value['name'] / 'manifest.json') != value['manifest_sha256']:
            raise ValueError('ASR manifest changed')
    return plan


class DiagnosticProvider(AsrProvider):
    def __init__(self, config, without_timestamps):
        self.without_timestamps = without_timestamps
        if without_timestamps:
            from north55_speech.text_windows import load_text_window_model
            super().__init__(config, model_loader=load_text_window_model)
        else:
            super().__init__(config)

    def options(self, language, retry=False):
        return super().options(language, retry) | {'without_timestamps': self.without_timestamps}


def validate_intervals(intervals, samples):
    previous_end = 0
    for start, end in intervals:
        if not 0 <= previous_end <= start < end <= samples:
            raise ValueError('VAD intervals overlap or leave the original timeline')
        previous_end = end


def transcribe_windows(provider, waveform, intervals, language, prefix):
    """Keep original sample offsets. Never concatenate pauses or deduplicate text."""
    validate_intervals(intervals, len(waveform))
    segments, windows = [], []
    for index, (start, end) in enumerate(intervals):
        found = provider.transcribe(waveform[start:end], start, language,
                                    f'{prefix}-window{index}', lambda: None)
        for segment in found:
            for value in [segment, *segment.words]:
                if not start / RATE <= value.start_sec <= value.end_sec <= end / RATE + 1e-6:
                    raise ValueError('Alignment left its original audio window')
        segments.extend(found)
        windows.append({'start_sample': start, 'end_sample': end, 'segment_count': len(found),
                        'effective_options': provider.options(language)})
    return segments, windows


def load_audio(item):
    path = Path('/audio') / item['audio_path']
    if not path.resolve().is_relative_to(Path('/audio').resolve()) or file_hash(path) != item['audio_sha256']:
        raise ValueError('Audio path or checksum differs')
    waveform, rate = sf.read(path, dtype='float32')
    if rate != RATE or waveform.ndim != 1 or not np.isfinite(waveform).all():
        raise ValueError('Expected finite 16 kHz mono audio')
    if abs(len(waveform) / RATE - item['duration_sec']) > 1 / RATE:
        raise ValueError('Audio duration differs')
    return (waveform * np.float32(10 ** (item['gain_db'] / 20))).astype('float32')


def infer(system, cpu=False):
    plan = validate()
    config = PipelineConfig.model_validate(plan['configs'][system])
    items = read(ROOT / 'inputs.json')
    if system.endswith('_baseline'):
        items = [i for i in items if i['gain_db']]
    if cpu:
        # Predetermined smoke membership; not used to choose a quality variant.
        config = config.model_copy(update={'device': 'cpu', 'compute_type': 'int8'})
        items = [next(i for i in items if i['cohort'] == c) for c in
                 ('partial_human_dev', 'general_ru', 'noise_only', 'quiet_general_clean')]
    output = ROOT / ('cpu-' + system if cpu else system)
    output.mkdir(exist_ok=True)
    attempt = now().strftime('%Y%m%dT%H%M%S%fZ')
    started = time.perf_counter()
    runtime = {'started_at': now().isoformat(), 'attempt': attempt, 'system': system,
               'plan_sha256': file_hash(ROOT / 'plan.json'), 'cpu_smoke': cpu,
               'python': platform.python_version(), 'new_records': 0, 'resumed_records': 0,
               'packages': {p: importlib.metadata.version(p) for p in
                            ('faster-whisper', 'ctranslate2', 'numpy', 'soundfile')}, 'status': 'RUNNING'}
    try:
        provider = DiagnosticProvider(config, plan['options_overrides'][system]['without_timestamps'])
        runtime.update(actual_device=provider.model.model.device,
                       actual_precision=provider.model.model.compute_type,
                       initialization_sec=provider.initialization_sec)
        if not cpu and (runtime['actual_device'], runtime['actual_precision']) != ('cuda', 'float16'):
            raise ValueError('GPU precision differs')
        for index, item in enumerate(items):
            destination = output / 'predictions' / (item['id'] + '.json')
            options = provider.options(item['input_language'])
            if destination.exists():
                record = read(destination)
                if (record['plan_sha256'] != runtime['plan_sha256'] or record['config'] != config.model_dump()
                        or record['effective_options'] != options or any(record[k] != v for k, v in item.items())):
                    raise ValueError('Resume record differs from the frozen request')
                if record['runtime_failure'] is not None:
                    raise ValueError('Existing failed prediction requires a new audited attempt, not silent overwrite')
                runtime['resumed_records'] += 1
                continue
            record = {**item, 'system': system, 'plan_sha256': runtime['plan_sha256'],
                      'config': config.model_dump(), 'effective_options': options,
                      'hypothesis': '', 'segments': [], 'windows': [], 'runtime_failure': None}
            begin = time.perf_counter()
            try:
                waveform = load_audio(item)
                import hashlib
                record['effective_waveform_sha256'] = hashlib.sha256(waveform.astype('<f4').tobytes()).hexdigest()
                intervals = VadProvider().intervals(waveform, config.vad)
                record['retained_audio_seconds'] = sum(end - start for start, end in intervals) / RATE
                segments, windows = transcribe_windows(provider, waveform, intervals, item['input_language'], item['id'])
                record.update(hypothesis=' '.join(s.raw_asr_text.strip() for s in segments),
                              segments=[s.model_dump() for s in segments], windows=windows,
                              backend_audit=getattr(provider, 'last_backend_audit', None),
                              alignment={'words': sum(len(s.words) for s in segments),
                                         'nonempty_segments_without_words': sum(bool(s.raw_asr_text.strip()) and not s.words for s in segments),
                                         'zero_duration_words': sum(w.start_sec == w.end_sec for s in segments for w in s.words)})
            except Exception as exc:
                record['runtime_failure'] = {'type': type(exc).__name__, 'message': str(exc)}
            record['driver_elapsed_sec'] = time.perf_counter() - begin
            atomic_json(destination, record)
            runtime['new_records'] += 1
            if index % 20 == 0 or index == len(items) - 1:
                print(json.dumps({'system': system, 'completed': index + 1, 'total': len(items)}), flush=True)
        runtime['status'] = 'COMPLETED'
    except Exception as exc:
        runtime.update(status='FAILED', error={'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        runtime.update(finished_at=now().isoformat(), wall_sec=time.perf_counter() - started)
        atomic_json(output / f'runtime-{attempt}.json', runtime)
    paths = {i['id'] + '.json' for i in items}
    actual = {p.name: file_hash(p) for p in (output / 'predictions').glob('*.json')}
    if set(actual) != paths:
        raise ValueError('Unexpected prediction population')
    atomic_json(output / 'execution.json', {'plan_sha256': runtime['plan_sha256'],
        'prediction_sha256': actual, 'runtime_sha256': {p.name: file_hash(p) for p in output.glob('runtime-*.json')}})


def comparison(pairs):
    a = corpus_counts([p['baseline'] for p in pairs])
    b = corpus_counts([p['candidate'] for p in pairs])
    x, y = a['wer_lexical_corpus'], b['wer_lexical_corpus']
    bootstrap = paired_cluster_bootstrap(pairs, resamples=2000, seed=55, confidence=.95)
    return {'baseline': a, 'candidate': b, 'relative_reduction': (x - y) / x if x else None,
            'wer_delta': y - x if x is not None else None, 'bootstrap': bootstrap}


def score():
    plan = validate()
    if file_hash(REFERENCES) != plan['references_sha256']:
        raise ValueError('Reference file changed')
    refs, items = read(REFERENCES), read(ROOT / 'inputs.json')
    lookup = {}
    for model in ('parent', 'augmented'):
        controls_path = ROOT / 'controls' / (model + '.json')
        if file_hash(controls_path) != plan['controls_sha256'][model]:
            raise ValueError('Historical controls changed')
        for key, value in read(controls_path).items():
            lookup[model + '_baseline', key] = value
    executions = {}
    for system in SYSTEMS:
        execution = read(ROOT / system / 'execution.json')
        executions[system] = execution
        if execution['plan_sha256'] != file_hash(ROOT / 'plan.json'):
            raise ValueError('Execution plan differs')
        for filename, expected in execution['runtime_sha256'].items():
            if file_hash(ROOT / system / filename) != expected:
                raise ValueError('Runtime record changed')
        expected_ids = {i['id'] + '.json' for i in items if not system.endswith('_baseline') or i['gain_db']}
        if set(execution['prediction_sha256']) != expected_ids:
            raise ValueError('Incomplete/unexpected population')
        for filename, expected in execution['prediction_sha256'].items():
            path = ROOT / system / 'predictions' / filename
            if file_hash(path) != expected:
                raise ValueError('Prediction changed')
            record = read(path)
            if record['plan_sha256'] != execution['plan_sha256']:
                raise ValueError('Prediction plan differs')
            lookup[system, record['id']] = record
    rows, cohorts = [], {}
    for item in items:
        ref = refs[item['reference_id']]
        if ref is None:
            raise ValueError('Unexpected unscorable item in the fixed diagnostic subset')
        for system in SYSTEMS:
            record = lookup[system, item['id']]
            if record['audio_sha256'] != item['audio_sha256']:
                raise ValueError('Compared audio differs')
            record['score'] = edit_counts(ref, record['hypothesis'])
            rows.append({'id': item['id'], 'group_id': item['group_id'], 'cohort': item['cohort'],
                         'system': system, 'score': record['score'], 'runtime_failure': record['runtime_failure']})
    membership = {c: [i for i in items if i['cohort'] == c] for c in sorted({i['cohort'] for i in items})}
    membership['short_general_clean'] = [i for i in items if i['cohort'] == 'general_clean' and i['duration_sec'] <= 4]
    for cohort, members in membership.items():
        comparisons = {}
        for model in ('parent', 'augmented'):
            for mode in ('text', 'vad'):
                comparisons[model + '_' + mode] = comparison([
                    {'group_id': i['group_id'], 'baseline': lookup[model + '_baseline', i['id']]['score'],
                     'candidate': lookup[model + '_' + mode, i['id']]['score']} for i in members])
        cohorts[cohort] = {'inputs': len(members), 'independent_groups': len({i['group_id'] for i in members}),
            'channel_minutes': sum(i['duration_sec'] for i in members) / 60,
            'comparisons': comparisons, 'systems': {s: {
                'counts': corpus_counts([lookup[s, i['id']]['score'] for i in members]),
                'empty_hypotheses': sum(not lookup[s, i['id']]['hypothesis'].strip() for i in members),
                'runtime_failures': sum(lookup[s, i['id']]['runtime_failure'] is not None for i in members),
                'inserted_words_per_minute': sum(lookup[s, i['id']]['score']['I'] for i in members) / (sum(i['duration_sec'] for i in members) / 60)
            } for s in SYSTEMS}}
    failures = {s: sum(lookup[s, i['id']]['runtime_failure'] is not None for i in items) for s in SYSTEMS}
    gates = {}
    for system in (s for s in SYSTEMS if not s.endswith('_baseline')):
        model = system.split('_')[0]
        human = cohorts['partial_human_dev']['comparisons'][system]
        clean = cohorts['general_clean']['comparisons'][system]
        ru = cohorts['general_ru']['comparisons'][system]
        noise_ok = all(cohorts[c]['systems'][system]['inserted_words_per_minute'] <=
                       cohorts[c]['systems'][model + '_baseline']['inserted_words_per_minute']
                       for c in ('noise_only', 'bleriot_b_noise'))
        gates[system] = {
            'human_dev_point_target': 'PASS' if human['relative_reduction'] >= .1 else 'FAIL',
            'clean_guard': 'PASS' if clean['wer_delta'] <= .01 else 'FAIL',
            'ru_guard': 'PASS' if ru['wer_delta'] <= .01 else 'FAIL',
            'noise_guard': 'PASS' if noise_ok else 'FAIL',
            'runtime_guard': 'PASS' if failures[system] == 0 else 'FAIL',
            'statistical_confirmation': 'INCONCLUSIVE',
            'paired_ci_excludes_zero': human['bootstrap']['upper'] is not None and human['bootstrap']['upper'] < 0,
            'statistical_limitation': 'Only three exposed human-dev groups; independent acceptance population is insufficient.',
            'critical_entities': 'NEEDS_MORE_DATA', 'quiet_short_command_recall': 'NEEDS_MORE_DATA',
            'release': 'FAIL' if (human['relative_reduction'] < .1 or clean['wer_delta'] > .01
                                  or ru['wer_delta'] > .01 or not noise_ok or failures[system]) else 'NEEDS_MORE_DATA'}
    alignment = {s: {'words': sum(lookup[s, i['id']].get('alignment', {}).get('words', 0) for i in items),
        'nonempty_segments_without_words': sum(lookup[s, i['id']].get('alignment', {}).get('nonempty_segments_without_words', 0) for i in items),
        'zero_duration_words': sum(lookup[s, i['id']].get('alignment', {}).get('zero_duration_words', 0) for i in items)}
        for s in SYSTEMS if not s.endswith('_baseline')}
    result = {'status': 'EXECUTED_DIAGNOSTIC', 'plan_sha256': file_hash(ROOT / 'plan.json'),
              'input_count': len(items), 'cohorts': cohorts, 'gates': gates, 'alignment': alignment,
              'runtime_failures': failures, 'records': len(rows),
              'new_predictions': sum(len(e['prediction_sha256']) for e in executions.values()),
              'asr_quality_gate': 'NEEDS_MORE_DATA', 'nlp_quality_gate': 'NEEDS_MORE_DATA',
              'temporal_detection_gate': 'NEEDS_MORE_DATA', 'test_accessed': False,
              'release_promoted': False, 'limitations': plan['limitations']}
    atomic_json(ROOT / 'scored-counts.json', rows)
    atomic_json(ROOT / 'comparison.json', result)
    print(json.dumps({'status': result['status'], 'gates': gates, 'runtime_failures': failures}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'infer', 'cpu', 'score'))
    parser.add_argument('--system', choices=SYSTEMS)
    args = parser.parse_args()
    if args.action in ('infer', 'cpu'):
        if not args.system or (args.action == 'cpu' and args.system.endswith('_baseline')):
            parser.error('Select a diagnostic system for inference/smoke')
        infer(args.system, cpu=args.action == 'cpu')
    else:
        {'prepare': prepare, 'score': score}[args.action]()
