"""Prepare, independently redecode, and export publisher-template recovery v3."""

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from north55_speech.core import atomic_json, digest, file_hash
from scripts.expand_publisher_pairs import FAMILIES
from scripts.publisher_recovery_rules_v3 import (
    POLICY,
    fresh_reasons,
    ordered_nonoverlap,
    propose_subphrases,
    whole_support,
)

MODELS = {"medium": "whisper-medium-en-ct2", "large": "whisper-large-v3-systran-ct2"}
OUT = Path("/output")
ROOT = Path("/workspace")


def read(path):
    return json.loads(path.read_bytes())


def identity():
    names = ["scripts/recover_publisher_v3.py", "scripts/publisher_recovery_rules_v3.py",
        "scripts/audit_bleriot_remaining.py", "scripts/expand_publisher_pairs.py", "scripts/build_publisher_pairs.py",
        "scripts/publisher_phrase_support.py", "scripts/publisher_alignment.py", "configs/publisher_slots_v3.json",
        "src/north55_speech/asr.py", "src/north55_speech/schemas.py", "src/north55_speech/metrics.py"]
    return {name: file_hash(Path("/code") / name) for name in names}


def prepare():
    import soundfile as sf

    from north55_speech.asr import local_model_manifest
    from north55_speech.core import settings

    if (OUT / "inference/plan.json").exists():
        raise ValueError("Preserve the frozen preparation")
    old = ROOT / "reports/publisher-phrases-v2"
    prior = ROOT / "data/curated/pair-quality-v1"
    decisions = {d["id"]: d for d in read(old / "decisions.json")}
    items = read(prior / "plan.json")["items"]
    small_execution, medium_execution = read(prior / "small/execution.json"), read(old / "predictions/execution.json")
    documents = read(old / "scoring/documents.json")
    slots = read(Path("/code/configs/publisher_slots_v3.json"))
    if slots["source_sha256"] != documents[slots["document"]]["source_sha256"]:
        raise ValueError("Template PDF identity changed")
    texts = {name: "\n".join(line["text"] for line in doc["lines"] if not line.get("excluded_layout"))
             for name, doc in documents.items()}
    proposed, input_rows, generation = [], [], []
    only_document = {"insufficient_publisher_support", "critical_token_not_supported_by_publisher"}
    for item in items:
        d = decisions[item["id"]]
        if d["accepted"]:
            continue  # Carry the prior 96 pairs; do not create overlapping new training clips.
        sp = prior / "small/predictions" / f"{item['id']}.json"
        mp = old / "predictions" / f"{item['id']}.json"
        if file_hash(sp) != small_execution["prediction_sha256"][sp.name] or file_hash(mp) != medium_execution["predictions"][item["id"]]:
            raise ValueError("Cached ASR evidence changed")
        small, medium = read(sp), read(mp)
        relevant = {n+".json": texts[n+".json"] for n in FAMILIES[item["family"]]}
        candidates = propose_subphrases(small, medium, relevant, slots, item["duration_sec"])
        # Bound candidate count using duration and publisher order before new ASR.
        candidates = ordered_nonoverlap(candidates)
        if d["reasons"] and set(d["reasons"]) <= only_document:
            p = whole_support(d["target"], relevant)
            if p["coverage"] >= .9 and p["critical_supported"]:
                candidates.append({"kind": "whole_alias", "start_sec": 0, "end_sec": item["duration_sec"],
                    "target": d["target"], "small_target": small["hypothesis"],
                    "publisher": {**p, "mode": "alias_whole", "start_token": p["span"][0]}})
        generation.append({"parent_id": item["id"], "candidates": len(candidates), "old_reasons": d["reasons"]})
        if not candidates:
            continue
        source_path = settings.audio_root / item["audio_path"]
        if file_hash(source_path) != item["audio_sha256"]:
            raise ValueError("Original pause clip changed")
        waveform, rate = sf.read(source_path, dtype="float32")
        if rate != 16000 or waveform.ndim != 1:
            raise ValueError("Unexpected source audio format")
        seen = set()
        for c in candidates:
            start, end = round(c["start_sec"]*rate), round(c["end_sec"]*rate)
            key = (start, end, c["target"])
            if key in seen:
                continue
            seen.add(key)
            sample_id = digest({"version": POLICY["version"], "parent": item["id"], "samples": [start, end], "target": c["target"]})[:32]
            path = settings.audio_root / "publisher-recovery-v3" / (sample_id+".wav")
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                raise ValueError("Do not overwrite an existing derived audio clip")
            sf.write(path, waveform[start:end], rate, subtype="FLOAT")
            row = {**c, "id": sample_id, "parent_id": item["id"], "source": item["source"],
                "audio_path": str(path.relative_to(settings.audio_root)), "audio_sha256": file_hash(path),
                "duration_sec": (end-start)/rate, "start_sec": start/rate, "end_sec": end/rate,
                "original_start_sec": item["original_start_sec"]+start/rate,
                "original_end_sec": item["original_start_sec"]+end/rate,
                "small_prediction_sha256": file_hash(sp), "medium_prediction_sha256": file_hash(mp),
                "parent_audio_sha256": item["audio_sha256"], "parent_medium_target": medium["hypothesis"]}
            proposed.append(row)
            input_rows.append({k: row[k] for k in ("id", "audio_path", "audio_sha256", "duration_sec")})
        if len(generation) % 100 == 0:
            print(json.dumps({"parents_examined": len(generation), "proposed": len(proposed)}), flush=True)
    atomic_json(OUT / "scoring/candidates.json", proposed)
    atomic_json(OUT / "scoring/generation.json", generation)
    atomic_json(OUT / "scoring/documents.json", documents)
    atomic_json(OUT / "scoring/sources.json", read(prior / "sources.json"))
    atomic_json(OUT / "inference/inputs.json", input_rows)
    frozen = {"policy": POLICY, "models": {k: {"id": v, "manifest": local_model_manifest(v)} for k, v in MODELS.items()},
        "code_sha256": identity(), "candidates_sha256": file_hash(OUT / "scoring/candidates.json"),
        "inputs_sha256": file_hash(OUT / "inference/inputs.json"), "documents_sha256": file_hash(OUT / "scoring/documents.json"),
        "sources_sha256": file_hash(OUT / "scoring/sources.json"),
        "old_train_sha256": file_hash(ROOT / "data/curated/publisher-phrases-v2/train.jsonl"),
        "old_dev_sha256": file_hash(ROOT / "data/curated/publisher-phrases-v2/dev.jsonl"),
        "old_49_train_sha256": file_hash(ROOT / "data/curated/publisher-recovery-v1/train.jsonl"),
        "previous_decisions_sha256": file_hash(old / "decisions.json"),
        "candidates": len(proposed), "asr_calls_planned": len(proposed)*len(MODELS),
        "test_accessed": False, "dev_used_for_selection": False, "training_steps": 0}
    atomic_json(OUT / "inference/plan.json", frozen)
    summary = {"candidates": len(proposed), "kind_counts": dict(Counter(c["publisher"]["mode"] for c in proposed)),
        "parent_clips": len({c["parent_id"] for c in proposed}), "asr_calls_planned": frozen["asr_calls_planned"]}
    atomic_json(OUT / "preparation.json", summary)
    print(json.dumps(summary, indent=2))


def infer(system):
    import soundfile as sf

    from north55_speech.asr import AsrProvider
    from north55_speech.core import settings
    from north55_speech.schemas import PipelineConfig

    study, predictions = Path("/study"), Path("/predictions") / system
    plan_path = study / "plan.json"
    plan, plan_sha = read(plan_path), file_hash(plan_path)
    if identity() != plan["code_sha256"] or POLICY != plan["policy"] or file_hash(study / "inputs.json") != plan["inputs_sha256"]:
        raise ValueError("Frozen code, inputs, or policy changed")
    items = read(study / "inputs.json")
    execution_path = predictions / "execution.json"
    if execution_path.exists():
        execution = read(execution_path)
        if execution["plan_sha256"] != plan_sha or set(execution["predictions"]) != {i["id"] for i in items}:
            raise ValueError("Completed execution identity mismatch")
        for key, sha in execution["predictions"].items():
            if file_hash(predictions / (key+".json")) != sha:
                raise ValueError("Completed prediction changed")
        print(system+": completed inference verified, no new ASR calls")
        return
    provider = AsrProvider(PipelineConfig(model=MODELS[system], device="cuda", compute_type="float16",
                                          condition_on_previous_text=False))
    if provider.manifest != plan["models"][system]["manifest"]:
        raise ValueError("Model manifest changed")
    begun, hashes, errors, calls = time.perf_counter(), {}, [], 0
    for index, item in enumerate(items):
        path = predictions / (item["id"]+".json")
        if path.exists():
            p = read(path)
            if p["plan_sha256"] != plan_sha or p["audio_sha256"] != item["audio_sha256"]:
                raise ValueError("Resume prediction identity mismatch")
        else:
            audio_path = settings.audio_root / item["audio_path"]
            if file_hash(audio_path) != item["audio_sha256"]:
                raise ValueError("Derived audio changed")
            waveform, rate = sf.read(audio_path, dtype="float32")
            if rate != 16000 or waveform.ndim != 1 or abs(len(waveform)/rate-item["duration_sec"]) > .001:
                raise ValueError("Derived audio contract mismatch")
            p = {"id": item["id"], "audio_sha256": item["audio_sha256"], "plan_sha256": plan_sha,
                "system": system, "options": provider.options("en"), "hypothesis": "", "segments": [], "error": None}
            try:
                segments = provider.transcribe(waveform, 0, "en", item["id"], lambda: None)
                p.update(hypothesis=" ".join(s.raw_asr_text.strip() for s in segments),
                         segments=[s.model_dump(mode="json") for s in segments])
            except Exception as exc:
                p["error"] = f"{type(exc).__name__}: {exc}"
            atomic_json(path, p)
            calls += 1
        hashes[item["id"]] = file_hash(path)
        if p["error"]:
            errors.append(item["id"])
        if (index+1) % 25 == 0:
            print(json.dumps({"system": system, "completed": index+1, "total": len(items)}), flush=True)
    atomic_json(execution_path, {"plan_sha256": plan_sha, "predictions": hashes, "new_asr_calls": calls,
        "errors": errors, "seconds": time.perf_counter()-begun, "device": provider.model.model.device,
        "precision": provider.model.model.compute_type})


def assemble():
    from north55_speech.core import settings
    from north55_speech.datasets import (
        Sample,
        decoded_audio_hash,
        load_manifest,
        validate_groups,
        write_manifest,
    )
    from north55_speech.lora import validate_references

    plan_path = OUT / "inference/plan.json"
    plan, plan_sha = read(plan_path), file_hash(plan_path)
    if identity() != plan["code_sha256"]:
        raise ValueError("Selection implementation changed")
    for name in ("candidates", "documents", "sources"):
        if file_hash(OUT / "scoring" / (name+".json")) != plan[name+"_sha256"]:
            raise ValueError("Source scoring evidence changed")
    old_base = ROOT / "data/curated/publisher-phrases-v2"
    for name in ("train", "dev"):
        if file_hash(old_base / (name+".jsonl")) != plan["old_"+name+"_sha256"]:
            raise ValueError("Prior dataset changed")
    candidates = read(OUT / "scoring/candidates.json")
    sources, documents = read(OUT / "scoring/sources.json"), read(OUT / "scoring/documents.json")
    executions = {s: read(OUT / "predictions" / s / "execution.json") for s in MODELS}
    for e in executions.values():
        if e["plan_sha256"] != plan_sha or set(e["predictions"]) != {c["id"] for c in candidates}:
            raise ValueError("Incomplete recheck")
    decisions, passed = [], defaultdict(list)
    for c in candidates:
        predictions = {}
        for system, e in executions.items():
            path = OUT / "predictions" / system / (c["id"]+".json")
            if file_hash(path) != e["predictions"][c["id"]]:
                raise ValueError("Recheck response changed")
            predictions[system] = read(path)
        reasons = fresh_reasons(c, predictions["medium"], predictions["large"], c["duration_sec"])
        decisions.append({"id": c["id"], "parent_id": c["parent_id"], "accepted_recheck": not reasons, "reasons": reasons})
        if not reasons:
            passed[c["parent_id"]].append(c)
    selected = [c for group in passed.values() for c in ordered_nonoverlap(group)]
    train, dev = load_manifest(old_base / "train.jsonl"), load_manifest(old_base / "dev.jsonl")
    added = []
    for c in selected:
        parent, doc = sources[c["source"]], documents[c["publisher"]["document"]]
        path = settings.audio_root / c["audio_path"]
        if file_hash(path) != c["audio_sha256"]:
            raise ValueError("Selected clip changed")
        row = {**parent, "sample_id": c["id"], "audio_path": c["audio_path"], "audio_sha256": c["audio_sha256"],
            "decoded_audio_sha256": decoded_audio_hash([path]), "duration_sec": c["duration_sec"], "channel": 0,
            "original_utterance_id": parent["original_utterance_id"]+"@recovery-v3:"+c["id"], "variant_of": None,
            "group_id": None, "continuous_recording": False, "language": "en", "input_language": "en",
            "scope": "read_cockpit", "scope_verified": False, "primary": False, "transcript_status": "weak",
            "reference_text": c["target"], "annotation_provenance": {
                "method": POLICY["version"], "reviewed_audio": False, "annotator": None, "publisher_transcript": False,
                "publisher_supported": True, "automatic_training_eligible": True, "eligibility_reasons": [],
                "language_verified": False, "target_origin": "cached_medium_word_span_with_two_fresh_audio_rechecks",
                "source_file": doc["source_file"], "source_sha256": doc["source_sha256"],
                "document_bundle_sha256": plan["documents_sha256"], "selection_plan_sha256": plan_sha,
                "small_prediction_sha256": c["small_prediction_sha256"], "medium_prediction_sha256": c["medium_prediction_sha256"],
                "fresh_medium_sha256": executions["medium"]["predictions"][c["id"]],
                "fresh_large_sha256": executions["large"]["predictions"][c["id"]], "recheck_passed": True,
                "source_sample_id": c["source"], "parent_clip_id": c["parent_id"],
                "original_start_sec": c["original_start_sec"], "original_end_sec": c["original_end_sec"],
                "publisher_match": c["publisher"], "numeric_value_human_verified": False}}
        added.append(Sample.model_validate(row))
    # Preserve original v2 samples; validate grouping on copies to avoid mutating their records.
    train += added
    for s in train:
        s.group_id = None
    validate_groups(train)
    validate_references(train, dev, {"reference_policy": POLICY["version"], "quality_evidence": False, "selection_allowed": False})
    dataset = Path("/dataset")
    if (dataset / "train.jsonl").exists():
        raise ValueError("Do not overwrite a completed dataset")
    write_manifest(dataset / "train.jsonl", train)
    write_manifest(dataset / "added.jsonl", added)
    (dataset / "dev.jsonl").write_bytes((old_base / "dev.jsonl").read_bytes())
    atomic_json(OUT / "decisions.json", decisions)
    selected_ids = {c["id"] for c in selected}
    atomic_json(OUT / "scoring/not-selected.json", [{**d, "nonoverlap_selected": d["id"] in selected_ids} for d in decisions if d["id"] not in selected_ids])
    result = {"status": "READY_WEAK_TRAINING_PAIRS", "proposed_candidates": len(candidates),
        "passed_recheck": sum(d["accepted_recheck"] for d in decisions), "added_pairs": len(added),
        "added_minutes": sum(s.duration_sec for s in added)/60, "train_pairs": len(train),
        "train_minutes": sum(s.duration_sec for s in train)/60, "dev_pairs": len(dev), "dev_byte_identical": True,
        "added_modes": dict(Counter(c["publisher"]["mode"] for c in selected)),
        "added_sources": dict(Counter(c["source"] for c in selected)),
        "recheck_reasons": dict(Counter(r for d in decisions for r in d["reasons"])),
        "new_asr_calls": sum(e["new_asr_calls"] for e in executions.values()),
        "runtime_errors": sum(len(e["errors"]) for e in executions.values()), "training_steps": 0,
        "human_verified_added": 0, "quality_improvement": "NOT_MEASURED",
        "train_sha256": file_hash(dataset / "train.jsonl"), "dev_sha256": file_hash(dataset / "dev.jsonl")}
    atomic_json(OUT / "result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "infer", "assemble"])
    parser.add_argument("--system", choices=list(MODELS))
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare()
    elif args.stage == "infer":
        infer(args.system)
    else:
        assemble()


if __name__ == "__main__":
    main()
