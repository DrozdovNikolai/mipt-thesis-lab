"""Frozen exploratory checkpoint comparison on expanded BLeRIOT and VOICI.

Published scripts, partial reviews and noise assumptions have separate metrics.
Nothing in this driver can promote a release or manufacture human event labels.
"""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.asr import AsrProvider, local_model_manifest
from north55_speech.audio import VadProvider
from north55_speech.benchmark import code_hash, scorer_hash
from north55_speech.core import atomic_json, file_hash, now, read_yaml, settings
from north55_speech.datasets import load_manifest
from north55_speech.metrics import (
    corpus_counts,
    edit_counts,
    lexical_normalizer_v1,
    paired_cluster_bootstrap,
)
from north55_speech.reporting import write_csv
from north55_speech.schemas import PipelineConfig, VadConfig
from scripts.build_publisher_pairs import clip
from scripts.prepare_voici_diagnostics import mix_at_snr

MODELS = {'parent': 'whisper-small-publisher-base-ct2', 'expanded': 'whisper-small-publisher-expanded-v1-ct2'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def identity():
    return {'script_sha256': file_hash(Path(__file__)), 'scorer_sha256': scorer_hash(), 'code_sha256': code_hash(),
            'mixture_script_sha256': file_hash(Path(__file__).with_name('prepare_voici_diagnostics.py')),
            'clip_script_sha256': file_hash(Path(__file__).with_name('build_publisher_pairs.py')),
            'acceptance_sha256': file_hash(Path('/app/ACCEPTANCE.yaml')), 'uv_lock_sha256': file_hash(Path('/app/uv.lock')),
            'baseline_config_sha256': file_hash(Path('/app/configs/baseline.yaml'))}


def prepare(args):
    if (args.output / 'plan.json').exists():
        raise ValueError('Evaluation is already frozen; do not overwrite it')
    config = PipelineConfig.model_validate(read_yaml(Path('/app/configs/baseline.yaml')))
    config.device, config.compute_type = 'cuda', 'float16'
    expanded = load_manifest(Path('/expanded/all/dev.jsonl'))
    if any(s.split != 'dev' for s in expanded):
        raise ValueError('Expanded comparison is dev-only')
    noise_plan = read(Path('/voici-diagnostic/plan.json'))
    if noise_plan['source_partition'] != 'dev_only_no_training_or_test_use':
        raise ValueError('Entire noise original must be assigned to dev only')
    models = {system: {'name': name, 'manifest': local_model_manifest(name),
                      'manifest_sha256': file_hash(settings.model_root / name / 'manifest.json')} for system, name in MODELS.items()}
    training = read(settings.model_root / 'whisper-small-publisher-expanded-v1/manifest.json')
    if training['reference_policy'] != 'publisher_weak_exploratory_v1' or training['converted_model'] != models['expanded']['manifest']:
        raise ValueError('Expected the completed expanded-data adaptation')
    for split in ('train', 'dev'):
        if file_hash(Path('/expanded/training') / f'{split}.jsonl') != training[f'{split}_sha256']:
            raise ValueError('Training references changed after adaptation')
    if models['parent']['manifest']['source_manifest_sha256'] != file_hash(settings.model_root / 'whisper-small-transformers/manifest.json'):
        raise ValueError('Parent checkpoint is from a different Transformers source')
    if training['base_manifest'] != read(settings.model_root / 'whisper-small-transformers/manifest.json'):
        raise ValueError('Adaptation has a different parent')
    items, references = [], {}
    for s in expanded:
        item = {'id': 'bleriot-' + s.sample_id, 'audio_path': s.audio_path, 'audio_sha256': s.audio_sha256,
                'group_id': s.group_id, 'duration_sec': s.duration_sec, 'input_language': 'auto',
                'source_id': s.annotation_provenance['source_sample_id'], 'original_id': s.original_utterance_id,
                'original_start_sec': s.annotation_provenance['original_start_sec'], 'condition': s.acoustic_condition,
                'cohort': 'publisher_weak_dev', 'reference_kind': 'automatic_publisher_alignment',
                'reference_eligible': s.annotation_provenance['automatic_training_eligible'], 'primary': False}
        items.append(item)
        references[item['id']] = s.reference_text if item['reference_eligible'] else None
    for n in noise_plan['items']:
        items.append({**n, 'cohort': 'noise_only', 'reference_eligible': True})
        references[n['id']] = ''  # Publisher's speech-removal claim, not an invented human annotation.
    # Existing controls are a regression diagnostic; no model is selected using them.
    clean_plan = read(Path('/clean-controls/plan.json'))
    clean_refs = read(Path('/clean-controls/references.json'))
    for item in clean_plan['items']:
        items.append({**item, 'cohort': 'general_clean', 'condition': 'general_clean',
                      'reference_kind': 'publisher_LibriSpeech', 'reference_eligible': True})
        references[item['id']] = clean_refs[item['id']]
    reviewed_path = Path('/reviewed/dev.jsonl')
    for s in load_manifest(reviewed_path):
        if s.split != 'dev' or s.transcript_status != 'human_verified':
            raise ValueError('Reviewed subset must contain only actual saved dev reviews')
        path = settings.audio_root / 'expanded-evaluation-v1' / f'reviewed-{s.sample_id}.wav'
        clip(s, 0, s.duration_sec, path)
        item = {'id': 'reviewed-' + s.sample_id, 'audio_path': str(path.relative_to(settings.audio_root)),
                'audio_sha256': file_hash(path), 'duration_sec': s.duration_sec, 'group_id': s.group_id,
                'input_language': 'auto', 'cohort': 'partial_human_dev', 'condition': s.acoustic_condition,
                'reference_kind': 'saved_partial_human_review_with_suggestion_exposure', 'reference_eligible': True, 'primary': False}
        items.append(item)
        references[item['id']] = s.reference_text
    # Full VOICI recording belongs only to dev; never split it between train/dev.
    noise_parts = []
    for n in noise_plan['items']:
        p = settings.audio_root / n['audio_path']
        if file_hash(p) != n['audio_sha256']:
            raise ValueError('Prepared noise changed')
        waveform, rate = sf.read(p, dtype='float32')
        if rate != 16000:
            raise ValueError('Unexpected prepared noise rate')
        noise_parts.append(waveform)
    noise = np.concatenate(noise_parts)
    skipped_mixtures = []
    for s in expanded:
        if s.variant_of:
            continue  # Real supplied A/C pair retained; do not add noise on top of C.
        path = settings.audio_root / s.audio_path
        if file_hash(path) != s.audio_sha256:
            raise ValueError('Expanded dev audio changed')
        speech, rate = sf.read(path, dtype='float32')
        if rate != 16000 or speech.ndim != 1:
            raise ValueError('Expected prepared mono audio')
        active = np.zeros(len(speech), dtype=bool)
        intervals = VadProvider().intervals(speech, VadConfig(enabled=True))
        for start, end in intervals:
            active[start:end] = True
        if not active.any():
            skipped_mixtures.append({'source': s.sample_id, 'reason': 'no_active_speech_RMS_under_frozen_VAD', 'original_retained': True})
            continue
        offset = int(hashlib.sha256(f'55:{s.sample_id}'.encode()).hexdigest()[:16], 16) % (len(noise) - len(speech) + 1)
        aligned_noise = noise[offset:offset + len(speech)]
        for snr in (0., 10.):
            waveform, mixing = mix_at_snr(speech, aligned_noise, active, snr)
            sample_id = f'mix-{s.sample_id}-{int(snr)}dB'
            path = settings.audio_root / 'expanded-evaluation-v1' / f'{sample_id}.wav'
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                old, old_rate = sf.read(path, dtype='float32')
                if old_rate != 16000 or not np.array_equal(old, waveform):
                    raise ValueError('Existing mixture differs')
            else:
                sf.write(path, waveform, 16000, subtype='FLOAT')
            items.append({'id': sample_id, 'audio_path': str(path.relative_to(settings.audio_root)),
                          'audio_sha256': file_hash(path), 'duration_sec': s.duration_sec, 'input_language': 'auto',
                          'cohort': f'voici_mix_{int(snr)}dB', 'condition': f'voici_mix_{int(snr)}dB',
                          'group_id': 'voici-original-2660112', 'speech_group_id': s.group_id, 'original_id': s.original_utterance_id,
                          'source_id': s.sample_id, 'original_start_sec': s.annotation_provenance['original_start_sec'],
                          'reference_kind': 'clean_weak_target_inherited_not_verified_after_noise',
                          'reference_eligible': s.annotation_provenance['automatic_training_eligible'], 'primary': False,
                          'mixing': {**mixing, 'noise_offset_samples_16k': offset, 'noise_source_sha256': noise_plan['source_sha256'],
                                     'vad_intervals_samples': intervals, 'source_split': 'dev', 'noise_split': 'dev'},
                          'component_licenses': [s.license_id, 'CC-BY-SA-4.0'], 'redistribution_admitted': False})
            references[sample_id] = s.reference_text if s.annotation_provenance['automatic_training_eligible'] else None
    args.output.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output / 'references.json', references)
    plan = {'created_at': now().isoformat(), **identity(), 'models': models, 'inference_config': config.model_dump(), 'items': items,
            'references_sha256': file_hash(args.output / 'references.json'), 'skipped_mixtures': skipped_mixtures,
            'source_hashes': {'expanded': file_hash(Path('/expanded/all/dev.jsonl')), 'reviewed': file_hash(reviewed_path),
                              'noise_plan': file_hash(Path('/voici-diagnostic/plan.json')), 'clean_plan': file_hash(Path('/clean-controls/plan.json'))},
            'training_manifest_sha256': file_hash(settings.model_root / 'whisper-small-publisher-expanded-v1/manifest.json'),
            'selection_allowed': False, 'release_promoted': False, 'test_accessed': False, 'quality_evidence': False,
            'limitations': ['Automatic publisher targets are not independent lexical WER gold.',
                            'Human dev subset is small, previously inspected and includes unresolved digit spelling.',
                            'Whole VOICI original is dev-only; mixtures share ONE noise group, not independent flights.',
                            'Noise has publisher speech-removal provenance, no independent human verification.',
                            'General clean controls were already observed; regression only, no tuning or selection.',
                            'No human event/salience/entity or continuous temporal labels are created.']}
    atomic_json(args.output / 'plan.json', plan)
    print(json.dumps({'status': 'FROZEN', 'items': len(items), 'mixtures_skipped': len(skipped_mixtures),
                      'cohorts': {c: sum(i['cohort'] == c for i in items) for c in sorted({i['cohort'] for i in items})}}, indent=2))


def validate(args):
    plan = read(args.output / 'plan.json')
    if any(plan[k] != value for k, value in identity().items()):
        raise ValueError('Evaluation code or protocol changed after freeze')
    if file_hash(args.output / 'references.json') != plan['references_sha256']:
        raise ValueError('Frozen references changed')
    for model in plan['models'].values():
        if file_hash(settings.model_root / model['name'] / 'manifest.json') != model['manifest_sha256']:
            raise ValueError('Frozen model manifest changed')
    for item in plan['items']:
        path = (settings.audio_root / item['audio_path']).resolve()
        if not path.is_relative_to(settings.audio_root.resolve()) or file_hash(path) != item['audio_sha256']:
            raise ValueError('Frozen input audio changed')
    return plan


def infer(args):
    plan = validate(args)
    plan_hash = file_hash(args.output / 'plan.json')
    runtime = {'plan_sha256': plan_hash, 'python': platform.python_version(), 'platform': platform.platform(),
               'packages': {n: importlib.metadata.version(n) for n in ('faster-whisper', 'ctranslate2', 'numpy', 'soundfile', 'jiwer')},
               'gpu': subprocess.check_output(['nvidia-smi', '--query-gpu=index,name,driver_version', '--format=csv,noheader'], text=True)}
    runtime_path = args.output / 'runtime.json'
    if runtime_path.exists() and read(runtime_path) != runtime:
        raise ValueError('Resume requires the original runtime identity')
    atomic_json(runtime_path, runtime)
    for system, model in plan['models'].items():
        config = PipelineConfig.model_validate(plan['inference_config']).model_copy(update={'model': model['name']})
        provider, failure = None, None
        try:
            provider = AsrProvider(config)
            if provider.model.model.compute_type != 'float16' or provider.model.model.device != 'cuda':
                raise ValueError('Actual model precision/device differs')
        except Exception as exc:
            provider = None
            failure = {'type': type(exc).__name__, 'message': str(exc)}
        for index, item in enumerate(plan['items']):
            path = args.output / 'predictions' / f'{system}-{item["id"]}.json'
            if path.exists():
                record = read(path)
                if record['plan_sha256'] != plan_hash or record['model'] != model['name'] or record['audio_sha256'] != item['audio_sha256']:
                    raise ValueError('Prediction cache belongs to another input or model')
                continue
            started = time.perf_counter()
            record = {**item, 'system': system, 'model': model['name'], 'plan_sha256': plan_hash,
                      'hypothesis': '', 'segments': [], 'runtime_failure': failure, 'config': config.model_dump()}
            if provider:
                try:
                    audio, rate = sf.read(settings.audio_root / item['audio_path'], dtype='float32')
                    if rate != 16000 or audio.ndim != 1:
                        raise ValueError('Expected frozen mono16k input')
                    record['effective_options'] = provider.options(item['input_language'])
                    segments = provider.transcribe(audio, 0, item['input_language'], 'expanded', lambda: None)
                    record.update(hypothesis=' '.join(s.raw_asr_text.strip() for s in segments), segments=[s.model_dump() for s in segments])
                except Exception as exc:
                    record['runtime_failure'] = {'type': type(exc).__name__, 'message': str(exc)}
            record['elapsed_sec'] = time.perf_counter() - started
            atomic_json(path, record)
            if index % 20 == 0 or index == len(plan['items']) - 1:
                print(json.dumps({'system': system, 'completed': index + 1, 'total': len(plan['items']), 'failure': record['runtime_failure']}), flush=True)
    atomic_json(args.output / 'execution.json', {'plan_sha256': plan_hash,
                'prediction_sha256': {p.name: file_hash(p) for p in sorted((args.output / 'predictions').glob('*.json'))}})


def score(args):
    plan = validate(args)
    plan_hash = file_hash(args.output / 'plan.json')
    references, execution = read(args.output / 'references.json'), read(args.output / 'execution.json')
    if execution['plan_sha256'] != plan_hash or len(execution['prediction_sha256']) != 2 * len(plan['items']):
        raise ValueError('Every frozen run must be retained before scoring')
    rows, paired = [], {}
    for item in plan['items']:
        pair = {'group_id': item['group_id']}
        options = []
        for system, model in plan['models'].items():
            path = args.output / 'predictions' / f'{system}-{item["id"]}.json'
            if file_hash(path) != execution['prediction_sha256'][path.name]:
                raise ValueError('Prediction changed after execution')
            record = read(path)
            if any(record[k] != v for k, v in item.items()) or record['plan_sha256'] != plan_hash or record['model'] != model['name']:
                raise ValueError('Prediction input identity differs')
            if record['runtime_failure'] and record['hypothesis']:
                raise ValueError('Failed recognition must count as empty hypothesis')
            if not record['runtime_failure']:
                options.append(record['effective_options'])
            reference = references[item['id']]
            counts = edit_counts(reference, record['hypothesis']) if reference is not None else None
            rows.append({**record, 'reference': reference, 'score': counts})
            pair['baseline' if system == 'parent' else 'candidate'] = counts
        if len(options) == 2 and options[0] != options[1]:
            raise ValueError('Models used different effective ASR options')
        if pair['baseline'] is not None:
            paired.setdefault(item['cohort'], []).append(pair)
    cohorts = {}
    for cohort in sorted({i['cohort'] for i in plan['items']}):
        subset = [r for r in rows if r['cohort'] == cohort]
        summaries = {system: corpus_counts([r['score'] for r in subset if r['system'] == system and r['score'] is not None]) for system in MODELS}
        parent, candidate = [summaries[s]['wer_lexical_corpus'] for s in MODELS]
        interval = paired_cluster_bootstrap(paired.get(cohort, []), resamples=2000, seed=55, confidence=.95)
        cohorts[cohort] = {'samples': len(subset) // 2, 'scored': sum(r['score'] is not None for r in subset) // 2,
                           'scores': summaries, 'bootstrap': interval,
                           'relative_reduction': (parent - candidate) / parent if parent else None,
                           'wer_delta': candidate - parent if parent is not None else None,
                           'runtime_failures': sum(r['runtime_failure'] is not None for r in subset)}
        if cohort == 'noise_only':
            minutes = sum(i['duration_sec'] for i in plan['items'] if i['cohort'] == cohort) / 60
            cohorts[cohort]['duration_minutes'] = minutes
            cohorts[cohort]['inserted_words_per_minute'] = {s: sum(len(lexical_normalizer_v1(r['hypothesis']).split()) for r in subset if r['system'] == s) / minutes for s in MODELS}
    acceptance = read_yaml(Path('/app/ACCEPTANCE.yaml'))['asr_quality_gate']['guardrails']
    clean_delta = cohorts['general_clean']['wer_delta']
    noise_rates = cohorts['noise_only']['inserted_words_per_minute']
    guardrails = {'clean': 'PASS' if clean_delta <= acceptance['maximum_clean_wer_absolute_increase'] else 'FAIL',
                  'noise_under_publisher_assumption': 'PASS' if noise_rates['expanded'] - noise_rates['parent'] <= acceptance['maximum_non_speech_inserted_words_per_minute_delta'] else 'FAIL'}
    result = {'status': 'EXECUTED_EXPLORATORY', 'plan_sha256': plan_hash, 'cohorts': cohorts, 'diagnostic_guardrails': guardrails,
              'runs': len(rows), 'runtime_failures': sum(r['runtime_failure'] is not None for r in rows),
              'asr_quality_gate': 'NEEDS_MORE_DATA', 'nlp_quality_gate': 'NEEDS_MORE_DATA', 'temporal_gate': 'NEEDS_MORE_DATA',
              'candidate_selected': False, 'release_promoted': False, 'test_accessed': False,
              'limitations': plan['limitations'], 'rows': rows}
    atomic_json(args.output / 'comparison.json', result)
    write_csv(args.output / 'predictions.csv', ['id', 'cohort', 'system', 'S', 'D', 'I', 'N', 'wer', 'reference', 'hypothesis', 'runtime_failure', 'elapsed_sec'],
              [{**r, **(r['score'] or {})} for r in rows])
    print(json.dumps({k: v for k, v in result.items() if k not in {'rows', 'limitations'}}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'infer', 'score'))
    parser.add_argument('--output', type=Path, default=Path('/reports/all-sources-v1/evaluation'))
    args = parser.parse_args()
    {'prepare': prepare, 'infer': infer, 'score': score}[args.action](args)


if __name__ == '__main__':
    main()
