"""Verify recorded NUS acquisition/inspection evidence, not an ASR quality PASS."""

import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path("reports/nus-vr-v1")
PROTECTED = {
    "SPEC.md": "9191d785add8109b4a3edd75171fab81987aac5df34036cb34daecbbe4de644f",
    "SOURCES.md": "74e70ac86c48d423f9a3da3d3d6bd8a13ee32cab6e537502ba0f12c3a939f114",
    "ACCEPTANCE.yaml": "32d35b1e80b64f38e6adcc9895515b37f224a9e51dcf5ff95389e1f9ecc45071",
    "configs/baseline.yaml": "419accafb0874a51c11bd4865117a4daf761345a48242e36269c71e88a73e1d1",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    return json.loads((ROOT / name).read_bytes())


def main():
    checks = []

    def check(name, condition):
        checks.append({"name": name, "status": "PASS" if condition else "FAIL"})

    acquisition = read("acquisition.json")
    report = read("inspection-final.json")
    replay = read("inspection-linux-replay.json")
    check("all_ten_files_acquired", len(acquisition["files"]) == 10
          and acquisition["total_bytes"] == 34631443)
    for row in acquisition["files"]:
        path = Path(row["local_path"].replace("\\", "/"))
        body = path.read_bytes()
        blob = hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()
        check(f"payload_integrity:{path.name}", len(body) == row["bytes"]
              and hashlib.sha256(body).hexdigest() == row["sha256"] and blob == row["git_blob"])
    for folder in ("metadata", "preparation-metadata"):
        retrieval = read(f"{folder}/retrieval.json")
        check(f"metadata_integrity:{folder}", all(row["status"] == 200 and
              sha(ROOT / folder / f"{row['id']}.response") == row["sha256"]
              for row in retrieval["records"]))
    check("all_642_rows_decoded", report["decoded_rows"] == report["row_count"] == 642
          and report["decode_status"] == "PASS" and not report["failures"])
    check("313_unique_audio_clips", report["duplicates"]["unique_pcm_clips"] == 313
          and report["duplicates"]["duplicate_rows"] == 329)
    check("eleven_reference_conflicts_preserved",
          len(report["duplicates"]["conflicting_reference_audio_groups"]) == 11)
    check("missing_origin_times_not_fabricated",
          report["missing_or_invalid_source_interval_rows"] == 642)
    check("actual_clip_duration_matches_source", report["duration_mismatch_over_20ms"] == 0
          and report["missing_declared_duration_rows"] == 0)
    check("one_conservative_group_no_fake_holdout", report["provisional_leakage_groups"] == 1
          and not report["train_dev_test_split_created"] and not report["final_test_eligible"])
    check("no_unlicensed_training_or_promotion", report["rights"]["status"] == "BLOCKED"
          and not report["training_executed"] and not report["asr_inference_executed"]
          and not report["candidate_promoted"])
    check("no_invented_quality_metrics", report["wer"] is None and report["nlp_f1"] is None
          and report["project_quality_gate"] == "NEEDS_MORE_DATA")
    check("final_script_matches_executed_hash",
          report["script_sha256"] == sha(Path("scripts/inspect_nus_vr.py")))
    check("source_acquisition_audit_matches", report["acquisition_sha256"] == sha(ROOT / "acquisition.json"))
    check("private_index_integrity", report["private_index_sha256"] == sha(
        Path("data/quarantine/nus-vr-v1/inspection-index-final.json")))
    def comparable(value):
        return {key: item for key, item in value.items() if key not in {"checked_at", "runtime"}}

    check("powershell_linux_replay_same_measurements", comparable(report) == comparable(replay))
    check("replay_same_library_versions", all(report["runtime"][key] == replay["runtime"][key]
                                             for key in ("python", "pyarrow", "numpy", "soundfile")))
    for filename, expected in PROTECTED.items():
        check(f"protected_unchanged:{filename}", sha(Path(filename)) == expected)
    suites = ET.parse(ROOT / "unit-tests.xml").getroot().iter("testsuite")
    suites = list(suites)
    check("seven_unit_tests_passed", sum(int(s.attrib["tests"]) for s in suites) == 7 and
          all(int(s.attrib.get(key, 0)) == 0 for s in suites for key in ("errors", "failures", "skipped")))
    ignored = subprocess.run(["git", "check-ignore", "data/quarantine/nus-vr-v1/Sample01.parquet",
                              "data/quarantine/nus-vr-v1/inspection-index-final.json"],
                             text=True, capture_output=True, check=False)
    check("payload_and_references_excluded_from_git", ignored.returncode == 0
          and len(ignored.stdout.splitlines()) == 2)
    result = {"checked_at": datetime.now(UTC).isoformat(), "checks": checks,
              "verification_status": "PASS" if all(row["status"] == "PASS" for row in checks) else "FAIL",
              "verified_scope": "acquisition_and_offline_inspection_only",
              "training_admission": "BLOCKED", "project_quality_gate": "NEEDS_MORE_DATA"}
    (ROOT / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if result["verification_status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
