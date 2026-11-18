"""Audit the 476 windows and recheck language-only train rejects with medium.en.

The second recognizer sees audio only. Publisher targets remain byte-for-byte
unchanged, unverified and exploratory; this is not a cockpit quality benchmark.
"""

import argparse
import json
import math
import statistics
import time
from collections import Counter
from pathlib import Path

from north55_speech.core import atomic_json, file_hash
from north55_speech.metrics import edit_counts, lexical_normalizer_v1
from scripts.publisher_alignment import number_tokens

LANGUAGE_REASON = "non_English_or_uncertain_detected_language"
MODEL = "whisper-medium-en-ct2"
POLICY = {
    "version": "publisher_language_recheck_v1",
    "train_only": True,
    "original_reasons": [LANGUAGE_REASON],
    "maximum_lexical_disagreement": 0.15,
    "minimum_median_word_probability": 0.6,
    "minimum_reference_words": 8,
    "require_exact_numeric_sequence": True,
    "require_exact_negation_sequence": True,
    "publisher_text_modified": False,
    "human_verified": False,
    "language_verified": False,
    "quality_evidence": False,
    "training_steps": 0,
}


def read(path):
    return json.loads(path.read_bytes())


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def selected(row):
    return (row["split"] == "train"
            and row["annotation_provenance"]["eligibility_reasons"] == [LANGUAGE_REASON])


def negations(text):
    return [w for w in lexical_normalizer_v1(text).split()
            if w in {"no", "not", "never", "without", "cannot", "unable", "negative"}
            or w.endswith("n't")]


def assess(target, prediction, duration):
    reasons = []
    if prediction.get("error"):
        return {"accepted": False, "reasons": ["runtime_failure"]}
    hypothesis = prediction["hypothesis"]
    counts = edit_counts(target, hypothesis)
    disagreement = (counts["S"] + counts["D"] + counts["I"]) / max(1, counts["N"])
    if counts["N"] < POLICY["minimum_reference_words"]:
        reasons.append("insufficient_reference_words")
    if disagreement > POLICY["maximum_lexical_disagreement"]:
        reasons.append("second_model_lexical_disagreement")
    if number_tokens(target) != number_tokens(hypothesis):
        reasons.append("numeric_disagreement")
    if negations(target) != negations(hypothesis):
        reasons.append("negation_disagreement")
    words = [w for s in prediction["segments"] for w in s["words"]]
    probabilities = [w["probability"] for w in words if w["probability"] is not None]
    median = statistics.median(probabilities) if probabilities else 0.0
    if not math.isfinite(median) or median < POLICY["minimum_median_word_probability"]:
        reasons.append("low_second_model_score")
    if not words or any(not (math.isfinite(w["start_sec"]) and math.isfinite(w["end_sec"])
                             and 0 <= w["start_sec"] <= w["end_sec"] <= duration + 0.05)
                        for w in words):
        reasons.append("invalid_word_timeline")
    return {"accepted": not reasons, "reasons": reasons, "lexical_disagreement": disagreement,
            "median_word_probability": median, "counts": counts}


def prepare(old, out):
    from north55_speech.asr import local_model_manifest

    if (out / "inference/plan.json").exists():
        raise ValueError("Use a new preparation version; the current plan is frozen")
    report = read(old / "preparation-report.json")
    sources = rows(old / "all/train.jsonl")
    candidates = [r for r in sources if selected(r)]
    assert report["total_rows"] == 476 and len(candidates) == 91
    inputs = [{"id": r["sample_id"], "audio_path": r["audio_path"],
               "audio_sha256": r["audio_sha256"], "duration_sec": r["duration_sec"]} for r in candidates]
    atomic_json(out / "inference/inputs.json", inputs)
    source_files = ["preparation-report.json", "all/train.jsonl", "all/dev.jsonl",
                    "training/train.jsonl", "training/dev.jsonl", "plan.json"]
    sources_sha = {p: file_hash(old / p) for p in source_files}
    for r in candidates:
        # Variants share the clean parent's original alignment evidence.
        name = r["variant_of"] or r["sample_id"]
        path = f"proposals/{name}.json"
        sources_sha[path] = file_hash(old / path)
        if sources_sha[path] != r["annotation_provenance"]["alignment_sha256"]:
            raise ValueError("Original alignment hash changed")
    plan = {"policy": POLICY, "model": MODEL, "model_manifest": local_model_manifest(MODEL),
            "script_sha256": file_hash(Path(__file__)), "source_sha256": sources_sha,
            "inputs_sha256": file_hash(out / "inference/inputs.json"), "count": len(inputs)}
    atomic_json(out / "inference/plan.json", plan)
    items = report["items"]
    audit = {"total_windows": len(items), "old_train": report["eligible_train"],
             "old_dev": report["eligible_dev"],
             "overlapping_reasons": dict(Counter(r for i in items for r in i["reasons"])),
             "exclusive_reason_combinations": dict(Counter(" + ".join(i["reasons"]) or "accepted" for i in items)),
             "language_only_by_split": dict(Counter(i["split"] for i in items if i["reasons"] == [LANGUAGE_REASON])),
             "old_candidates_human_verified": False, "new_policy": POLICY}
    atomic_json(out / "audit.json", audit)
    print(json.dumps(audit, ensure_ascii=False, indent=2))


def infer(study, predictions):
    import soundfile as sf

    from north55_speech.asr import AsrProvider
    from north55_speech.core import settings
    from north55_speech.schemas import PipelineConfig

    plan, plan_sha = read(study / "plan.json"), file_hash(study / "plan.json")
    if plan["policy"] != POLICY or file_hash(Path(__file__)) != plan["script_sha256"]:
        raise ValueError("Frozen inference code/policy changed")
    if file_hash(study / "inputs.json") != plan["inputs_sha256"]:
        raise ValueError("Frozen inputs changed")
    inputs = read(study / "inputs.json")
    execution_path = predictions / "execution.json"
    if execution_path.exists():
        previous = read(execution_path)
        if previous["plan_sha256"] != plan_sha or set(previous["predictions"]) != {i["id"] for i in inputs}:
            raise ValueError("Completed execution identity changed")
        for key, sha in previous["predictions"].items():
            if file_hash(predictions / f"{key}.json") != sha:
                raise ValueError("Completed prediction changed")
        print("Complete inference verified; no new calls")
        return
    provider = AsrProvider(PipelineConfig(model=MODEL, device="cuda", compute_type="float16"))
    if provider.manifest != plan["model_manifest"]:
        raise ValueError("Model manifest changed")
    hashes, failures, new = {}, [], 0
    start = time.perf_counter()
    for index, item in enumerate(inputs):
        path = predictions / f"{item['id']}.json"
        if path.exists():
            prediction = read(path)
            if prediction["plan_sha256"] != plan_sha or prediction["audio_sha256"] != item["audio_sha256"]:
                raise ValueError("Resumed prediction identity mismatch")
        else:
            audio_path = settings.audio_root / item["audio_path"]
            if file_hash(audio_path) != item["audio_sha256"]:
                raise ValueError("Audio checksum mismatch")
            audio, rate = sf.read(audio_path, dtype="float32")
            if rate != 16000 or audio.ndim != 1 or abs(len(audio) / rate - item["duration_sec"]) > 0.001:
                raise ValueError("Audio contract mismatch")
            prediction = {"id": item["id"], "plan_sha256": plan_sha,
                          "audio_sha256": item["audio_sha256"], "options": provider.options("en"),
                          "hypothesis": "", "segments": [], "error": None}
            try:
                segments = provider.transcribe(audio, 0.0, "en", item["id"], lambda: None)
                prediction.update(hypothesis=" ".join(s.raw_asr_text.strip() for s in segments),
                                  segments=[s.model_dump(mode="json") for s in segments])
            except Exception as exc:
                prediction["error"] = f"{type(exc).__name__}: {exc}"
            atomic_json(path, prediction)
            new += 1
        if prediction["error"]:
            failures.append(item["id"])
        hashes[item["id"]] = file_hash(path)
        if (index + 1) % 10 == 0:
            print(json.dumps({"completed": index + 1, "total": len(inputs)}), flush=True)
    atomic_json(execution_path, {"plan_sha256": plan_sha, "predictions": hashes, "new_asr_calls": new,
                "failures": failures, "seconds": time.perf_counter() - start,
                "device": provider.model.model.device, "precision": provider.model.model.compute_type})


def assemble(old, out, dataset):
    from north55_speech.datasets import Sample, load_manifest, validate_groups, write_manifest
    from north55_speech.lora import validate_references

    plan_path = out / "inference/plan.json"
    plan, plan_sha = read(plan_path), file_hash(plan_path)
    if plan["policy"] != POLICY or file_hash(Path(__file__)) != plan["script_sha256"]:
        raise ValueError("Frozen selection code/policy changed")
    for path, sha in plan["source_sha256"].items():
        if file_hash(old / path) != sha:
            raise ValueError("Original evidence changed")
    execution = read(out / "predictions/execution.json")
    inputs = read(out / "inference/inputs.json")
    if execution["plan_sha256"] != plan_sha or set(execution["predictions"]) != {i["id"] for i in inputs}:
        raise ValueError("Incomplete inference")
    source = {r["sample_id"]: r for r in rows(old / "all/train.jsonl")}
    added, decisions = [], []
    for item in inputs:
        row = source[item["id"]]
        if not selected(row):
            raise ValueError("A non-training or non-language-only row entered recovery")
        path = out / "predictions" / f"{item['id']}.json"
        if file_hash(path) != execution["predictions"][item["id"]]:
            raise ValueError("Prediction hash mismatch")
        prediction = read(path)
        decision = {"id": item["id"], **assess(row["reference_text"], prediction, item["duration_sec"])}
        decisions.append(decision)
        if decision["accepted"]:
            row["annotation_provenance"] = {**row["annotation_provenance"],
                "automatic_training_eligible": True, "eligibility_reasons": [],
                "previous_eligibility_reasons": [LANGUAGE_REASON],
                "selection_method": POLICY["version"], "selection_plan_sha256": plan_sha,
                "second_model_prediction_sha256": file_hash(path), "second_model_assessment": decision,
                "language_basis": "English publisher text with second-model agreement; original auto language disputed; not human verified"}
            added.append(Sample.model_validate(row))
    old_train = load_manifest(old / "training/train.jsonl")
    present = {s.sample_id for s in old_train + added}
    unsupported_variants = {s.sample_id for s in added if s.variant_of and s.variant_of not in present}
    for decision in decisions:
        if decision["id"] in unsupported_variants:
            decision["accepted"] = False
            decision["reasons"].append("clean_parent_not_admitted")
    added = [s for s in added if s.sample_id not in unsupported_variants]
    train = old_train + added
    dev = load_manifest(old / "training/dev.jsonl")
    if len({s.sample_id for s in train}) != len(train):
        raise ValueError("Duplicate recovery")
    for row in train:
        row.group_id = None
    validate_groups(train)
    groups = validate_groups([s.model_copy(deep=True, update={"group_id": None}) for s in train + dev])
    validate_references(train, dev, {"reference_policy": "publisher_weak_exploratory_v1",
                        "quality_evidence": False, "selection_allowed": False, "max_steps": 40})
    dataset.mkdir(parents=True, exist_ok=True)
    train_path, dev_path = dataset / "train.jsonl", dataset / "dev.jsonl"
    if train_path.exists() or dev_path.exists():
        raise ValueError("Preserve existing dataset version")
    write_manifest(train_path, train)
    dev_path.write_bytes((old / "training/dev.jsonl").read_bytes())
    atomic_json(out / "decisions.json", decisions)
    result = {"status": "READY_WEAK_TRAINING_PAIRS" if added else "NO_NEW_PAIRS",
              "old_train_pairs": len(train) - len(added), "checked_language_only_train": len(inputs),
              "added_pairs": len(added), "new_train_pairs": len(train),
              "added_minutes": sum(s.duration_sec for s in added) / 60,
              "total_train_minutes": sum(s.duration_sec for s in train) / 60,
              "added_clean": sum(s.variant_of is None for s in added),
              "added_noisy": sum(s.variant_of is not None for s in added),
              "new_train_speakers": len({v for s in train for v in s.speaker_ids}),
              "groups": groups, "source_preservation": True,
              "unchanged_dev_pairs": len(dev), "dev_byte_identical": file_hash(dev_path) == file_hash(old / "training/dev.jsonl"),
              "train_sha256": file_hash(train_path), "dev_sha256": file_hash(dev_path),
              "selection_plan_sha256": plan_sha, "training_loader_contract": "PASS",
              "human_verified_added": 0, "new_training_steps": 0, "new_test_access": False,
              "quality_improvement": "NOT_MEASURED", "rejection_reasons": dict(Counter(r for d in decisions for r in d["reasons"]))}
    atomic_json(out / "result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "infer", "assemble"))
    parser.add_argument("--old", type=Path, default=Path("/old"))
    parser.add_argument("--out", type=Path, default=Path("/output"))
    parser.add_argument("--study", type=Path, default=Path("/study"))
    parser.add_argument("--predictions", type=Path, default=Path("/predictions"))
    parser.add_argument("--dataset", type=Path, default=Path("/dataset"))
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.old, args.out)
    elif args.stage == "infer":
        infer(args.study, args.predictions)
    else:
        assemble(args.old, args.out, args.dataset)


if __name__ == "__main__":
    main()
