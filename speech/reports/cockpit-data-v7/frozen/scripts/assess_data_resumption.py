"""Summarize acquired data and verify the real, non-benchmark development smoke."""

import json
from pathlib import Path

from north55_speech.benchmark import code_hash
from north55_speech.core import atomic_json, file_hash
from north55_speech.datasets import load_manifest, verify_partition_proof

root = Path("/reports")


def read(name):
    return json.loads((root / name).read_text(encoding="utf-8"))


acquisition, prep = read("bleriot-acquisition.json"), read("bleriot-preparation.json")
smoke, voici = read("bleriot-asr-smoke.json"), read("voici-acquisition.json")
proof = json.loads(Path("/data/protocol/partition-proof.json").read_text(encoding="utf-8"))
verify_partition_proof(proof)
dev = load_manifest(Path("/data/train-dev/dev.jsonl"))
verify_partition_proof(proof, dev, "dev")
checks = {
    "publisher_checksums": acquisition["status"] == "ACQUIRED_AND_CHECKSUM_VERIFIED"
    and voici["status"] == "ACQUIRED_AND_CHECKSUM_VERIFIED",
    "frozen_partition_proof": True,
    "current_code": smoke["plan"]["code_hash"] == code_hash(),
    "offline_cpu": smoke["network_mode"] == "none" and smoke["cpu"],
    "four_runs": len(smoke["runs"]) == 4,
    "dev_only": all(row["sample_id"] in {s.sample_id for s in dev} for row in smoke["runs"]),
    "all_real_nonempty_uncached": all(
        row["result"]["segments"] and not row["result"]["cache_hit"]
        and any(s["raw_asr_text"].strip() for s in row["result"]["segments"])
        for row in smoke["runs"]
    ),
    "same_model_precision": len({
        (json.dumps(row["result"]["model_manifest"], sort_keys=True),
         row["result"]["effective_config"]["compute_type"],
         row["result"]["effective_config"]["device"])
        for row in smoke["runs"]
    }) == 1,
    "valid_source_timestamps": all(
        0 <= segment["start_sec"] <= segment["end_sec"] <=
        row["original_end_sec"]-row["original_start_sec"] + 0.05
        for row in smoke["runs"] for segment in row["result"]["segments"]
    ),
    "no_quality_claim_or_promotion": not smoke["release_promoted"] and not smoke["candidate_selected"]
    and smoke["wer"] is None and smoke["quality_gate"] == "NEEDS_MORE_DATA",
}
report = {
    "status": "PREPARED_FOR_REVIEW", "verification": "PASS" if all(checks.values()) else "FAIL",
    "checks": checks, "source_code_hash": code_hash(),
    "supersedes": "The earlier blocker audit's claim that no independent data work remained",
    "sources": {
        "BLeRIOT-A": {"wav_files": 40, "script_documents": 15, "downloaded": True,
                      "minutes": sum(r["duration_sec"] for r in prep["audio_inventory"] if r["corpus"] == "A")/60},
        "BLeRIOT-C": {"wav_files": 28, "downloaded": True, "minutes": read("bleriot-c-inventory.json")["duration_minutes"],
                      "linked_for_initial_review": prep["paired_variants"], "quarantined": len(prep["quarantined"])},
        "VOICI": {"downloaded": True, "role": "noise_only", "minutes": read("voici-inventory.json")["duration_sec"]/60},
    },
    "split_groups": prep["split_result"]["split_groups"],
    "imported_recordings": len(prep["audio_inventory"]), "asr_runs": len(smoke["runs"]),
    "asr_model": "small", "precision": "int8", "device": "cpu",
    "human_verified_annotations": 0, "research_gate": "NEEDS_MORE_DATA",
    "wer_improvement": None, "event_f1": None, "release_promoted": False,
    "remaining": [
        "Review segment scope/language and align publisher scripts to actual audio",
        "Resolve 13 C files' parent linkage without excluding difficult noise from the benchmark",
        "Obtain independent human entity/event/salience/temporal labels",
        "Acquire sufficient independent final-test groups; reserved BLeRIOT test has only 3",
        "Verify lawful recorded-human RU/mixed sources before claiming those languages' quality",
    ],
    "evidence_sha256": {name: file_hash(root/name) for name in (
        "bleriot-acquisition.json", "bleriot-preparation.json", "bleriot-asr-smoke.json", "voici-acquisition.json"
    )},
}
atomic_json(root / "data-resumption.json", report)
print(json.dumps({"verification": report["verification"], "checks": checks,
                  "research_gate": report["research_gate"]}))
if not all(checks.values()):
    raise SystemExit(1)
