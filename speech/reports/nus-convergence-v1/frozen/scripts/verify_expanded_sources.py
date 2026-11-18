"""Verify executed artifacts and integrity without promoting scientific evidence."""

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.core import atomic_json, file_hash, now, settings
from north55_speech.datasets import load_manifest, validate_groups
from north55_speech.lora import validate_references
from north55_speech.metrics import lexical_normalizer_v1
from scripts.verify_clean_controls import independent_distance


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    root = Path('/reports/all-sources-v1')
    output = root / 'evaluation'
    result, plan = read(output / 'comparison.json'), read(output / 'plan.json')
    preparation = read(Path('/expanded/preparation-report.json'))
    prep_plan = read(Path('/expanded/plan.json'))
    training = read(settings.model_root / 'whisper-small-publisher-expanded-v1/manifest.json')
    history = read(settings.model_root / 'whisper-small-publisher-expanded-v1/training-history.json')
    checks = {}

    def check(name, value):
        checks[name] = bool(value)

    check('preparation_code_frozen', all(file_hash(Path('/app/scripts') / n) == sha for n, sha in prep_plan['code'].items()))
    check('evaluation_code_frozen', file_hash(Path('/app/scripts/evaluate_expanded_sources.py')) == plan['script_sha256'])
    check('immutable_plan_links', file_hash(Path('/expanded/plan.json')) == preparation['plan_sha256']
          and file_hash(output / 'plan.json') == result['plan_sha256'])
    all_rows = [s for split in ('train', 'dev') for s in load_manifest(Path('/expanded/all') / f'{split}.jsonl')]
    check('expanded_group_graph', validate_groups(all_rows) == preparation['groups'])
    train, dev = [load_manifest(Path('/expanded/training') / f'{split}.jsonl') for split in ('train', 'dev')]
    check('train_dev_admission_and_disjointness', validate_references(train, dev, training['config']) == 'publisher_weak_exploratory_v1')
    check('all_window_and_accepted_counts', len(all_rows) == 476 and (len(train), len(dev)) == (33, 35)
          and len({s.annotation_provenance['source_sample_id'] for s in all_rows}) == 15)
    check('no_human_or_event_labels_invented', all(s.transcript_status in {'weak', 'missing'} and not s.scope_verified
          and not s.primary and s.labels is None and s.events is None and s.critical_entities is None for s in all_rows))
    check('training_manifest_data_frozen', all(file_hash(Path('/expanded/training') / f'{s}.jsonl') == training[f'{s}_sha256'] for s in ('train', 'dev')))
    check('actual_training_finished_40_steps', max(r['step'] for r in history) == 40 and training['config']['max_steps'] == 40
          and training['train_metrics']['train_runtime'] > 0 and training['converted_inference'] == 'executed')
    check('all_training_artifact_hashes', all(file_hash(settings.model_root / 'whisper-small-publisher-expanded-v1' / name) == sha for name, sha in training['files'].items()))
    check('distinct_real_model_files', plan['models']['parent']['manifest']['files']['model.bin'] != plan['models']['expanded']['manifest']['files']['model.bin']
          and all(all(file_hash(settings.model_root / model['name'] / n) == sha for n, sha in model['manifest']['files'].items()) for model in plan['models'].values()))
    rows, execution = result['rows'], read(output / 'execution.json')
    check('all_frozen_runs_included', len(rows) == 1048 and len(plan['items']) == 524
          and len({(r['system'], r['id']) for r in rows}) == 1048
          and all({r['id'] for r in rows if r['system'] == system} == {i['id'] for i in plan['items']} for system in ('parent', 'expanded')))
    check('raw_predictions_preserved', len(execution['prediction_sha256']) == 1048
          and all(file_hash(output / 'predictions' / n) == sha for n, sha in execution['prediction_sha256'].items()))
    check('independent_edit_distance', all(independent_distance(r['reference'], r['hypothesis']) == sum(r['score'][k] for k in ('S', 'D', 'I')) for r in rows if r['score'] is not None))
    check('cohort_aggregation', all(all(sum(r['score'][k] for r in rows if r['cohort'] == name and r['system'] == system and r['score'] is not None) == c['scores'][system][k]
          for k in ('S', 'D', 'I', 'N')) for name, c in result['cohorts'].items() for system in ('parent', 'expanded')))
    check('final_per_sample_asr_failure_count', result['runtime_failures'] == sum(r['runtime_failure'] is not None for r in rows) == 0)
    interruption = read(root / 'resumption/attempt-1.json')
    interrupted_state = read(root / 'resumption/interrupted-state.json')
    check('storage_interruption_retained', interruption['status'] == 'INTERRUPTED_STORAGE_WRITE_ERROR'
          and interruption['process_exit_code'] == interrupted_state['ExitCode'] == 255
          and not interruption['unpersisted_hypothesis_available']
          and 'Input/output error' in (root / 'resumption/interrupted-tail.log').read_text(encoding='utf-8-sig'))
    check('completed_predictions_unchanged_after_resumption', len(interruption['saved_prediction_sha256']) == 707
          and all(file_hash(output / 'predictions' / n) == sha for n, sha in interruption['saved_prediction_sha256'].items()))
    check('resumption_completed_every_missing_prediction', len(interruption['missing_prediction_files']) == 341
          and all((output / 'predictions' / n).is_file() for n in interruption['missing_prediction_files'])
          and set(interruption['saved_prediction_sha256']).isdisjoint(interruption['missing_prediction_files'])
          and set(execution['prediction_sha256']) == set(interruption['saved_prediction_sha256']) | set(interruption['missing_prediction_files']))
    check('same_precision_and_no_reference_prompts', all(r['config']['compute_type'] == 'float16' and r['config']['device'] == 'cuda'
          and r['effective_options']['beam_size'] == 5 and r['effective_options']['temperature'] == 0
          and r['effective_options']['initial_prompt'] is None and r['effective_options']['hotwords'] is None
          and not r['effective_options']['vad_filter'] and not r['config']['denoise']['enabled'] and not r['config']['redecode'] for r in rows))
    noise = read(Path('/voici-diagnostic/plan.json'))
    starts = [n['original_start_sec'] for n in noise['items']]
    check('complete_contiguous_noise_original', len(noise['items']) == 151 and starts == [20 * i for i in range(151)]
          and abs(sum(n['duration_sec'] for n in noise['items']) - noise['duration_sec']) < 1 / 16000)
    check('noise_never_admitted_to_training', noise['source_partition'] == 'dev_only_no_training_or_test_use'
          and not noise['normal_training_augmentation_admitted'] and not noise['local_human_audio_verification']
          and all('voici' not in s.audio_path and (s.augmentation is None or (
              s.augmentation.get('type') == 'publisher_audio_chain' and s.variant_of is not None
              and s.annotation_provenance['source_sample_id'].startswith('bleriot-c:')
              and s.augmentation.get('source_sha256') != noise['source_sha256'])) for s in train + dev))
    noise_audio = np.concatenate([sf.read(settings.audio_root / n['audio_path'], dtype='float32')[0] for n in noise['items']])
    source_rows = {s.sample_id: s for s in all_rows}
    mixture_checks = []
    for item in plan['items']:
        if 'mixing' not in item:
            continue
        mixing = item['mixing']
        source = source_rows[item['source_id']]
        speech = sf.read(settings.audio_root / source.audio_path, dtype='float32')[0]
        mixture = sf.read(settings.audio_root / item['audio_path'], dtype='float32')[0]
        offset = mixing['noise_offset_samples_16k']
        component = noise_audio[offset:offset + len(speech)]
        expected = (speech + mixing['alpha'] * component) * mixing['mixture_gain']
        active = np.zeros(len(speech), dtype=bool)
        for a, b in mixing['vad_intervals_samples']:
            active[a:b] = True
        speech_component = speech * mixing['mixture_gain']
        residual = mixture - speech_component
        measured = 20 * np.log10(np.sqrt(np.mean(speech_component[active].astype(np.float64) ** 2)) / np.sqrt(np.mean(residual[active].astype(np.float64) ** 2)))
        mixture_checks.append(np.array_equal(mixture, expected) and abs(measured - mixing['target_snr_db']) < 1e-4
                              and np.abs(mixture).max() <= .980001 and source.split == 'dev' and item['group_id'] == 'voici-original-2660112')
    check('actual_mixtures_match_sources_snr_and_partition', len(mixture_checks) == 204 and all(mixture_checks))
    rates = result['cohorts']['noise_only']['inserted_words_per_minute']
    minutes = sum(n['duration_sec'] for n in noise['items']) / 60
    check('noise_insertion_counts', all(abs(rates[s] - sum(len(lexical_normalizer_v1(r['hypothesis']).split()) for r in rows if r['cohort'] == 'noise_only' and r['system'] == s) / minutes) < 1e-6 for s in ('parent', 'expanded')))
    runtime = read(root / 'north55-expanded-evaluation-v1.json')
    check('actual_gpu_execution_offline_after_freeze', runtime['network_mode'] == 'none' and runtime['state']['ExitCode'] == 0
          and runtime['state']['Status'] == 'exited' and 'CUDA_VISIBLE_DEVICES=0' in runtime['gpu_environment']
          and datetime.fromisoformat(plan['created_at']) < datetime.fromisoformat(runtime['state']['StartedAt'].replace('Z', '+00:00')))
    check('actual_training_offline', read(root / 'north55-expanded-training-v1.json')['network_mode'] == 'none'
          and read(root / 'north55-expanded-training-v1.json')['state']['ExitCode'] == 0)
    cpu = read(root / 'cpu-smoke.json')
    check('new_checkpoint_real_CPU_offline', cpu['status'] == 'PASS' and cpu['actual_device'] == 'cpu'
          and cpu['actual_compute_type'] == 'int8_float32' and read(root / 'north55-expanded-cpu-v1.json')['network_mode'] == 'none')
    check('no_scientific_pass_or_promotion', not result['candidate_selected'] and not result['release_promoted']
          and not result['test_accessed'] and result['asr_quality_gate'] == result['nlp_quality_gate'] == result['temporal_gate'] == 'NEEDS_MORE_DATA')
    suites = list(ET.parse(root / 'contract-tests.xml').getroot().iter('testsuite'))
    check('five_contract_tests_passed', sum(int(s.get('tests', 0)) for s in suites) == 5
          and all(int(s.get(k, 0)) == 0 for s in suites for k in ('failures', 'errors', 'skipped')))
    reproduction = read(root / 'score-reproduction.json')
    check('powershell_and_linux_scores_reproduced', {r['environment'] for r in reproduction} == {'powershell', 'linux_wsl_ubuntu'}
          and all(r['exit_code'] == 0 and r['identical'] and r['before_sha256'] == r['after_sha256']
                  and all(file_hash(output / n) == sha for n, sha in r['after_sha256'].items()) for r in reproduction))
    services = read(root / 'resumption/restart-policies.json')
    check('database_and_broker_recovered_with_restart_policy', len(services) == 2
          and all(s['restart_policy']['Name'] == 'unless-stopped' and s['status'] == 'running' and s['health'] == 'healthy' for s in services))
    check('api_and_annotation_available_after_recovery', all(s['status'] == 200 for s in read(root / 'resumption/service-health.json').values()))
    report = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'implemented': True, 'executed': True,
              'verified': all(checks.values()), 'verified_at': now().isoformat(), 'checks': checks,
              'verifier_sha256': file_hash(Path(__file__)), 'independent_distance_script_sha256': file_hash(Path(__file__).with_name('verify_clean_controls.py')),
              'asr_quality_gate': 'NEEDS_MORE_DATA', 'candidate_selected': False,
              'infrastructure_interruptions': 1, 'recovered': checks['completed_predictions_unchanged_after_resumption']
              and checks['resumption_completed_every_missing_prediction'] and runtime['state']['ExitCode'] == 0,
              'final_per_sample_asr_failures': result['runtime_failures'],
              'artifact_sha256': {str(p.relative_to(root)): file_hash(p) for p in root.rglob('*') if p.is_file() and p.name != 'verification.json'}}
    atomic_json(root / 'verification.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'artifact_sha256'}, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
