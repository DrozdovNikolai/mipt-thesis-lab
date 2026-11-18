"""Frozen four-design follow-up of pause handling on old and newly acquired data."""

import argparse
import importlib.metadata
import json
import platform
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.asr import AsrProvider
from north55_speech.audio import VadProvider, denoise
from north55_speech.core import atomic_json, file_hash, now
from north55_speech.metrics import corpus_counts, edit_counts, lexical_normalizer_v1, paired_cluster_bootstrap
from north55_speech.schemas import DenoiseConfig, PipelineConfig, VadConfig
from scripts.evaluate_expanded_sources import identity

ROOT = Path('/reports/additional-sources-v1/asr')
PREVIOUS = Path('/reports/all-sources-v1/evaluation')
TRIALS = ('baseline', 'vad_segments', 'vad_gate', 'vad_span', 'vad_gate_denoise')
VAD = {'enabled': True, 'threshold': .5, 'min_speech_duration_ms': 100, 'min_silence_duration_ms': 400, 'speech_pad_ms': 200, 'max_speech_duration_s': 30}


def read(path):
    return json.loads(path.read_bytes())


def script_identity():
    return {**identity(), 'additional_script_sha256': file_hash(Path(__file__))}


def inference_regions(length, speech_regions, trial):
    if trial == 'baseline':
        return [(0, length)] if length else []
    if not speech_regions:
        return []
    if trial == 'vad_segments':
        return speech_regions
    if trial in {'vad_gate', 'vad_gate_denoise'}:
        return [(0, length)]
    if trial == 'vad_span':
        # Preserve intervening pauses and continuous original context, add 400ms
        # around already padded Silero boundaries. Never concatenate distant cuts.
        return [(max(0, speech_regions[0][0] - 6400), min(length, speech_regions[-1][1] + 6400))]
    raise ValueError('Unknown frozen design')


def prepare():
    if (ROOT / 'plan.json').exists():
        raise ValueError('Existing comparison plan is immutable')
    previous, additional = read(PREVIOUS / 'plan.json'), read(Path('/additional-audio/plan.json'))
    references = {**read(PREVIOUS / 'references.json'), **read(Path('/additional-audio/references.json'))}
    if file_hash(PREVIOUS / 'references.json') != previous['references_sha256'] or file_hash(Path('/additional-audio/references.json')) != additional['references_sha256']:
        raise ValueError('Source references changed')
    config = previous['inference_config'] | {'model': previous['models']['parent']['name']}
    items = previous['items'] + additional['items']
    if len({i['id'] for i in items}) != len(items):
        raise ValueError('Duplicate comparison ID')
    reused = {}
    execution = read(PREVIOUS / 'execution.json')
    for item in previous['items']:
        path = PREVIOUS / 'predictions' / f'parent-{item["id"]}.json'
        r = read(path)
        sha = file_hash(path)
        if sha != execution['prediction_sha256'][path.name] or r['config'] != config or r['audio_sha256'] != item['audio_sha256']:
            raise ValueError('Parent cache differs from declared baseline')
        reused[item['id']] = {'path': str(path), 'sha256': sha, 'original_plan_sha256': r['plan_sha256']}
    ROOT.mkdir(parents=True, exist_ok=True)
    atomic_json(ROOT / 'references.json', references)
    atomic_json(ROOT / 'plan.json', {'created_at': now().isoformat(), **script_identity(), 'items': items,
        'config': config, 'trials': TRIALS, 'vad': VAD, 'span_extra_padding_samples': 6400,
        'denoise': DenoiseConfig(enabled=True, strength=.3).model_dump(), 'baseline_reused': reused,
        'references_sha256': file_hash(ROOT / 'references.json'), 'model': previous['models']['parent'],
        'previous_plan_sha256': file_hash(PREVIOUS / 'plan.json'), 'additional_audio_plan_sha256': file_hash(Path('/additional-audio/plan.json')),
        'test_accessed': False, 'release_promoted': False, 'quality_evidence': False,
        'search_budget': {'previous_pipeline_designs': 8, 'new_designs': 3, 'reused_vad_design': 1, 'checkpoint_adaptation_runs': 2, 'maximum_configurations': 16},
        'selection_policy': 'diagnostic comparisons only; no candidate/release choice from general controls',
        'limitations': previous['limitations'] + additional['limitations']})
    print(json.dumps({'status': 'FROZEN', 'inputs': len(items), 'trials': len(TRIALS), 'reused_baseline_predictions': len(reused)}))


def validate():
    plan = read(ROOT / 'plan.json')
    if any(plan[k] != v for k, v in script_identity().items()) or file_hash(ROOT / 'references.json') != plan['references_sha256']:
        raise ValueError('Frozen code/protocol/reference identity changed')
    return plan


def infer():
    plan = validate()
    plan_sha = file_hash(ROOT / 'plan.json')
    config = PipelineConfig.model_validate(plan['config'])
    provider = AsrProvider(config)
    if provider.model.model.compute_type != 'float16' or provider.model.model.device != 'cuda':
        raise ValueError('Different actual model device/precision')
    runtime = {'python': platform.python_version(), 'packages': {n: importlib.metadata.version(n) for n in ('faster-whisper', 'ctranslate2', 'numpy', 'soundfile')},
        'plan_sha256': plan_sha, 'actual_device': provider.model.model.device, 'actual_precision': provider.model.model.compute_type}
    if (ROOT / 'runtime.json').exists() and read(ROOT / 'runtime.json') != runtime:
        raise ValueError('Resume runtime differs')
    atomic_json(ROOT / 'runtime.json', runtime)
    vad = VadProvider()
    for index, item in enumerate(plan['items']):
        audio_path = Path('/audio') / item['audio_path']
        if file_hash(audio_path) != item['audio_sha256']:
            raise ValueError('Frozen source audio changed')
        audio, rate = sf.read(audio_path, dtype='float32')
        if rate != 16000 or audio.ndim != 1 or not np.isfinite(audio).all():
            raise ValueError('Invalid frozen mono16k audio')
        speech_regions = vad.intervals(audio, VadConfig.model_validate(plan['vad']))
        for trial in plan['trials']:
            path = ROOT / 'predictions' / f'{trial}-{item["id"]}.json'
            if path.exists():
                r = read(path)
                if r['plan_sha256'] != plan_sha or r['audio_sha256'] != item['audio_sha256']:
                    raise ValueError('Resume prediction differs')
                continue
            started = time.perf_counter()
            regions = inference_regions(len(audio), speech_regions, trial)
            record = {**item, 'trial': trial, 'plan_sha256': plan_sha, 'config': config.model_dump(),
                'effective_options': provider.options(item['input_language']), 'speech_regions_samples': speech_regions,
                'asr_regions_samples': regions, 'hypothesis': '', 'segments': [], 'runtime_failure': None, 'asr_calls': 0, 'reused': False}
            if trial == 'baseline' and item['id'] in plan['baseline_reused']:
                origin = plan['baseline_reused'][item['id']]
                if file_hash(Path(origin['path'])) != origin['sha256']:
                    raise ValueError('Saved baseline prediction changed')
                previous = read(Path(origin['path']))
                if previous['effective_options'] != record['effective_options']:
                    raise ValueError('Cached parent used different language/options')
                record.update({k: previous[k] for k in ('hypothesis', 'segments', 'runtime_failure')})
                record.update(reused=True, reused_from=origin, previous_elapsed_sec=previous['elapsed_sec'])
            else:
                try:
                    waveform = denoise(audio, DenoiseConfig.model_validate(plan['denoise'])) if trial == 'vad_gate_denoise' else audio
                    segments = []
                    for begin, end in regions:
                        record['asr_calls'] += 1
                        segments.extend(provider.transcribe(waveform[begin:end], begin, item['input_language'], f'{trial}-{begin}', lambda: None))
                    record.update(hypothesis=' '.join(s.raw_asr_text.strip() for s in segments), segments=[s.model_dump() for s in segments])
                except Exception as exc:
                    record.update(runtime_failure={'type': type(exc).__name__, 'message': str(exc)}, hypothesis='', segments=[])
            record['elapsed_sec'] = time.perf_counter() - started
            atomic_json(path, record)
        if index % 20 == 0 or index == len(plan['items']) - 1:
            print(json.dumps({'completed_inputs': index + 1, 'total_inputs': len(plan['items'])}), flush=True)
    atomic_json(ROOT / 'execution.json', {'plan_sha256': plan_sha, 'completed_at': now().isoformat(),
        'prediction_sha256': {p.name: file_hash(p) for p in sorted((ROOT / 'predictions').glob('*.json'))}})


def score():
    plan = validate()
    references, execution = read(ROOT / 'references.json'), read(ROOT / 'execution.json')
    if len(execution['prediction_sha256']) != len(plan['items']) * len(plan['trials']) or execution['plan_sha256'] != file_hash(ROOT / 'plan.json'):
        raise ValueError('Incomplete frozen population')
    rows, lookup = [], {}
    for item in plan['items']:
        for trial in plan['trials']:
            path = ROOT / 'predictions' / f'{trial}-{item["id"]}.json'
            if file_hash(path) != execution['prediction_sha256'][path.name]:
                raise ValueError('Prediction changed after execution')
            record = read(path)
            if record['plan_sha256'] != execution['plan_sha256'] or record['audio_sha256'] != item['audio_sha256']:
                raise ValueError('Prediction plan/input mismatch')
            reference = references[item['id']]
            row = {**record, 'reference': reference, 'score': edit_counts(reference, record['hypothesis']) if reference is not None else None}
            rows.append(row)
            lookup[trial, item['id']] = row
    cohorts = {}
    for cohort in sorted({i['cohort'] for i in plan['items']}):
        selected = [i for i in plan['items'] if i['cohort'] == cohort]
        summaries = {t: corpus_counts([lookup[t, i['id']]['score'] for i in selected if references[i['id']] is not None]) for t in plan['trials']}
        baseline = summaries['baseline']['wer_lexical_corpus']
        comparisons = {}
        for trial in plan['trials'][1:]:
            pairs = [{'group_id': i['group_id'], 'baseline': lookup['baseline', i['id']]['score'], 'candidate': lookup[trial, i['id']]['score']} for i in selected if references[i['id']] is not None]
            interval = paired_cluster_bootstrap(pairs, resamples=2000, seed=55, confidence=.95)
            value = summaries[trial]['wer_lexical_corpus']
            comparisons[trial] = {'relative_reduction': (baseline - value) / baseline if baseline else None,
                'wer_delta': value - baseline if baseline is not None else None, 'bootstrap': interval,
                'ci_interpretable_for_independent_sampling': interval['independent_groups'] > 1}
        cohorts[cohort] = {'inputs': len(selected), 'scored': sum(references[i['id']] is not None for i in selected), 'scores': summaries, 'comparisons': comparisons}
        if cohort in {'noise_only', 'bleriot_b_noise'}:
            minutes = sum(i['duration_sec'] for i in selected) / 60
            cohorts[cohort].update(channel_minutes=minutes, inserted_words_per_minute={t: sum(len(lexical_normalizer_v1(lookup[t, i['id']]['hypothesis']).split()) for i in selected) / minutes for t in plan['trials']})
    result = {'status': 'EXECUTED_DIAGNOSTIC', 'plan_sha256': file_hash(ROOT / 'plan.json'), 'cohorts': cohorts,
        'output_records': len(rows), 'reused_baseline_records': sum(r['reused'] for r in rows), 'new_asr_calls': sum(r['asr_calls'] for r in rows),
        'runtime_failures': sum(r['runtime_failure'] is not None for r in rows), 'gated_empty_outputs': sum(not r['reused'] and not r['asr_regions_samples'] for r in rows),
        'asr_quality_gate': 'NEEDS_MORE_DATA', 'critical_entity_gate': 'NEEDS_MORE_DATA', 'candidate_selected': False, 'release_promoted': False,
        'test_accessed': False, 'limitations': plan['limitations'], 'rows': rows}
    atomic_json(ROOT / 'comparison.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in {'rows', 'cohorts', 'limitations'}}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'infer', 'score'))
    args = parser.parse_args()
    {'prepare': prepare, 'infer': infer, 'score': score}[args.action]()
