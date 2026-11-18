"""Independent artifact and metric checks for language-large-v1."""

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from north55_speech.core import atomic_json, file_hash, now
from north55_speech.metrics import lexical_normalizer_v1
from scripts.acquire_large_v3 import validate_file
from scripts.language_large_experiment import declared_language, identity
from scripts.verify_clean_controls import independent_distance

ROOT = Path('/reports/language-large-v1')


def read(path):
    return json.loads(path.read_bytes())


def main():
    checks = {}

    def check(name, value):
        checks[name] = bool(value)

    plan, result = read(ROOT / 'plan.json'), read(ROOT / 'comparison.json')
    items = read(ROOT / 'inputs.json')
    checks['code_config_and_scorer_frozen'] = all(plan[k] == v for k, v in identity().items())
    snapshot = read(ROOT / 'frozen/manifest.json')
    check('108_executed_source_files_preserved', len(snapshot['files']) == 108 and all(file_hash(ROOT / 'frozen' / name) == sha for name, sha in snapshot['files'].items()))
    check('inputs_and_references_frozen', file_hash(ROOT / 'inputs.json') == plan['inputs_sha256']
          and file_hash(Path('/scoring/references.json')) == plan['references_sha256'])
    check('all_661_original_inputs', len(items) == len({i['id'] for i in items}) == 661
          and file_hash(Path('/reports/additional-sources-v1/asr/plan.json')) == plan['previous_plan_sha256'])
    check('all_audio_hashes', all(file_hash(Path('/audio') / i['audio_path']) == i['audio_sha256'] for i in items))
    review_path = Path('/reviewed/dev.jsonl')
    reviews = {'reviewed-' + r['sample_id']: r for r in [json.loads(line) for line in review_path.read_text().splitlines()]}
    check('language_uses_unchanged_saved_human_metadata', file_hash(review_path) == plan['reviewed_manifest_sha256']
          and all(i['input_language'] == declared_language(i | {'input_language': i['previous_input_language']}, reviews) for i in items))
    changed = [i for i in items if i['input_language'] != i['previous_input_language']]
    check('exactly_five_EN_declarations_no_FR_mixed_override', len(changed) == len(plan['language_evidence']) == 5
          and all(i['cohort'] == 'partial_human_dev' and i['previous_input_language'] == 'auto' and i['input_language'] == 'en' for i in changed))
    check('input_manifest_has_no_transcripts', all(not {'reference', 'reference_text', 'hypothesis', 'text', 'labels', 'critical_entities'} & i.keys() for i in items))
    check('two_new_configurations_within_budget', plan['search_budget'] == {'previous_configurations_conservative': 14, 'new_configurations': 2, 'total': 16, 'limit': 16})
    a, b = plan['configs']['small_known'], plan['configs']['large_known']
    check('model_comparison_changes_only_checkpoint', {k: v for k, v in a.items() if k != 'model'} == {k: v for k, v in b.items() if k != 'model'}
          and a['device'] == 'cuda' and a['compute_type'] == 'float16' and not a['vad']['enabled'] and not a['denoise']['enabled']
          and not a['redecode'] and a['hotwords'] is None)
    acquisition, metadata = read(ROOT / 'model-acquisition.json'), read(ROOT / 'model-source.json')
    entries = {r['rfilename']: r for r in metadata['siblings']}
    for row in acquisition['files']:
        validate_file(Path('/models') / 'whisper-large-v3-systran-ct2' / row['name'], entries[row['name']])
    check('large_model_publisher_checksums_and_license', len(acquisition['files']) == 6 and metadata['cardData']['license'] == 'mit'
          and metadata['sha'] == 'edaa852ec7e145841d8ffdb056a99866b5f0a478'
          and acquisition['manifest']['files']['model.bin'] == '69f74147e3334731bc3a76048724833325d2ec74642fb52620eda87352e3d4f1')
    check('both_model_manifests_and_weights_frozen', all(file_hash(Path('/models') / m['name'] / 'manifest.json') == m['manifest_sha256']
          and all(file_hash(Path('/models') / m['name'] / n) == sha for n, sha in m['manifest']['files'].items()) for m in plan['models'].values()))
    rows = result['rows']
    check('1983_records_with_1322_fresh_results', len(rows) == result['records'] == 1983 and result['new_inferences'] == 1322
          and len({(r['system'], r['id']) for r in rows}) == 1983)
    lookup = {(r['system'], r['id']): r for r in rows}
    for system in plan['systems']:
        execution = read(ROOT / system / 'execution.json')
        check(system + '_all_661_immutable', len(execution['prediction_sha256']) == 661 and execution['plan_sha256'] == file_hash(ROOT / 'plan.json')
              and all(file_hash(ROOT / system / 'predictions' / name) == sha for name, sha in execution['prediction_sha256'].items())
              and all(file_hash(ROOT / system / name) == sha for name, sha in execution['runtime_sha256'].items()))
        selected = [r for r in rows if r['system'] == system]
        check(system + '_config_options_and_raw_output', all(r['config'] == plan['configs'][system] and r['plan_sha256'] == file_hash(ROOT / 'plan.json')
              and r['effective_options']['language'] == (r['input_language'] if r['input_language'] in {'en', 'ru'} else None)
              and r['effective_options']['initial_prompt'] is None and r['effective_options']['hotwords'] is None
              and r['hypothesis'] == ' '.join(s['raw_asr_text'].strip() for s in r['segments']) for r in selected))
        raw_rows = [read(ROOT / system / 'predictions' / f'{r["id"]}.json') for r in selected]
        check(system + '_scorer_preserves_raw_records', all(all(scored[k] == v for k, v in raw.items()) for scored, raw in zip(selected, raw_rows, strict=True)))
        runtimes = [read(ROOT / system / n) for n in execution['runtime_sha256']]
        check(system + '_actual_CUDA_float16_and_memory_measured', all(r['actual_device'] == 'cuda' and r['actual_precision'] == 'float16'
              and r['memory']['samples'] and r['memory']['process_peak_rss_kib'] > 0 for r in runtimes)
              and sum(r['new_records'] for r in runtimes) == 661)
        timing = result['timing'][system]
        check(system + '_timing_aggregation', abs(timing['asr_seconds'] - sum(r['asr_elapsed_sec'] for r in selected)) < 1e-9
              and abs(timing['asr_rtf'] - timing['asr_seconds'] / sum(r['duration_sec'] for r in selected)) < 1e-12)
    check('661_prior_responses_not_overwritten', all(file_hash(Path(v['path'])) == v['sha256'] for v in plan['previous_baseline'].values()))
    check('same_language_and_options_between_fresh_models', all(lookup['small_known', i['id']]['effective_options'] == lookup['large_known', i['id']]['effective_options'] for i in items))
    check('all_timestamps_within_original_input', all(0 <= s['start_sec'] <= s['end_sec'] <= r['duration_sec'] + 1e-6
          and all(0 <= w['start_sec'] <= w['end_sec'] <= r['duration_sec'] + 1e-6 for w in s['words']) for r in rows for s in r['segments']))
    check('independent_edit_distance', all(independent_distance(r['reference'], r['hypothesis']) == sum(r['score'][k] for k in ('S', 'D', 'I')) for r in rows if r['score'] is not None))
    check('independent_corpus_aggregation', all(sum(r['score'][k] for r in rows if r['cohort'] == cohort and r['system'] == s and r['score'] is not None) == c['scores'][s][k]
          for cohort, c in result['cohorts'].items() for s in ('small_previous', *plan['systems']) for k in ('S', 'D', 'I', 'N')))
    interpretation = read(ROOT / 'ci-interpretation.json')
    check('empty_and_single_group_CIs_not_interpreted', all(not interpretation[c][e]['independent_sampling_interpretable']
          for c in ('noise_only', 'bleriot_b_noise', 'general_ru', 'voici_mix_0dB', 'voici_mix_10dB') for e in ('language_effect', 'model_effect')))
    check('noise_counts_use_channel_minutes', all(abs(c['inserted_words_per_minute'][s] - sum(len(lexical_normalizer_v1(r['hypothesis']).split()) for r in rows if r['cohort'] == cohort and r['system'] == s) / c['channel_minutes']) < 1e-10
          for cohort, c in result['cohorts'].items() if 'channel_minutes' in c for s in ('small_previous', *plan['systems'])))
    check('failures_retained_and_counted', all(result['runtime_failures'][s] == sum(r['runtime_failure'] is not None for r in rows if r['system'] == s) for s in result['runtime_failures'])
          and all(not r['hypothesis'] for r in rows if r['runtime_failure']))
    names = ('north55-language-small-v1', 'north55-language-large-v1')
    containers = [read(ROOT / f'{n}.json') for n in names]
    check('both_inference_containers_offline_and_exited_zero', all(c['network_mode'] == 'none' and c['state']['ExitCode'] == 0 and c['state']['Status'] == 'exited' for c in containers))
    check('containers_have_no_reference_or_old_report_mount', all(not any(m['Destination'] in {'/reports', '/scoring', '/reviewed', '/data'} or 'references' in m['Destination'] for m in c['mounts']) for c in containers))
    check('plan_frozen_before_inference_and_models_sequential', datetime.fromisoformat(plan['frozen_at']) < datetime.fromisoformat(containers[0]['state']['StartedAt'])
          and datetime.fromisoformat(containers[0]['state']['FinishedAt']) <= datetime.fromisoformat(containers[1]['state']['StartedAt']))
    cpu = read(ROOT / 'cpu-smoke.json')
    check('large_real_CPU_smoke', cpu['status'] == 'PASS' and cpu['actual_device'] == 'cpu' and cpu['actual_compute_type'] == 'int8_float32'
          and len(cpu['rows']) == 3 and all(r['hypothesis'] for r in cpu['rows'][:2]) and cpu['model_manifest'] == plan['models']['large_known']['manifest'])
    cpu_container = read(ROOT / 'north55-language-large-cpu-v1.json')
    check('CPU_offline_exit_zero_and_failed_mount_preserved', cpu_container['network_mode'] == 'none' and cpu_container['state']['ExitCode'] == 0
          and read(ROOT / 'cpu-attempt1-mount-failure.json')['state']['Status'] == 'created')
    suites = list(ET.parse(ROOT / 'contracts.xml').getroot().iter('testsuite'))
    check('12_contract_tests_passed', sum(int(s.get('tests', 0)) for s in suites) == 12
          and all(int(s.get(k, 0)) == 0 for s in suites for k in ('failures', 'errors', 'skipped')))
    replay = read(ROOT / 'score-reproduction.json')
    check('PowerShell_Linux_scores_identical', {r['environment'] for r in replay} == {'powershell', 'linux_wsl_ubuntu'}
          and all(r['exit_code'] == 0 and r['identical'] and r['before_sha256'] == r['after_sha256'] == file_hash(ROOT / 'comparison.json') for r in replay))
    before, after = read(ROOT / 'preservation-before.json'), read(ROOT / 'preservation-after.json')
    check('requirements_baseline_reviews_and_old_reports_preserved', before['files'] == after['files'])
    check('no_release_or_same_checkpoint_gain_claim', not result['same_checkpoint_pipeline_gain_claimed'] and not result['test_accessed'] and not result['release_promoted']
          and result['asr_quality_gate'] == result['critical_entity_gate'] == 'NEEDS_MORE_DATA')
    report = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'implemented': True, 'executed': True, 'verified': all(checks.values()),
        'verified_at': now().isoformat(), 'checks': checks, 'quality_gate': 'NEEDS_MORE_DATA', 'release_promoted': False,
        'verifier_sha256': file_hash(Path(__file__)), 'artifact_sha256': {str(p.relative_to(ROOT)): file_hash(p) for p in ROOT.rglob('*') if p.is_file() and p.name != 'verification.json' and '__pycache__' not in p.parts}}
    atomic_json(ROOT / 'verification.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'artifact_sha256'}, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
