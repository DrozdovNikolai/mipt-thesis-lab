"""Independent integrity/metric checks of the additional-source experiments."""

import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import soundfile as sf

from north55_speech.core import atomic_json, file_hash, now
from north55_speech.metrics import lexical_normalizer_v1
from scripts.additional_asr_experiment import inference_regions, script_identity
from scripts.verify_clean_controls import independent_distance

ROOT = Path('/reports/additional-sources-v1')


def read(path):
    return json.loads(path.read_bytes())


def binary_metrics(labels, predictions):
    output = {}
    for value, key in ((0, 'negative'), (1, 'safety_voice')):
        tp = sum(y == p == value for y, p in zip(labels, predictions, strict=True))
        fp = sum(y != value and p == value for y, p in zip(labels, predictions, strict=True))
        fn = sum(y == value and p != value for y, p in zip(labels, predictions, strict=True))
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        output[key] = {'precision': precision, 'recall': recall, 'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0, 'support': tp + fn}
    output['macro_f1'] = (output['negative']['f1'] + output['safety_voice']['f1']) / 2
    output['accuracy'] = sum(a == b for a, b in zip(labels, predictions, strict=True)) / len(labels)
    return output


def main():
    checks = {}

    def check(name, condition):
        checks[name] = bool(condition)

    plan = read(ROOT / 'asr/plan.json')
    result = read(ROOT / 'asr/comparison.json')
    execution = read(ROOT / 'asr/execution.json')
    check('ASR_code_frozen', all(plan[k] == value for k, value in script_identity().items()))
    check('ASR_plan_identity', result['plan_sha256'] == execution['plan_sha256'] == file_hash(ROOT / 'asr/plan.json'))
    check('all_3305_comparisons', len(result['rows']) == len(execution['prediction_sha256']) == 3305
          and len(plan['items']) == 661 and len({(r['id'], r['trial']) for r in result['rows']}) == 3305)
    check('all_predictions_immutable', all(file_hash(ROOT / 'asr/predictions' / name) == sha for name, sha in execution['prediction_sha256'].items()))
    check('all_audio_hashes', all(file_hash(Path('/audio') / i['audio_path']) == i['audio_sha256'] for i in plan['items']))
    check('model_files_unchanged', all(file_hash(Path('/models') / plan['model']['name'] / n) == sha for n, sha in plan['model']['manifest']['files'].items()))
    rows = result['rows']
    reused = [r for r in rows if r['reused']]
    check('524_parent_outputs_reused_with_provenance', len(reused) == 524 and all(r['trial'] == 'baseline' and r['asr_calls'] == 0
          and file_hash(Path(r['reused_from']['path'])) == r['reused_from']['sha256']
          and all(r[k] == read(Path(r['reused_from']['path']))[k] for k in ('hypothesis', 'segments', 'runtime_failure', 'effective_options')) for r in reused))
    previous = read(Path('/reports/all-sources-v1/evaluation/execution.json'))
    check('all_1048_previous_answers_preserved', all(file_hash(Path('/reports/all-sources-v1/evaluation/predictions') / n) == sha for n, sha in previous['prediction_sha256'].items()))
    check('actual_regions_match_frozen_designs', all(r['asr_regions_samples'] == inference_regions(round(r['duration_sec'] * 16000), [tuple(i) for i in r['speech_regions_samples']], r['trial'])
          or r['asr_regions_samples'] == [list(i) for i in inference_regions(round(r['duration_sec'] * 16000), [tuple(i) for i in r['speech_regions_samples']], r['trial'])] for r in rows))
    check('no_utterance_concatenation_or_timestamp_shift', all(all(0 <= a < b <= round(r['duration_sec'] * 16000) for a, b in r['asr_regions_samples'])
          and all(0 <= s['start_sec'] <= s['end_sec'] <= r['duration_sec'] + 1e-5 for s in r['segments']) for r in rows))
    check('gate_empty_record_has_no_model_calls', all(not r['hypothesis'] and not r['segments'] and r['asr_calls'] == 0 for r in rows if not r['asr_regions_samples']))
    check('same_checkpoint_precision_options', all(r['config'] == plan['config'] and r['effective_options']['beam_size'] == 5
          and r['effective_options']['temperature'] == 0 and r['effective_options']['initial_prompt'] is None
          and r['effective_options']['hotwords'] is None and not r['effective_options']['vad_filter']
          and r['effective_options']['language'] == (r['input_language'] if r['input_language'] in ('en', 'ru') else None) for r in rows))
    check('ASR_failure_count_matches_all_rows', result['runtime_failures'] == sum(r['runtime_failure'] is not None for r in rows) == 0)
    check('independent_edit_distances', all(independent_distance(r['reference'], r['hypothesis']) == sum(r['score'][k] for k in ('S', 'D', 'I')) for r in rows if r['score'] is not None))
    check('independent_aggregation', all(sum(r['score'][k] for r in rows if r['cohort'] == cohort and r['trial'] == trial and r['score'] is not None) == c['scores'][trial][k]
          for cohort, c in result['cohorts'].items() for trial in plan['trials'] for k in ('S', 'D', 'I', 'N')))
    check('noise_rates_match_words_and_channel_minutes', all(abs(c['inserted_words_per_minute'][trial] - sum(len(lexical_normalizer_v1(r['hypothesis']).split()) for r in rows if r['cohort'] == cohort and r['trial'] == trial) / c['channel_minutes']) < 1e-9
          for cohort, c in result['cohorts'].items() if 'channel_minutes' in c for trial in plan['trials']))
    audio_plan = read(Path('/additional-audio/plan.json'))
    check('new_audio_plan_frozen', file_hash(Path('/additional-audio/plan.json')) == plan['additional_audio_plan_sha256']
          and file_hash(Path('/app/scripts/prepare_additional_audio.py')) == audio_plan['script_sha256'])
    check('new_data_counts_and_group_scope', len(audio_plan['items']) == 137 and len(audio_plan['bleriot_b_inventory']) == 102
          and len({i['group_id'] for i in audio_plan['items'] if i['cohort'] == 'bleriot_b_noise'}) == 2
          and len({i['group_id'] for i in audio_plan['items'] if i['cohort'] == 'general_ru'}) == 1
          and not audio_plan['noise_training_admitted'] and all(i['split'] == 'dev' and not i['primary'] and not i['scope_verified'] for i in audio_plan['items']))
    check('new_audio_decodes_and_duration_matches', all(sf.info(Path('/audio') / i['audio_path']).samplerate == 16000
          and sf.info(Path('/audio') / i['audio_path']).channels == 1
          and abs(sf.info(Path('/audio') / i['audio_path']).duration - i['duration_sec']) < 1 / 16000 for i in audio_plan['items']))
    acquisition = read(ROOT / 'bleriot-b-acquisition.json')['acquisition']
    check('BLeRIOT_B_publisher_checksums', len(acquisition['files']) == 7 and acquisition['license_id'] == 'CC-BY-NC-4.0'
          and all(file_hash(Path('/source-b') / r['filename']) == r['sha256']
                  and hashlib.md5((Path('/source-b') / r['filename']).read_bytes(), usedforsecurity=False).hexdigest() == r['publisher_md5'] for r in acquisition['files']))
    fleurs = read(Path('/fleurs/acquisition.json'))
    check('official_RU_control_acquisition', fleurs['license'] == 'CC-BY-4.0' and not fleurs['test_downloaded']
          and all(file_hash(Path('/fleurs') / f['path']) == f['sha256'] for f in fleurs['files']))
    cvr_proof = read(Path('/cvr/preparation.json'))
    datasets = {s: [json.loads(line) for line in (Path('/cvr/train-dev') / f'{s}.jsonl').read_text().splitlines()] for s in ('train', 'dev')}
    references = [json.loads(line) for line in Path('/cvr/sealed/test-references.jsonl').read_text().splitlines()]
    groups = {s: {r['group_id'] for r in rs} for s, rs in datasets.items()}
    groups['test'] = {r['group_id'] for r in references}
    check('native_CVR_cases_disjoint', all(not groups[a] & groups[b] for a, b in (('train', 'dev'), ('train', 'test'), ('dev', 'test'))))
    check('native_CVR_prepared_files_immutable', all(file_hash(Path('/cvr') / n) == sha for n, sha in cvr_proof['files'].items()))
    check('source_native_human_labels_not_renamed', all(r['human_label_field'] == 'coding_safety_voice' and r['label'] in (0, 1)
          and r['label_name'] == 'source_native_safety_voice' and r['project_labels'] is None and r['project_salience'] is None
          and r['temporal_events'] is None and not r['scope_independently_verified'] for rs in datasets.values() for r in rs))
    nlp = read(ROOT / 'nlp-final/comparison.json')
    nlp_selection = read(ROOT / 'nlp-final/final-selection.json')
    nlp_predictions = read(ROOT / 'nlp-final/predictions.json')
    check('native_selection_before_holdout', datetime.fromisoformat(nlp_selection['frozen_at']) < datetime.fromisoformat(nlp_predictions['executed_at'])
          and nlp['selection_sha256'] == nlp_predictions['selection_sha256'] == file_hash(ROOT / 'nlp-final/final-selection.json'))
    check('native_model_hash_and_trial_budget', file_hash(ROOT / 'nlp-final/model.skops') == nlp_selection['model_sha256']
          and nlp_selection['candidate_trials'] + nlp_selection['rule_baselines'] == 14)
    predictions = {r['id']: r for r in nlp_predictions['rows']}
    labels = [r['label'] for r in references]
    independent = {s: binary_metrics(labels, [predictions[r['id']][s] for r in references]) for s in nlp['scores']}
    check('native_precision_recall_F1_independently_recomputed', all(abs(independent[s][k][m] - nlp['scores'][s][k][m]) < 1e-12
          for s in independent for k in ('negative', 'safety_voice') for m in ('precision', 'recall', 'f1', 'support')))
    check('native_holdout_limit_not_hidden', nlp['groups'] == 1 and nlp['rows'] == 49 and nlp['status'] == 'INCONCLUSIVE'
          and nlp['confidence_interval'] is None and nlp['project_label_mapping'] is None and not nlp['release_promoted'])
    inference_container = read(ROOT / 'north55-cvr-native-holdout-v1.json')
    check('native_holdout_inference_has_no_label_mount', any(m['Destination'] == '/inputs/test-inputs.jsonl' for m in inference_container['mounts'])
          and not any('references' in m['Destination'] or m['Destination'] in {'/cvr', '/data', '/train-dev'} for m in inference_container['mounts']))
    names = ('north55-additional-asr-v1', 'north55-additional-cpu-v1', 'north55-cvr-native-training-v1', 'north55-cvr-context-training-v1', 'north55-cvr-native-holdout-v1')
    check('all_experiments_exited_zero_without_network', all(read(ROOT / f'{n}.json')['network_mode'] == 'none'
          and read(ROOT / f'{n}.json')['state']['ExitCode'] == 0 and read(ROOT / f'{n}.json')['state']['Status'] == 'exited' for n in names))
    for n in ('north55-cvr-native-training-v1', 'north55-cvr-context-training-v1'):
        mounts = read(ROOT / f'{n}.json')['mounts']
        check(n + '_no_test_mount', not any(m['Destination'] in {'/cvr', '/data', '/inputs', '/references'} or 'sealed' in m['Source'] for m in mounts))
    cpu = read(ROOT / 'cpu-smoke.json')
    check('new_real_CPU_smoke', cpu['status'] == 'PASS' and cpu['actual_device'] == 'cpu' and cpu['actual_compute_type'] == 'int8_float32'
          and len(cpu['rows']) == 2 and cpu['rows'][0]['hypothesis'])
    suites = list(ET.parse(ROOT / 'contracts.xml').getroot().iter('testsuite'))
    check('15_contract_tests_passed', sum(int(s.get('tests', 0)) for s in suites) == 15
          and all(int(s.get(k, 0)) == 0 for s in suites for k in ('failures', 'errors', 'skipped')))
    check('no_scientific_promotion', result['asr_quality_gate'] == result['critical_entity_gate'] == 'NEEDS_MORE_DATA'
          and not result['candidate_selected'] and not result['release_promoted'] and not result['test_accessed']
          and nlp['project_nlp_quality_gate'] == nlp['temporal_gate'] == 'NEEDS_MORE_DATA')
    replay = read(ROOT / 'score-reproduction.json')
    check('powershell_linux_score_reproducible', {r['environment'] for r in replay} == {'powershell', 'linux_wsl_ubuntu'}
          and all(r['exit_code'] == 0 and r['identical'] and r['before_sha256'] == r['after_sha256'] == file_hash(ROOT / 'asr/comparison.json') for r in replay))
    report = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'implemented': True, 'executed': True, 'verified': all(checks.values()),
        'verified_at': now().isoformat(), 'checks': checks, 'quality_gate': 'NEEDS_MORE_DATA', 'release_promoted': False,
        'verifier_sha256': file_hash(Path(__file__)), 'artifact_sha256': {str(p.relative_to(ROOT)): file_hash(p) for p in ROOT.rglob('*') if p.is_file() and p.name != 'verification.json' and '__pycache__' not in p.parts}}
    atomic_json(ROOT / 'verification.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'artifact_sha256'}, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
