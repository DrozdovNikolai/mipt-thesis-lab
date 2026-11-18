"""Two fixed dev diagnostics: reviewed input language, then small vs large-v3.

Inference mounts only inputs and fresh outputs, not references or prior answers.
Both models run without network and are timed afresh on the same 661 waveforms.
"""

import argparse
import importlib.metadata
import json
import platform
import resource
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.asr import AsrProvider, local_model_manifest
from north55_speech.benchmark import code_hash, scorer_hash
from north55_speech.core import atomic_json, file_hash, now
from north55_speech.metrics import (
    corpus_counts,
    edit_counts,
    lexical_normalizer_v1,
    paired_cluster_bootstrap,
)
from north55_speech.schemas import PipelineConfig

ROOT = Path('/reports/language-large-v1')
PREVIOUS = Path('/reports/additional-sources-v1/asr')
SCORING = Path('/scoring')
MODELS = {'small_known': 'whisper-small-publisher-base-ct2', 'large_known': 'whisper-large-v3-systran-ct2'}


def read(path):
    return json.loads(path.read_bytes())


def identity():
    return {'script_sha256': file_hash(Path(__file__)), 'code_sha256': code_hash(),
        'scorer_sha256': scorer_hash(), 'acceptance_sha256': file_hash(Path('/app/ACCEPTANCE.yaml')),
        'baseline_sha256': file_hash(Path('/app/configs/baseline.yaml')), 'uv_lock_sha256': file_hash(Path('/app/uv.lock'))}


def declared_language(item, reviews):
    """Only previously verified EN metadata can change an existing input mode."""
    r = reviews.get(item['id'])
    if (r and r.get('split') == 'dev' and r.get('scope_verified') is True
            and r.get('scope') in {'read_cockpit', 'cockpit', 'simulator'}
            and r.get('language') == 'en' and r.get('transcript_status') == 'human_verified'
            and r.get('annotation_provenance', {}).get('reviewed_audio') is True):
        return 'en'
    return item['input_language']


def prepare():
    if (ROOT / 'plan.json').exists():
        raise ValueError('Frozen study already exists')
    old = read(PREVIOUS / 'plan.json')
    refs = read(PREVIOUS / 'references.json')
    if file_hash(PREVIOUS / 'references.json') != old['references_sha256']:
        raise ValueError('Prior references changed')
    review_path = Path('/reviewed/dev.jsonl')
    reviews = {'reviewed-' + r['sample_id']: r for r in [json.loads(line) for line in review_path.read_text().splitlines()]}
    items, evidence = [], []
    for item in old['items']:
        language = declared_language(item, reviews)
        items.append({**item, 'previous_input_language': item['input_language'], 'input_language': language})
        if language != item['input_language']:
            r = reviews[item['id']]
            evidence.append({'id': item['id'], 'from': item['input_language'], 'to': language,
                'basis': 'existing human review language + scope/listening verification',
                'reviewed_manifest_sha256': file_hash(review_path), 'reviewed_at': r['annotation_provenance']['reviewed_at']})
    if len(items) != 661 or len(evidence) != 5 or any(r['cohort'] != 'partial_human_dev' for r in items if r['input_language'] != r['previous_input_language']):
        raise ValueError('Predeclared language population differs; inspect without silently broadening')
    configs = {s: PipelineConfig.model_validate(old['config'] | {'model': m}).model_dump() for s, m in MODELS.items()}
    for c in configs.values():
        if c['device'] != 'cuda' or c['compute_type'] != 'float16' or c['vad']['enabled'] or c['denoise']['enabled'] or c['hotwords'] or c['redecode']:
            raise ValueError('Unexpected baseline stages or device')
    models = {s: {'name': n, 'manifest': local_model_manifest(n),
        'manifest_sha256': file_hash(Path('/models') / n / 'manifest.json')} for s, n in MODELS.items()}
    prior_execution = read(PREVIOUS / 'execution.json')
    prior = {i['id']: {'path': str(PREVIOUS / 'predictions' / f'baseline-{i["id"]}.json'),
        'sha256': prior_execution['prediction_sha256'][f'baseline-{i["id"]}.json']} for i in items}
    if any(file_hash(Path(r['path'])) != r['sha256'] for r in prior.values()):
        raise ValueError('Previous answers changed')
    atomic_json(SCORING / 'references.json', refs)
    atomic_json(ROOT / 'inputs.json', items)
    atomic_json(ROOT / 'plan.json', {'frozen_at': now().isoformat(), **identity(),
        'inputs_sha256': file_hash(ROOT / 'inputs.json'), 'references_sha256': file_hash(SCORING / 'references.json'),
        'configs': configs, 'models': models, 'previous_plan_sha256': file_hash(PREVIOUS / 'plan.json'),
        'previous_baseline': prior, 'language_evidence': evidence, 'systems': list(MODELS),
        'protocol_sha256': file_hash(ROOT / 'protocol.md'),
        'reviewed_manifest_sha256': file_hash(review_path), 'input_count': len(items),
        'search_budget': {'previous_configurations_conservative': 14, 'new_configurations': 2, 'total': 16, 'limit': 16},
        'selection_policy': 'two diagnostic checks only; no further configuration search or release choice',
        'test_accessed': False, 'release_promoted': False,
        'limitations': old['limitations'] + [
            'Language-effect comparison deliberately changes input information and is not same-information pipeline evidence.',
            'Small versus large changes checkpoint; it cannot establish same-checkpoint pipeline improvement.',
            'English is a saved human declaration; French and mixed language are never inferred from a desired transcript.',
            'Memory sampling is device-wide on a shared GPU, not exact per-process GPU allocation or guaranteed peak.',
            'All data are already exposed dev/diagnostic cohorts, not independent final test.']})
    print(json.dumps({'status': 'FROZEN', 'inputs': len(items), 'changed_language_inputs': len(evidence), 'new_configurations': 2}))


def validate():
    plan = read(ROOT / 'plan.json')
    if any(plan[k] != v for k, v in identity().items()) or file_hash(ROOT / 'inputs.json') != plan['inputs_sha256'] or file_hash(ROOT / 'protocol.md') != plan['protocol_sha256']:
        raise ValueError('Frozen code/config/input/protocol identity changed')
    return plan


class MemorySampler:
    def __init__(self):
        self.samples, self.errors = [], []
        self.stop = threading.Event()
        self.started = time.perf_counter()
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def sample(self):
        try:
            result = subprocess.run(['nvidia-smi', '-i', '0', '--query-gpu=index,uuid,name,memory.total,memory.used', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=3, check=True)
            index, uuid, name, total, used = [x.strip() for x in result.stdout.strip().split(',')]
            status = Path('/proc/self/status').read_text()
            rss = int(next(line for line in status.splitlines() if line.startswith('VmRSS:')).split()[1])
            self.samples.append({'elapsed_sec': time.perf_counter() - self.started, 'gpu_index': int(index),
                'gpu_uuid': uuid, 'gpu_name': name, 'device_total_mib': int(total), 'device_used_mib': int(used), 'process_rss_kib': rss})
        except Exception as exc:
            self.errors.append({'type': type(exc).__name__, 'message': str(exc)})

    def loop(self):
        while not self.stop.wait(.5):
            self.sample()

    def begin(self):
        self.sample()
        self.thread.start()

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=4)
        self.sample()
        return {'sampling_target_seconds': .5, 'samples': self.samples, 'errors': self.errors,
            'sampled_device_peak_mib': max((s['device_used_mib'] for s in self.samples), default=None),
            'device_before_model_mib': self.samples[0]['device_used_mib'] if self.samples else None,
            'process_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'limitation': 'Device-wide sampled memory includes other apps; transient peaks between samples can be missed.'}


def infer(system):
    plan = validate()
    config = PipelineConfig.model_validate(plan['configs'][system])
    inputs = read(ROOT / 'inputs.json')
    output = ROOT / system
    output.mkdir(exist_ok=True)
    sampler = MemorySampler()
    started = time.perf_counter()
    sampler.begin()
    attempt = now().strftime('%Y%m%dT%H%M%S%fZ')
    runtime = {'system': system, 'attempt': attempt, 'started_at': now().isoformat(),
        'plan_sha256': file_hash(ROOT / 'plan.json'), 'python': platform.python_version(),
        'packages': {p: importlib.metadata.version(p) for p in ('faster-whisper', 'ctranslate2', 'numpy', 'soundfile')},
        'new_records': 0, 'resumed_records': 0, 'status': 'RUNNING'}
    try:
        provider = AsrProvider(config)
        runtime.update(initialization_sec=provider.initialization_sec, actual_device=provider.model.model.device,
            actual_precision=provider.model.model.compute_type)
        if runtime['actual_device'] != 'cuda' or runtime['actual_precision'] != 'float16':
            raise ValueError('Actual inference precision/device differs')
        for index, item in enumerate(inputs):
            path = output / 'predictions' / f'{item["id"]}.json'
            if path.exists():
                saved = read(path)
                if saved['plan_sha256'] != runtime['plan_sha256'] or saved['audio_sha256'] != item['audio_sha256'] or saved['effective_options'] != provider.options(item['input_language']):
                    raise ValueError('Resume output differs from frozen request')
                runtime['resumed_records'] += 1
                continue
            begin = time.perf_counter()
            audio_path = Path('/audio') / item['audio_path']
            if file_hash(audio_path) != item['audio_sha256']:
                raise ValueError('Frozen audio changed')
            waveform, rate = sf.read(audio_path, dtype='float32')
            if rate != 16000 or waveform.ndim != 1 or not np.isfinite(waveform).all():
                raise ValueError('Invalid mono 16 kHz input')
            record = {**item, 'system': system, 'attempt': attempt, 'plan_sha256': runtime['plan_sha256'],
                'config': config.model_dump(), 'effective_options': provider.options(item['input_language']),
                'hypothesis': '', 'segments': [], 'runtime_failure': None}
            asr_started = time.perf_counter()
            try:
                segments = provider.transcribe(waveform, 0, item['input_language'], item['id'], lambda: None)
                record.update(hypothesis=' '.join(s.raw_asr_text.strip() for s in segments), segments=[s.model_dump() for s in segments])
            except Exception as exc:
                record['runtime_failure'] = {'type': type(exc).__name__, 'message': str(exc)}
            record.update(asr_elapsed_sec=time.perf_counter() - asr_started, driver_elapsed_sec=time.perf_counter() - begin)
            atomic_json(path, record)
            runtime['new_records'] += 1
            if index % 25 == 0 or index == len(inputs) - 1:
                print(json.dumps({'system': system, 'completed': index + 1, 'total': len(inputs)}), flush=True)
        runtime['status'] = 'COMPLETED'
    except Exception as exc:
        runtime.update(status='FAILED', infrastructure_error={'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        runtime.update(completed_at=now().isoformat(), wall_sec=time.perf_counter() - started, memory=sampler.finish())
        atomic_json(output / f'runtime-{attempt}.json', runtime)
    atomic_json(output / 'execution.json', {'plan_sha256': runtime['plan_sha256'], 'completed_at': now().isoformat(),
        'prediction_sha256': {p.name: file_hash(p) for p in sorted((output / 'predictions').glob('*.json'))},
        'runtime_sha256': {p.name: file_hash(p) for p in sorted(output.glob('runtime-*.json'))}})


def score():
    plan = validate()
    if file_hash(SCORING / 'references.json') != plan['references_sha256']:
        raise ValueError('Frozen references changed')
    refs, items = read(SCORING / 'references.json'), read(ROOT / 'inputs.json')
    rows, lookup = [], {}
    for system in ['small_previous', *plan['systems']]:
        execution = read(ROOT / system / 'execution.json') if system != 'small_previous' else None
        if execution and (len(execution['prediction_sha256']) != len(items) or execution['plan_sha256'] != file_hash(ROOT / 'plan.json')):
            raise ValueError('Incomplete frozen inference population')
        for item in items:
            prior = plan['previous_baseline'][item['id']]
            path = Path(prior['path']) if system == 'small_previous' else ROOT / system / 'predictions' / f'{item["id"]}.json'
            expected = prior['sha256'] if system == 'small_previous' else execution['prediction_sha256'][path.name]
            if file_hash(path) != expected:
                raise ValueError('Prediction changed after execution')
            record = read(path)
            row = {**record, 'system': system, 'reference': refs[item['id']],
                'score': edit_counts(refs[item['id']], record['hypothesis']) if refs[item['id']] is not None else None}
            rows.append(row)
            lookup[system, item['id']] = row
    systems = ['small_previous', *plan['systems']]
    cohorts = {}
    for cohort in sorted({i['cohort'] for i in items}):
        selected = [i for i in items if i['cohort'] == cohort]
        summaries = {s: corpus_counts([lookup[s, i['id']]['score'] for i in selected if refs[i['id']] is not None]) for s in systems}
        comparisons = {}
        for name, baseline, candidate in [('language_effect', 'small_previous', 'small_known'), ('model_effect', 'small_known', 'large_known')]:
            pairs = [{'group_id': i['group_id'], 'baseline': lookup[baseline, i['id']]['score'], 'candidate': lookup[candidate, i['id']]['score']} for i in selected if refs[i['id']] is not None]
            a, b = summaries[baseline]['wer_lexical_corpus'], summaries[candidate]['wer_lexical_corpus']
            ci = paired_cluster_bootstrap(pairs, resamples=2000, seed=55, confidence=.95)
            comparisons[name] = {'baseline': baseline, 'candidate': candidate, 'relative_reduction': (a - b) / a if a else None,
                'wer_delta': b - a if a is not None else None, 'bootstrap': ci, 'ci_interpretable_for_independent_sampling': ci['independent_groups'] > 1}
        value = {'inputs': len(selected), 'references': sum(refs[i['id']] is not None for i in selected), 'scores': summaries, 'comparisons': comparisons}
        if cohort in {'noise_only', 'bleriot_b_noise'}:
            minutes = sum(i['duration_sec'] for i in selected) / 60
            value.update(channel_minutes=minutes, inserted_words_per_minute={s: sum(len(lexical_normalizer_v1(lookup[s, i['id']]['hypothesis']).split()) for i in selected) / minutes for s in systems})
        cohorts[cohort] = value
    timing = {}
    for system in plan['systems']:
        selected = [r for r in rows if r['system'] == system]
        durations = sum(r['duration_sec'] for r in selected)
        timing[system] = {'audio_seconds': durations, 'asr_seconds': sum(r['asr_elapsed_sec'] for r in selected),
            'driver_seconds': sum(r['driver_elapsed_sec'] for r in selected),
            'asr_rtf': sum(r['asr_elapsed_sec'] for r in selected) / durations,
            'driver_rtf': sum(r['driver_elapsed_sec'] for r in selected) / durations,
            'scope': 'fresh sequential GPU calls; excludes model initialization, queue and UI; driver adds audio/hash preparation'}
    unchanged = [i for i in items if i['input_language'] == i['previous_input_language']]
    replay_same = sum(lookup['small_previous', i['id']]['hypothesis'] == lookup['small_known', i['id']]['hypothesis'] for i in unchanged)
    result = {'status': 'EXECUTED_DIAGNOSTIC', 'cohorts': cohorts, 'timing': timing, 'rows': rows,
        'plan_sha256': file_hash(ROOT / 'plan.json'), 'records': len(rows), 'new_inferences': len(items) * 2,
        'previous_records': len(items), 'unchanged_language_inputs': len(unchanged), 'unchanged_language_exact_replays': replay_same,
        'runtime_failures': {s: sum(r['runtime_failure'] is not None for r in rows if r['system'] == s) for s in systems},
        'asr_quality_gate': 'NEEDS_MORE_DATA', 'critical_entity_gate': 'NEEDS_MORE_DATA',
        'same_checkpoint_pipeline_gain_claimed': False, 'test_accessed': False, 'release_promoted': False,
        'limitations': plan['limitations']}
    atomic_json(ROOT / 'comparison.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in {'cohorts', 'rows', 'limitations'}}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'infer', 'score'))
    parser.add_argument('--system', choices=tuple(MODELS))
    args = parser.parse_args()
    if args.action == 'infer':
        if not args.system:
            parser.error('--system required for infer')
        infer(args.system)
    else:
        {'prepare': prepare, 'score': score}[args.action]()
