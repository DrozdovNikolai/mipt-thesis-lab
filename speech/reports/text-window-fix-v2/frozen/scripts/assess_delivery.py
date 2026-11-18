"""Assemble actual engineering evidence and no-data research assessment, without demo scores."""

import html
import json
import xml.etree.ElementTree as ET

from north55_speech.benchmark import code_hash, scorer_hash
from north55_speech.core import atomic_json, file_hash, settings
from north55_speech.gates import (
    asr_gate,
    engineering_gate,
    load_acceptance,
    nlp_gate,
    temporal_gate,
)

root = settings.report_root


def read(name):
    path = root / name
    return json.loads(path.read_text()) if path.is_file() else {}


acceptance = load_acceptance(__import__("pathlib").Path("configs/acceptance.yaml"))
cases = list(ET.parse(root / "final-tests.xml").getroot().iter("testcase"))
passed = {case.attrib["name"] for case in cases if not list(case)}
integration = [c for c in cases if "integration" in c.attrib.get("classname", "")]
tests_ok = bool(cases) and all(not list(c) for c in cases)
compose = read("compose-validation.json")
offline = read("offline-asr-smoke.json")
migrations = read("migration-tests.json")
short, long = read("selftest-short-result.json"), read("selftest-long-result.json")
checks = {
    "require_valid_cpu_compose": compose.get("cpu_exit_code") == 0,
    "require_gpu_override_config_validation": compose.get("gpu_exit_code") == 0,
    "require_cpu_integration_execution": tests_ok and bool(integration),
    "require_real_asr_smoke_execution": offline.get("status") == "PASS"
    and all(v["result"].get("segments") for v in offline.get("variants", {}).values()),
    "require_migrations_and_queue_recovery_tests": migrations.get("status") == "PASS"
    and short.get("verification") == "PASS"
    and long.get("verification") == "PASS"
    and long.get("job", {}).get("attempts", 0) >= 2,
    "require_review_audit_and_original_audio_preservation": tests_ok
    and any("review" in name for name in passed)
    and bool(integration),
    "require_privacy_and_unsafe_correction_tests": tests_ok
    and any("fifteen" in name or "number" in name or "fifty" in name for name in passed),
    "require_offline_inference_after_prefetch": offline.get("status") == "PASS"
    and offline.get("network_interfaces") == ["lo"]
    and offline.get("code_hash") == code_hash(),
}
checks = {key: "PASS" if value else "BLOCKED" for key, value in checks.items()}
engineering = engineering_gate(checks, acceptance) | {
    "checks": checks,
    "code_hash": code_hash(),
    "test_cases": len(cases),
    "integration_cases": len(integration),
}
atomic_json(root / "engineering-gate.json", engineering)
evidence = {key: 0 for key in acceptance["asr_quality_gate"]["minimum_evidence"]}
asr = asr_gate({"executed": False, "evidence": evidence}, acceptance)
gates = {
    "engineering_gate": engineering,
    "asr_quality_gate": asr,
    "nlp_quality_gate": nlp_gate({}, acceptance),
    "temporal_event_gate": temporal_gate({}, acceptance),
}
baseline = read("baseline.lock.json")
files = [
    "final-tests.xml",
    "final-static.log",
    "migration-tests.json",
    "selftest-short-result.json",
    "selftest-long-result.json",
    "offline-asr-smoke.json",
    "real-asr-smoke-gpu-final.json",
    "compose-validation.json",
    "cli-verification.json",
    "data-workflow.json",
    "lora-runtime.json",
    "asr-training-status.json",
    "dev-search-status.json",
    "baseline.lock.json",
]
report = {
    "gates": gates,
    "benchmark_executed": False,
    "benchmark_execution_status": "NOT_RUN",
    "validated_scope": [],
    "supported_input_modes": ["en", "ru", "mixed", "auto"],
    "deployment_candidate": "baseline",
    "release_promoted": False,
    "baseline": baseline.get("config"),
    "candidate": None,
    "measurements": {
        "baseline_lexical_wer": None,
        "candidate_lexical_wer": None,
        "relative_wer_reduction": None,
        "paired_cluster_ci": None,
        "critical_entity_f1": None,
        "clean_control_wer": None,
        "nlp_rules_f1": None,
        "nlp_trained_f1": None,
        "temporal_precision": None,
        "temporal_recall": None,
    },
    "admitted_primary_test_evidence": evidence,
    "engineering_controls": {
        "source": "LibriSpeech dev-clean CC-BY-4.0",
        "original_human_utterances": 2,
        "independent_groups": 1,
        "not_quality_evidence": True,
    },
    "optional_execution": {
        "gpu": read("real-asr-smoke-gpu-final.json").get("status", "NOT_RUN"),
        "lora_dependencies": read("lora-runtime.json"),
        "lora_training": read("asr-training-status.json"),
        "pyannote": {
            "status": "BLOCKED",
            "reason": "accepted_terms_and_local_weights_not_supplied",
            "der": None,
            "jer": None,
        },
    },
    "code_hash": code_hash(),
    "scorer_hash": scorer_hash(),
    "acceptance_sha256": file_hash(__import__("pathlib").Path("configs/acceptance.yaml")),
    "evidence_files": {name: file_hash(root / name) for name in files if (root / name).is_file()},
    "limitations": [
        "No independent admitted cockpit train/dev/test or human event/entity labels",
        "No final test answers opened and no dev candidate selected",
        "RU mode on English control does not validate RU ASR; no cockpit language is validated",
        "LoRA adaptation and trained NLP product quality remain unverified",
        "Browser login page inspected; authenticated workflows covered by API integration tests",
    ],
}
atomic_json(root / "delivery.json", report)
text = "# north55_speech: actual delivery assessment\n\n"
text += "| Gate | Status |\n|---|---|\n" + "\n".join(
    f"| {key} | {value['status']} |" for key, value in gates.items()
)
text += f"\n\nExecuted code tests: {len(cases)}; integration cases: {len(integration)}. See final-tests.xml.\n"
text += "\nNo primary cockpit benchmark was executed. WER/F1/CI are unmeasured, not zero. Candidate is not selected; baseline remains active; release is not promoted. No EN/RU/mixed cockpit quality is validated.\n"
text += "\nThe two lawful human LibriSpeech controls, generated unit fixtures, repeated long audio and GPU/CPU smoke timings are engineering evidence only. They do not satisfy the scientific gate.\n\n"
text += "```json\n" + json.dumps(report, ensure_ascii=False, indent=2) + "\n```\n"
(root / "delivery.md").write_text(text, encoding="utf-8")
(root / "delivery.html").write_text(
    "<!doctype html><meta charset='utf-8'><title>north55 delivery</title><pre>"
    + html.escape(text)
    + "</pre>",
    encoding="utf-8",
)
print(json.dumps({key: value["status"] for key, value in gates.items()}))
