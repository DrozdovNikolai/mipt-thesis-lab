"""Verify retained control measurements, with an independent edit-distance check."""

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from north55_speech.core import atomic_json, file_hash, now, settings
from north55_speech.metrics import lexical_normalizer_v1
from scripts.evaluate_clean_controls import validate_plan


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def independent_distance(reference, hypothesis):
    a, b = lexical_normalizer_v1(reference).split(), lexical_normalizer_v1(hypothesis).split()
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def main():
    dataset = Path("/controls")
    root = Path("/reports/clean-control-v1")
    plan = validate_plan(dataset)
    report, execution = read(root / "comparison.json"), read(root / "execution.json")
    rows = report["rows"]
    checks = {}

    def check(name, result):
        checks[name] = bool(result)

    check("frozen_plan_and_source_identity", file_hash(dataset / "plan.json") == report["plan_sha256"] == execution["plan_sha256"] == file_hash(root / "plan.json"))
    check("executed_script_snapshot", file_hash(root / "executed-script.py") == plan["script_sha256"])
    check("all_frozen_samples_counted_twice", len(rows) == 100 and len({(r['system'], r['id']) for r in rows}) == 100
          and all({r['id'] for r in rows if r['system'] == system} == {i['id'] for i in plan['items']} for system in ('parent', 'adapted')))
    check("all_predictions_unchanged", len(execution["prediction_sha256"]) == 100 and all(file_hash(root / "predictions" / name) == sha for name, sha in execution["prediction_sha256"].items()))
    check("independent_levenshtein_totals", all(independent_distance(r['reference'], r['hypothesis']) == r['score']['S'] + r['score']['D'] + r['score']['I'] for r in rows))
    check("corpus_aggregation", all(all(sum(r['score'][k] for r in rows if r['system'] == system) == report['scores'][system][k] for k in ('S', 'D', 'I', 'N')) for system in ('parent', 'adapted')))
    check("reader_and_original_support", report['samples'] == 50 and report['groups'] == 39
          and len({i['original_id'] for i in plan['items']}) == 50 and all(i['speaker_id'] != '2277' for i in plan['items']))
    check("no_failures_dropped", report['runtime_failures'] == sum(r['runtime_failure'] is not None for r in rows) == 0)
    check("no_reference_prompts_or_extra_stages", all(r['effective_options']['initial_prompt'] is None
          and r['effective_options']['hotwords'] is None and r['effective_options']['prefix'] is None
          and not r['effective_options']['vad_filter'] and not r['effective_config']['denoise']['enabled']
          and not r['effective_config']['redecode'] and r['effective_options']['language'] == 'en' for r in rows))
    check("baseline_settings_and_precision", all(r['effective_config']['compute_type'] == 'float16'
          and r['effective_config']['device'] == 'cuda' and r['effective_options']['beam_size'] == 5
          and r['effective_options']['temperature'] == 0 for r in rows))
    models = plan['models']
    adaptation = read(settings.model_root / 'whisper-small-publisher-lora-v2/manifest.json')
    base_path = settings.model_root / 'whisper-small-transformers/manifest.json'
    check("same_transformers_parent", read(base_path) == adaptation['base_manifest']
          and models['parent']['manifest']['source_manifest_sha256'] == file_hash(base_path)
          and models['adapted']['manifest'] == adaptation['converted_model'])
    check("frozen_adaptation", file_hash(settings.model_root / 'whisper-small-publisher-lora-v2/manifest.json') == plan['adaptation_manifest_sha256'])
    check("distinct_verified_checkpoint_bytes", models['parent']['manifest']['files']['model.bin'] != models['adapted']['manifest']['files']['model.bin']
          and all(all(file_hash(settings.model_root / model['name'] / name) == sha for name, sha in model['manifest']['files'].items()) for model in models.values()))
    indexed = {(r['system'], r['id']): r for r in rows}
    check("distinct_executed_confidence_traces", all(indexed['parent', i['id']]['segments'] != indexed['adapted', i['id']]['segments'] for i in plan['items']))
    container, state = read(root / 'container.json'), read(root / 'container-state.json')
    check("actual_offline_successful_container", container['network_mode'] == 'none' and state['ExitCode'] == 0 and not state['OOMKilled'])
    check("plan_predates_inference", datetime.fromisoformat(plan['created_at']) < datetime.fromisoformat(container['started_at'].replace('Z', '+00:00')))
    check("read_only_inference_inputs", all(not m['RW'] for m in container['mounts'] if m['Destination'] in ('/audio', '/models', '/controls')))
    check("source_license_and_no_invented_human_audit", read(dataset / 'source.json')['license'] == 'CC-BY-4.0'
          and not read(dataset / 'source.json')['local_human_audio_verification'] and all(not i['primary'] for i in plan['items']))
    check("measured_guardrail_only", report['clean_control_measured_guardrail'] == 'PASS' and report['clean_wer_delta'] == 0
          and report['maximum_clean_wer_delta'] == .01 and not report['formal_release_evidence'])
    check("no_quality_or_promotion_claim", report['asr_quality_gate'] == 'NEEDS_MORE_DATA' and not report['candidate_selected']
          and not report['release_promoted'] and not report['cockpit_test_accessed'])
    suites = ET.parse('/reports/clean-control-tests.xml').getroot().iter('testsuite')
    counts = {key: 0 for key in ('tests', 'failures', 'errors', 'skipped')}
    for suite in suites:
        for key in counts:
            counts[key] += int(suite.get(key, '0'))
    check("eight_contract_tests_passed", counts == {'tests': 8, 'failures': 0, 'errors': 0, 'skipped': 0})
    result = {'status': 'PASS' if all(checks.values()) else 'FAIL', 'verified_at': now().isoformat(),
              'implemented': True, 'executed': True, 'verified': all(checks.values()), 'checks': checks, 'tests': counts,
              'verifier_sha256': file_hash(Path(__file__)), 'plan_sha256': report['plan_sha256'],
              'asr_quality_gate': 'NEEDS_MORE_DATA', 'clean_control_measured_guardrail': report['clean_control_measured_guardrail'],
              'artifact_sha256': {p.name: file_hash(p) for p in root.iterdir() if p.is_file() and p.name != 'verification.json'}}
    atomic_json(root / 'verification.json', result)
    print(json.dumps(result, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
