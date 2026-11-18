"""Verify completed source/review/ablation engineering without inventing quality."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from north55_speech.benchmark import code_hash
from north55_speech.core import atomic_json, digest, file_hash, now
from north55_speech.datasets import verify_partition_proof

root = Path("/reports")


def read(name):
    return json.loads((root/name).read_text(encoding="utf-8"))


prep, packet = read("bleriot-preparation-v2.json"), read("annotation-packet-v1.json")
plan, ablation = read("pending-dev-ablation-plan.json"), read("pending-dev-ablation.json")
proof = json.loads(Path("/protocol/partition-proof.json").read_text())
verify_partition_proof(proof)
rows = ablation["runs"]
expected = {(sample, trial) for sample in plan["sample_ids"] for trial in plan["configs"]}
successful = [row for row in rows if row["runtime_failure"] is None]
model_ids = {digest(row["result"]["model_manifest"]) for row in successful}
precisions = {(row["result"]["effective_config"]["model"], row["result"]["effective_config"]["compute_type"],
               row["result"]["effective_config"]["device"]) for row in successful}
suite = ET.parse(root/"annotation-sidecar-tests.xml").getroot().find("testsuite")
assert suite is not None
checks = {
    "all_unique_sources_retained": prep["recordings"] == 67 and prep["unique_noisy"] == 27 and prep["no_noise_difficulty_exclusions"],
    "existing_source_groups_preserved": prep["existing_groups_unchanged"],
    "reference_free_partition_proof_valid": True,
    "annotation_packet_train_dev_only": packet["items"] == 18 and packet["groups"]["split_groups"]["test"] == 0,
    "live_audio_ranges_exports": read("annotation-service.json")["status"] == "PASS",
    "focused_tests": int(suite.attrib["tests"]) >= 15 and int(suite.attrib["failures"]) == 0 and int(suite.attrib["errors"]) == 0,
    "full_transformers_offline_real_asr": read("transformers-offline-real-asr.json")["status"] == "PASS",
    "ablation_plan_unchanged": ablation["plan_sha256"] == file_hash(root/"pending-dev-ablation-plan.json"),
    "ablation_current_core_code": plan["code_hash"] == code_hash(),
    "all_frozen_inference_items": len(rows) == len(expected) == 64 and {(r["sample_id"], r["trial"]) for r in rows} == expected,
    "zero_runtime_failures": len(successful) == len(rows),
    "same_model_precision": len(model_ids) == 1 and precisions == {("small", "int8", "cpu")},
    "original_timestamps": all(0 <= s["start_sec"] <= s["end_sec"] <= r["duration_sec"]+0.05
                               for r in successful for s in r["result"]["segments"]),
    "offline_dev_only": ablation["network_mode"] == "none" and all(r["split"] == "dev" for r in rows),
    "no_promotion_or_fabricated_scores": ablation["wer"] is None and ablation["critical_entity_delta"] is None
        and not ablation["candidate_selected"] and not ablation["release_promoted"],
}
timings = {}
for trial in plan["configs"]:
    subset = [row for row in rows if row["trial"] == trial]
    elapsed, duration = sum(row["elapsed_sec"] for row in subset), sum(row["duration_sec"] for row in subset)
    timings[trial] = {"runs": len(subset), "elapsed_sec": elapsed, "audio_sec": duration,
                      "end_to_end_rtf": elapsed/duration, "cache_hits": sum(row["result"]["cache_hit"] for row in subset if row["runtime_failure"] is None)}
names = ("bleriot-acquisition.json", "voici-acquisition.json", "bleriot-linkage-v2.json", "bleriot-preparation-v2.json",
         "bleriot-scope-screening.json", "annotation-packet-v1.json", "annotation-script-context.json",
         "annotation-service.json", "annotation-sidecar-tests.xml", "transformers-small-acquisition.json",
         "transformers-offline-real-asr.json", "pending-dev-ablation-plan.json", "pending-dev-ablation.json",
         "reviewed-asr-readiness.json", "reviewed-events-readiness.json", "packet-asr-training-attempt.json",
         "packet-events-training-attempt.json")
report = {
    "created_at": now(), "status": "NEEDS_MORE_DATA", "core_code_hash": code_hash(),
    "source_and_inference_verification": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
    "scope": {"technical_modes": ["en", "ru", "mixed", "auto"], "quality_validated_languages": []},
    "sources": {"unique_recordings": prep["recordings"], "split_groups": prep["partitions"]["split_groups"],
                "exact_duplicates_excluded": len(prep["duplicates"]), "pending_acoustic_links": prep["parent_acoustic_review_pending"]},
    "annotation": {"clips": 18, "minutes": 6, "human_verified": 0,
                   "ui_browser": "Login visually inspected; embedded viewer sends Origin:null and is correctly refused. Authenticated contract verified through HTTP; use a normal browser.",
                   "automated_human_labels_created": 0},
    "ablation": {"implemented": True, "executed": True, "verified": all(checks.values()), "configurations": 8,
                 "runs": len(rows), "failures": ablation["runtime_failures"], "timings": timings,
                 "scored_search": "NOT_RUN", "candidate_selected": False},
    "training": {"asr": read("reviewed-asr-readiness.json")["status"], "events": read("reviewed-events-readiness.json")["status"],
                 "lora_weights_and_supported_gpu": "VERIFIED", "real_adaptation_executed": False},
    "quality": {"asr": "NEEDS_MORE_DATA", "nlp": "NEEDS_MORE_DATA", "temporal": "NEEDS_MORE_DATA",
                "lexical_wer_reduction": None, "paired_cluster_ci": None, "critical_entity_delta": None,
                "clean_control_delta": None, "nlp_rules_f1": None, "nlp_trained_f1": None,
                "release_promoted": False},
    "next_required_evidence": ["Human transcript/scope/entity/event/salience review of train/dev audio",
                               "At least 20 independent qualifying final-test groups; only 3 source groups currently reserved",
                               "Verified final-test utterance, word, entity, clean-control and non-speech support per unchanged ACCEPTANCE",
                               "Separate continuous temporal-event annotations and lawful recorded-human RU/mixed data before those claims"],
    "evidence_sha256": {name: file_hash(root/name) for name in names},
    "historical_evidence": ["delivery.json (core engineering)", "data-resumption.json (initial preparation v1)",
                            "blocker-audit.json (historical premature stop, superseded for acquisition/preparation)"],
}
atomic_json(root/"research-readiness-v2.json", report)
print(json.dumps({"status": report["status"], "source_and_inference_verification": report["source_and_inference_verification"],
                  "checks": checks, "runs": len(rows), "timings": timings}))
if not all(checks.values()):
    raise SystemExit(1)
