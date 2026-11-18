"""Verify the executed publisher experiment; never infer a scientific PASS."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from north55_speech.benchmark import code_hash, scorer_hash
from north55_speech.core import atomic_json, file_hash, now
from north55_speech.datasets import load_manifest
from north55_speech.lora import validate_references
from north55_speech.metrics import corpus_counts, edit_counts
from north55_speech.training import check_training_partitions


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    root = Path("/reports/publisher-weak-v1")
    publisher = Path("/publisher")
    app = Path("/app")
    models = Path("/models")
    checks = {}

    def check(name, value):
        checks[name] = bool(value)

    train = load_manifest(publisher / "training/train.jsonl")
    dev = load_manifest(publisher / "training/dev.jsonl")
    all_train = load_manifest(publisher / "all/train.jsonl")
    all_dev = load_manifest(publisher / "all/dev.jsonl")
    preparation = read(publisher / "preparation-report.json")
    plan = read(publisher / "plan.json")
    training = read(root / "training-manifest.json")
    comparison = read(root / "comparison.json")
    comparison_plan = read(root / "comparison-plan.json")
    history = read(root / "training-history.json")
    check_training_partitions(all_train, all_dev)
    check("weak_admission_and_disjoint_partitions", validate_references(train, dev, training["config"]) == "publisher_weak_exploratory_v1")
    check("prepared_counts", (len(all_train), len(all_dev), len(train), len(dev)) == (52, 24, 17, 7)
          and preparation["total_rows"] == 76)
    check("no_human_or_event_labels_created", all(
        s.transcript_status in {"weak", "missing"} and not s.primary and not s.scope_verified
        and not s.annotation_provenance["reviewed_audio"] and not s.labels and not s.events
        for s in all_train + all_dev))
    check("preparation_plan_and_code", file_hash(publisher / "plan.json") == preparation["plan_sha256"]
          and all(file_hash(app / "scripts" / name) == sha for name, sha in plan["code"].items())
          and all(file_hash(publisher / "documents" / f"{name}.json") == sha for name, sha in plan["documents"].items()))
    check("original_train_dev_hashes", all(file_hash(Path("/train-dev") / f"{split}.jsonl") == sha
          for split, sha in plan["manifests"].items()))
    check("training_data_hashes", all(file_hash(publisher / "training" / f"{split}.jsonl") == training[f"{split}_sha256"]
          for split in ("train", "dev")))
    check("executed_lora_source_snapshot", file_hash(root / "lora-executed.py") == read(root / "experiment-code.json")["lora_code_sha256"])
    executed_source = (root / "lora-executed.py").read_text()
    typed_source = executed_source.replace("from pathlib import Path\n", "from pathlib import Path\nfrom typing import Any\n")
    typed_source = typed_source.replace("    processor = WhisperProcessor", "    processor: Any = WhisperProcessor")
    typed_source = typed_source.replace("    model = WhisperForConditionalGeneration", "    model: Any = WhisperForConditionalGeneration")
    check("post_run_only_dynamic_type_annotations", (app / "src/north55_speech/lora.py").read_text() == typed_source)
    check("training_finished_40_steps", max(row["step"] for row in history) == 40
          and training["config"]["max_steps"] == 40 and training["train_metrics"]["epoch"] == 8
          and training["train_metrics"]["train_runtime"] > 0 and training["converted_inference"] == "executed")
    adapted_root = models / training["config"]["output"]
    check("training_artifact_checksums", read(adapted_root / "manifest.json") == training
          and all(file_hash(adapted_root / name) == sha for name, sha in training["files"].items()))
    converted = training["converted_model"]
    check("converted_artifact_checksums", read(models / converted["model"] / "manifest.json") == converted
          and all(file_hash(models / converted["model"] / name) == sha for name, sha in converted["files"].items()))
    base = models / "whisper-small-transformers"
    parent_root = models / comparison_plan["parent_model"]
    parent = read(parent_root / "manifest.json")
    check("same_base_checkpoint", file_hash(base / "manifest.json") == comparison_plan["base_source_sha256"]
          == parent["source_manifest_sha256"] and read(base / "manifest.json") == training["base_manifest"]
          and all(file_hash(parent_root / name) == sha for name, sha in parent["files"].items())
          and all(file_hash(base / name) == sha for name, sha in training["base_manifest"]["files"].items()))
    check("comparison_plan_and_code", file_hash(root / "comparison-plan.json") == comparison["plan_sha256"]
          and file_hash(app / "scripts/evaluate_publisher_lora.py") == comparison_plan["script_sha256"]
          and file_hash(adapted_root / "manifest.json") == comparison_plan["adaptation_sha256"]
          and file_hash(publisher / "all/dev.jsonl") == comparison_plan["dev_sha256"])
    config = comparison_plan["inference_config"]
    check("same_decoding_no_hints", config["device"] == "cuda" and config["compute_type"] == "float16"
          and config["beam_size"] == 5 and config["temperature"] == 0 and config["hotwords"] is None
          and not config["vad"]["enabled"] and not config["denoise"]["enabled"] and not config["redecode"])
    controls_path = Path("/audio/smoke/provenance.json")
    check("control_provenance", file_hash(controls_path) == comparison_plan["controls_sha256"])
    refs = {s.sample_id: s.reference_text if s.annotation_provenance["automatic_training_eligible"] else None for s in all_dev}
    refs.update({s["sample_id"]: s["reference_text"] for s in read(controls_path)["samples"]})
    predictions_ok, scores_ok = True, True
    for row in comparison["rows"]:
        record = read(root / "comparison-predictions" / f"{row['system']}-{row['id']}.json")
        predictions_ok &= record == {k: v for k, v in row.items() if k != "score"}
        predictions_ok &= file_hash(Path("/audio") / row["audio_path"]) == row["audio_sha256"]
        reference = refs[row["id"]]
        scores_ok &= row["score"] == (edit_counts(reference, row["hypothesis"]) if reference is not None else None)
    expected_pairs = {(system, item["id"]) for system in ("parent", "adapted") for item in comparison_plan["items"]}
    check("all_52_predictions_retained", predictions_ok and len(comparison["rows"]) == len(expected_pairs) == 52
          and {(r["system"], r["id"]) for r in comparison["rows"]} == expected_pairs
          and comparison["runtime_failures"] == 0 and all(r["runtime_failure"] is None for r in comparison["rows"]))
    check("edit_counts_recomputed", scores_ok and all(
        corpus_counts([r["score"] for r in comparison["rows"] if r["cohort"] == cohort and r["system"] == system and r["score"] is not None]) == values
        for cohort, systems in comparison["comparison"].items() for system, values in systems.items()))
    cpu = read(root / "adapted-cpu-smoke.json")
    check("adapted_real_cpu_offline", cpu["status"] == "PASS" and cpu["network"] == "none"
          and cpu["device"] == "cpu" and cpu["compute_type"] == "int8" and cpu["model_manifest"] == converted
          and bool(cpu["segments"]))
    cases = ET.parse(root / "all-tests.xml").findall(".//testcase")
    check("243_tests_9_integration", len(cases) == 243 and sum("integration" in c.attrib["classname"] for c in cases) == 9
          and not any(c.find(tag) is not None for c in cases for tag in ("failure", "error", "skipped")))
    check("static_and_compose", all(v["exit_code"] == 0 for v in read(root / "command-checks.json").values()))
    annotation = read(root / "annotation-service.json")
    check("annotation_manifests_preserved", annotation["status"] == "PASS" and annotation["annotation_writes"] == 0
          and all(file_hash(Path("/annotation") / f"{split}.jsonl") == value["sha256"] for split, value in annotation["exports"].items()))
    check("requirements_unchanged", all(file_hash(app / name) == sha for name, sha in {
        "SPEC.md": "9191d785add8109b4a3edd75171fab81987aac5df34036cb34daecbbe4de644f",
        "ACCEPTANCE.yaml": "32d35b1e80b64f38e6adcc9895515b37f224a9e51dcf5ff95389e1f9ecc45071",
        "SOURCES.md": "74e70ac86c48d423f9a3da3d3d6bd8a13ee32cab6e537502ba0f12c3a939f114",
    }.items()))
    check("no_selection_test_or_quality_claim", all(x["test_accessed"] is False for x in (plan, comparison_plan, comparison))
          and comparison["candidate_selected"] is False and comparison["release_promoted"] is False
          and training["quality_evidence"] is False and training["selection_allowed"] is False)
    result = {
        "created_at": now(), "experiment_verification": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
        "implemented": ["publisher document columns and local alignment", "explicit weak-reference LoRA policy", "annotation proposals", "offline adapted inference and measured comparison"],
        "executed": {"training_optimizer_steps": 40, "train_clips": len(train), "dev_clips": len(dev), "comparison_inferences": len(comparison["rows"]), "tests": len(cases)},
        "independent_groups": {"train_eligible": len({s.group_id for s in train}), "dev_eligible": len({s.group_id for s in dev})},
        "code_hash": code_hash(), "scorer_hash": scorer_hash(),
        "executed_lora_sha256": file_hash(root / "lora-executed.py"),
        "packaged_lora_sha256": file_hash(app / "src/north55_speech/lora.py"),
        "post_run_amendment": "Only Any annotations for dynamic Transformers/PEFT objects; exact source transformation checked. Training not rerun.",
        "ASR_QUALITY_GATE": "NEEDS_MORE_DATA", "statistical_confirmation": "INCONCLUSIVE",
        "critical_entity_quality": "NOT_MEASURED", "NLP_QUALITY_GATE": "NEEDS_MORE_DATA", "TEMPORAL_EVENT_GATE": "NEEDS_MORE_DATA",
        "release_promoted": False, "validated_language_scope": [], "human_labels_created": False,
        "comparison": comparison["comparison"],
        "limitations": ["Dev transcripts are automatically aligned publisher scripts, not independent audio gold.", "Three dev groups and repeated scripts cannot establish the required effect.", "Two general controls from one reader are below the clean-control acceptance minimum.", "No independent critical entity, event, salience or temporal labels.", "A5 adapted checkpoint is distinct from same-checkpoint A0-A4 pipeline experiments."],
        "prior_engineering_evidence": {"report": "reports/reporting-v1/verification.json", "sha256": file_hash(Path("/reports/reporting-v1/verification.json")), "recovery_rerun_in_this_experiment": False},
        "artifact_sha256": {p.name: file_hash(p) for p in sorted(root.iterdir()) if p.is_file() and not p.name.startswith("verification") and p.name not in {"report.html", "report.md"}},
    }
    atomic_json(root / "verification.json", result)
    print(json.dumps({k: v for k, v in result.items() if k in {"experiment_verification", "checks", "executed", "ASR_QUALITY_GATE"}}, indent=2))
    if not all(checks.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
