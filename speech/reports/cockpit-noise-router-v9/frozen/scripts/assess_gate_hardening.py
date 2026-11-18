"""Document the scorer amendment from actual packaged tests and runtime evidence."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from north55_speech.benchmark import code_hash, scorer_hash
from north55_speech.core import atomic_json, file_hash, now
from north55_speech.gates import (
    asr_gate,
    engineering_gate,
    load_acceptance,
    nlp_gate,
    temporal_gate,
)

root = Path("/reports")
folder = root/"gate-hardening"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


before = read(root/"gate-hardening-code-before.json")
after = read(root/"gate-hardening-code-after.json")
changed = sorted(name for name in before["files"] if before["files"][name] != after["files"][name])
cases = list(ET.parse(folder/"all-tests.xml").getroot().iter("testcase"))
tests_ok = bool(cases) and not any(any(case.find(tag) is not None for tag in ("error", "failure", "skipped")) for case in cases)
integration = [case for case in cases if "integration" in case.attrib["classname"]]
runtime = read(folder/"runtime.json")
cpu, gpu = [read(folder/device/"offline-asr-smoke.json") for device in ("cpu", "gpu")]
short, long = [read(folder/f"selftest-{kind}-result.json") for kind in ("short", "long")]
previous_baseline, baseline = read(root/"baseline.lock.json"), read(folder/"baseline.lock.json")
checks = {
    "current_packaged_code_and_scorer": code_hash() == after["code_hash"] == baseline["code_hash"] and scorer_hash() == after["scorer_hash"] == baseline["scorer_hash"],
    "only_gate_and_evaluation_cohort_code_changed": changed == ["benchmark.py", "gates.py"],
    "all_tests_pass_no_skips": tests_ok and len(cases) >= 220,
    "integration_executed": len(integration) >= 9,
    "static_checks": read(folder/"static-checks.json")["exit_code"] == 0,
    "compose_variants": all(value["exit_code"] == 0 for value in runtime["compose_checks"].values()),
    "running_api_worker_use_current_image": all(runtime["running_container_images"][name] == runtime["images"]["north55-speech:0.1.0"] for name in ("north55-speech-api-1", "north55-speech-worker-1")),
    "cpu_gpu_real_offline_uncached": all(report["status"] == "PASS" and report["code_hash"] == code_hash()
        and report["network_interfaces"] == ["lo"]
        and all(not value["result"]["cache_hit"] and value["result"]["segments"] for value in report["variants"].values()) for report in (cpu, gpu)),
    "broker_outage_and_worker_sigkill_recovered": short["verification"] == long["verification"] == "PASS" and long["job"]["attempts"] >= 2,
    "baseline_parameters_and_checkpoint_unchanged": baseline["config"] == previous_baseline["config"] and baseline["model"] == previous_baseline["model"],
    "annotation_service_and_audio_preserved": read(folder/"annotation-service.json")["status"] == "PASS" and read(folder/"annotation-service.json")["annotation_writes"] == 0,
    "no_final_test_opened": not (root/"test_access_log.jsonl").exists(),
}
acceptance = load_acceptance(Path("/app/configs/acceptance.yaml"))
engineering = engineering_gate({
    "require_valid_cpu_compose": "PASS" if checks["compose_variants"] else "FAIL",
    "require_gpu_override_config_validation": "PASS" if checks["compose_variants"] else "FAIL",
    "require_cpu_integration_execution": "PASS" if checks["all_tests_pass_no_skips"] and checks["integration_executed"] else "FAIL",
    "require_real_asr_smoke_execution": "PASS" if checks["cpu_gpu_real_offline_uncached"] else "FAIL",
    "require_migrations_and_queue_recovery_tests": "PASS" if checks["broker_outage_and_worker_sigkill_recovered"] and read(root/"migration-tests.json")["status"] == "PASS" else "FAIL",
    "require_review_audit_and_original_audio_preservation": "PASS" if tests_ok and checks["annotation_service_and_audio_preserved"] else "FAIL",
    "require_privacy_and_unsafe_correction_tests": "PASS" if tests_ok else "FAIL",
    "require_offline_inference_after_prefetch": "PASS" if checks["cpu_gpu_real_offline_uncached"] else "FAIL",
}, acceptance)
engineering.update(code_hash=code_hash(), scorer_hash=scorer_hash(), test_cases=len(cases), integration_cases=len(integration), evidence_directory="gate-hardening")
if not all(checks.values()):
    engineering.update(status="FAIL", reasons=[name for name, value in checks.items() if not value])
evidence = {key: 0 for key in acceptance["asr_quality_gate"]["minimum_evidence"]}
report = {
    "created_at": now(), "amendment": "gate_numeric_and_claim_scope_v1", "verification": "PASS" if all(checks.values()) else "FAIL",
    "checks": checks, "changed_core_files": changed, "previous_code_hash": before["code_hash"], "code_hash": code_hash(),
    "previous_scorer_hash": before["scorer_hash"], "scorer_hash": scorer_hash(), "acceptance_sha256": file_hash(Path("/app/ACCEPTANCE.yaml")),
    "engineering_gate": engineering, "asr_quality_gate": asr_gate({"executed": False, "evidence": evidence}, acceptance),
    "nlp_quality_gate": nlp_gate({}, acceptance), "temporal_event_gate": temporal_gate({}, acceptance),
    "research_objective_achieved": False, "candidate_selected": False, "release_promoted": False, "validated_scope": [],
    "amendment_reason": ["Nonfinite/invalid metrics and malformed evidence could bypass ordinary comparisons",
                         "The old ASR gate did not verify the bootstrap protocol beyond the upper bound",
                         "NLP/temporal evidence must belong to the frozen language/domain and have human review provenance"],
    "previous_dev_inference": {"report": "pending-dev-ablation.json", "runs": 64, "retained": True,
                               "original_image_tag": "north55-speech:asr-plan-a5578a68", "quality_evidence": False,
                               "reuse_for_current_selection": "Requires a new scored dev run and current freeze; old reports are not relabelled"},
    "baseline_lock": "gate-hardening/baseline.lock.json", "tests_passed": len(cases),
    "source_preparation": "research-readiness-v2.json remains the historical preparation/execution snapshot",
    "limitations": ["No human-verified cockpit benchmark cohort; no measured lexical WER improvement or NLP comparison",
                    "Only 3 source test groups reserved against the unchanged minimum of 20",
                    "Embedded browser login remains INCONCLUSIVE because it supplies Origin:null; ordinary HTTP service checks pass"],
    "evidence_sha256": {str(path.relative_to(root)): file_hash(path) for path in [
        folder/"all-tests.xml", folder/"static-checks.json", folder/"runtime.json", folder/"baseline.lock.json",
        folder/"cpu/offline-asr-smoke.json", folder/"gpu/offline-asr-smoke.json", folder/"selftest-short-result.json",
        folder/"selftest-long-result.json", folder/"annotation-service.json", root/"gate-numeric-before.xml",
        root/"gate-hardening-code-before.json", root/"gate-hardening-code-after.json", root/"migration-tests.json",
    ]},
}
atomic_json(folder/"verification.json", report)
atomic_json(root/"engineering-gate.json", engineering)
print(json.dumps({"verification": report["verification"], "checks": checks, "tests": len(cases),
                  "engineering": engineering["status"], "research": report["asr_quality_gate"]["status"]}))
if not all(checks.values()):
    raise SystemExit(1)
