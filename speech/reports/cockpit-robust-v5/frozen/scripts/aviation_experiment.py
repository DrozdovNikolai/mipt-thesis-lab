"""Reference-isolated, cross-corpus aviation recognition comparison."""

import argparse
import csv
import io
import json
import math
import re
import time
from collections import Counter
from pathlib import Path
from uuid import uuid4

import numpy as np
import soundfile as sf

from north55_speech.core import atomic_json, digest, file_hash, now
from scripts.improvement_experiment import jsonl, load_input, pcm_hash, read

MODELS = {"small": "whisper-small-publisher-base-ct2", "medium": "whisper-medium-en-ct2",
          "atc": "whisper-medium-en-atc-jacktol-ct2"}


def identity():
    root = Path("/code")
    return {str(p.relative_to(root)): file_hash(p) for folder in ("src", "scripts")
            for p in sorted((root / folder).rglob("*.py"))}


def source_identity(identifier, metadata):
    match = re.fullmatch(r"atcosim_((?:sm[1-4]|gf1|gm[12]|zf[1-3])_\d{2}_\d{3})_\d+_\d+", identifier)
    if not match or match[1] not in metadata:
        raise ValueError("Unverifiable source identity")
    source = metadata[match[1]]
    speaker = match[1].split("_")[0]
    if source["speaker_id"] != speaker or source["recording_corrupt"] != "0":
        raise ValueError("Source speaker mismatch or corrupt original")
    return match[1], speaker, source["recording_id"]


def prepare():
    import pyarrow.parquet as pq
    from scipy.signal import resample_poly

    from north55_speech.asr import local_model_manifest
    from north55_speech.schemas import PipelineConfig

    w, out = Path("/workspace"), Path("/output")
    if (out / "inference/plan.json").exists():
        raise ValueError("Preparation is immutable")
    old = w / "reports/improvement-v1"
    old_refs = read(old / "scoring/references.json")
    items = [i for i in read(old / "inference/inputs.json") if i["cohort"] not in {
        "general_ru", "new_ru_primary", "new_ru_repeat_readings"}]
    refs = {i["id"]: old_refs[i["id"]] for i in items}
    for i in items:
        i["original_input_language"] = i["input_language"]
        i["input_language"] = "en"
    source = w / "data/input/atcosim-v1"
    acquisition = read(source / "acquisition.json")
    for name, expected in acquisition["verified_files"].items():
        if file_hash(source / name) != expected:
            raise ValueError("Corpus source checksum mismatch")
    for name, entry in acquisition["original_metadata"].items():
        if file_hash(source / name) != entry["sha256"]:
            raise ValueError("Original metadata checksum mismatch")
    with (source / "fulldata.csv").open(encoding="ascii", newline="") as f:
        metadata_rows = list(csv.DictReader(f))
    metadata = {r["filename"]: r for r in metadata_rows}
    if len(metadata) != len(metadata_rows):
        raise ValueError("Duplicate original source identity")
    train = jsonl(w / "data/curated/nus-training-v1/train.jsonl")
    train += jsonl(w / "data/curated/publisher-expanded-v1/training/train.jsonl")
    train_pcm = set()
    for row in {r["audio_path"]: r for r in train}.values():
        if row["split"] != "train":
            raise ValueError("Unexpected training partition")
        path = Path("/audio") / row["audio_path"]
        if file_hash(path) != row["audio_sha256"]:
            raise ValueError("Training source checksum mismatch")
        x, sr = sf.read(path, dtype="float32")
        if sr != 16000 or x.ndim != 1:
            raise ValueError("Unexpected training format")
        train_pcm.add(pcm_hash(x))
    seen_pcm, source_notes = {}, []
    audio_dir = Path("/new-audio")
    audio_dir.mkdir(parents=True, exist_ok=True)
    for parquet in sorted((source / "data").glob("test-*.parquet")):
        for batch in pq.ParquetFile(parquet).iter_batches(batch_size=16):
            for row in batch.to_pylist():
                identifier = row["id"]
                original, speaker, recording = source_identity(identifier, metadata)
                x, sr = sf.read(io.BytesIO(row["audio"]["bytes"]), dtype="float32")
                if (sr not in {16000, 32000} or x.ndim != 1 or not len(x) or not np.isfinite(x).all()
                        or abs(len(x) / sr - row["duration"]) > .03):
                    raise ValueError("Invalid corpus audio or duration")
                source_rate, source_pcm = sr, pcm_hash(x)
                if sr != 16000:
                    divisor = math.gcd(sr, 16000)
                    x = resample_poly(x, 16000 // divisor, sr // divisor).astype("float32")
                    sr = 16000
                if not row["text"].strip():
                    raise ValueError("Missing corpus transcript")
                h = pcm_hash(x)
                if h in train_pcm:
                    raise ValueError("Evaluation waveform overlaps local training")
                if h in seen_pcm:
                    source_notes.append({"id": identifier, "exact_pcm_duplicate_of": seen_pcm[h]})
                seen_pcm[h] = identifier
                target = audio_dir / f"{identifier}.wav"
                sf.write(target, x, sr, subtype="FLOAT")
                refs[identifier] = row["text"]
                items.append({"id": identifier, "original_id": original,
                    "speaker_id": speaker, "group_id": f"atcosim-speaker-{speaker}",
                    "source_sample_rate": source_rate, "source_pcm_sha256": source_pcm,
                    "recording_id": recording, "audio_path": str(target), "audio_sha256": file_hash(target),
                    "pcm_sha256": h, "duration_sec": len(x) / sr, "input_language": "en",
                    "cohort": "atcosim", "scope": "atc_simulated_controller",
                    "source_split": "test", "reference_kind": "publisher_transcript_normalized_by_mirror",
                    "local_human_verified": False})
    if len({i["id"] for i in items}) != len(items):
        raise ValueError("Duplicate evaluation ID")
    if source_notes:
        atomic_json(out / "source-issues.json", source_notes)
        raise ValueError("Repeated evaluation PCM requires explicit accounting before freeze")
    for item in items:
        if pcm_hash(load_input(item)) != item["pcm_sha256"]:
            raise ValueError("Frozen audio identity mismatch")
    configs = {s: PipelineConfig.model_validate(read(old / "inference/plan.json")["baseline"] |
                    {"name": f"aviation_{s}_v1", "model": model}).model_dump() for s, model in MODELS.items()}
    atomic_json(out / "inference/inputs.json", items)
    atomic_json(out / "scoring/references.json", refs)
    plan = {"created_at": now().isoformat(), "code": identity(), "configs": configs,
            "models": {s: local_model_manifest(m) for s, m in MODELS.items()},
            "protocol_sha256": file_hash(out / "protocol.md"), "acquisition": acquisition,
            "inputs_sha256": file_hash(out / "inference/inputs.json"),
            "references_sha256": file_hash(out / "scoring/references.json"),
            "cohorts": dict(Counter(i["cohort"] for i in items)),
            "atcosim_speakers": dict(Counter(i["speaker_id"] for i in items if i["cohort"] == "atcosim")),
            "gate": {"threshold": .5, "min_speech_duration_ms": 100},
            "local_train_pcm_exclusions": len(train_pcm), "source_metadata_rows": len(metadata),
            "local_training_steps": 0, "max_configurations": 6,
            "old_cockpit_closed_test_accessed": False, "full_spec_gate": "NEEDS_MORE_DATA"}
    atomic_json(out / "inference/plan.json", plan)
    print(json.dumps({"cohorts": plan["cohorts"], "speakers": plan["atcosim_speakers"]}), flush=True)


def infer(system):
    from north55_speech.asr import AsrProvider
    from north55_speech.audio import VadProvider
    from north55_speech.schemas import PipelineConfig, VadConfig

    study, output = Path("/study"), Path("/predictions") / system
    plan = read(study / "plan.json")
    if identity() != plan["code"] or file_hash(study / "inputs.json") != plan["inputs_sha256"]:
        raise ValueError("Frozen inference code/input changed")
    items, plan_hash = read(study / "inputs.json"), file_hash(study / "plan.json")
    output.mkdir(parents=True, exist_ok=True)
    execution_path = output / "execution.json"
    if execution_path.exists():
        execution = read(execution_path)
        if execution["plan_sha256"] != plan_hash or any(
            file_hash(output / f"{i['id']}.json") != execution["files"][i["id"]] for i in items
        ):
            raise ValueError("Completed run integrity failure")
        print(f"{system}: verified existing completed run; no overwritten evidence", flush=True)
        return
    config = PipelineConfig.model_validate(plan["configs"][system])
    provider = AsrProvider(config)
    if provider.manifest != plan["models"][system]:
        raise ValueError("Frozen model manifest changed")
    if provider.model.model.device != "cuda" or provider.model.model.compute_type != "float16":
        raise ValueError("Unexpected runtime precision/device")
    begun, completed, resumed = time.perf_counter(), 0, 0
    for index, item in enumerate(items):
        path = output / f"{item['id']}.json"
        if path.exists():
            previous = read(path)
            if previous["plan_sha256"] != plan_hash or previous["pcm_sha256"] != item["pcm_sha256"]:
                raise ValueError("Partial resume identity mismatch")
            resumed += 1
            continue
        x = load_input(item)
        if pcm_hash(x) != item["pcm_sha256"]:
            raise ValueError("Runtime PCM changed")
        started = time.perf_counter()
        record = {"id": item["id"], "plan_sha256": plan_hash, "pcm_sha256": item["pcm_sha256"],
                  "options": provider.options("en"), "hypothesis": "", "segments": [], "runtime_failure": None}
        try:
            record["speech_intervals"] = VadProvider().intervals(x, VadConfig(enabled=True, **plan["gate"]))
            segments = provider.transcribe(x, 0, "en", item["id"], lambda: None)
            record["segments"] = [s.model_dump() for s in segments]
            record["hypothesis"] = " ".join(s.raw_asr_text.strip() for s in segments)
        except Exception as exc:
            record["runtime_failure"] = {"type": type(exc).__name__, "message": str(exc)}
        record["elapsed_sec"] = time.perf_counter() - started
        atomic_json(path, record)
        completed += 1
        if index % 50 == 0:
            print(json.dumps({"system": system, "done": index + 1, "total": len(items),
                              "elapsed_sec": time.perf_counter() - begun}), flush=True)
    execution = {"plan_sha256": plan_hash, "new_calls": completed, "resumed_records": resumed,
        "total_calls": len(items), "wall_sec": time.perf_counter() - begun,
        "model_initialization_sec": provider.initialization_sec,
        "files": {i["id"]: file_hash(output / f"{i['id']}.json") for i in items}}
    atomic_json(output / "attempts" / f"{uuid4().hex}.json", execution)
    atomic_json(execution_path, execution)
    print(json.dumps({"system": system, "completed": len(items), "new_calls": completed}), flush=True)


def candidate_decision(summaries):
    def wer(cohort, system, kind="lexical"):
        return summaries[cohort][system][kind]["wer_lexical_corpus"]
    quality = (all(wer("atcosim", "atc", kind) <= .9 * wer("atcosim", "medium", kind)
                   for kind in ("lexical", "canonical"))
               and wer("atcosim", "atc") < wer("atcosim", "small")
               and all(summaries[c]["atc"]["failures"] == 0 for c in summaries))
    gate = (wer("atcosim", "atc_gate") <= wer("atcosim", "atc")
            and all(summaries[c]["atc_gate"]["lexical"]["I"] <= summaries[c]["small"]["lexical"]["I"]
                    for c in ("noise_only", "bleriot_b_noise")))
    return {"quality": quality, "gate": gate, "selected": ("atc_gate" if gate else "atc") if quality else None}


def score():
    from north55_speech.metrics import (
        canonical_normalizer_v1,
        corpus_counts,
        edit_counts,
        paired_cluster_bootstrap,
    )

    out = Path("/output")
    plan, items = read(out / "inference/plan.json"), read(out / "inference/inputs.json")
    refs = read(out / "scoring/references.json")
    if (identity() != plan["code"] or file_hash(out / "protocol.md") != plan["protocol_sha256"]
            or file_hash(out / "inference/inputs.json") != plan["inputs_sha256"]
            or file_hash(out / "scoring/references.json") != plan["references_sha256"]):
        raise ValueError("Frozen scoring integrity failure")
    counts, records = {}, {}
    systems = [s + suffix for s in MODELS for suffix in ("", "_gate")]
    for base in MODELS:
        execution = read(out / "predictions" / base / "execution.json")
        for i in items:
            path = out / "predictions" / base / f"{i['id']}.json"
            r = read(path)
            if (file_hash(path) != execution["files"][i["id"]]
                    or r["plan_sha256"] != file_hash(out / "inference/plan.json")
                    or r["pcm_sha256"] != i["pcm_sha256"]):
                raise ValueError("Prediction hash or identity mismatch")
            for suffix in ("", "_gate"):
                key = base + suffix, i["id"]
                text = r["hypothesis"] if not suffix or r.get("speech_intervals") else ""
                records[key] = r
                counts[key] = {"lexical": edit_counts(refs[i["id"]], text),
                    "canonical": edit_counts(canonical_normalizer_v1(refs[i["id"]]), canonical_normalizer_v1(text))}
    summaries = {}
    cohorts = {c: [i for i in items if i["cohort"] == c] for c in sorted(plan["cohorts"])}
    cohorts.update({"speaker_" + speaker: [i for i in cohorts["atcosim"] if i["speaker_id"] == speaker]
                    for speaker in sorted(plan["atcosim_speakers"])})
    for cohort, selected in cohorts.items():
        minutes = sum(i["duration_sec"] for i in selected) / 60
        summaries[cohort] = {s: {kind: corpus_counts([counts[s, i["id"]][kind] for i in selected])
                                  for kind in ("lexical", "canonical")} |
            {"clips": len(selected), "minutes": minutes,
             "failures": sum(records[s, i["id"]]["runtime_failure"] is not None for i in selected)} for s in systems}
    decision = candidate_decision(summaries)
    comparisons = {}
    for baseline in ("small", "medium"):
        for kind in ("lexical", "canonical"):
            comparisons[f"atc_vs_{baseline}_{kind}"] = paired_cluster_bootstrap([
                {"group_id": i["group_id"], "baseline": counts[baseline, i["id"]][kind],
                 "candidate": counts["atc", i["id"]][kind]} for i in cohorts["atcosim"]])
    result = {"plan_sha256": file_hash(out / "inference/plan.json"), "cohorts": summaries,
              "decision": decision, "speaker_bootstrap": comparisons, "primary_scope": "ATCOSIM simulated controller English",
              "full_spec_gate": "NEEDS_MORE_DATA", "runtime_failures": {
                  s: [i["id"] for i in items if records[s, i["id"]]["runtime_failure"]] for s in systems}}
    atomic_json(out / "metrics.json", result)
    atomic_json(out / "scoring/counts.json", {s: {i["id"]: counts[s, i["id"]] for i in items} for s in systems})
    if decision["selected"]:
        config = dict(plan["configs"]["atc"])
        if decision["selected"].endswith("_gate"):
            config["vad"] = config["vad"] | plan["gate"] | {"enabled": True, "mode": "gate"}
        recipe = {"schema_version": "1.0", "source_plan_sha256": result["plan_sha256"],
                  "metrics_sha256": file_hash(out / "metrics.json"),
                  "default": config, "by_language": {"en": config},
                  "allowed_languages": ["en"], "profile": "aviation_atc_en",
                  "model_manifest_digests": {MODELS["atc"]: digest(plan["models"]["atc"])},
                  "evaluation_scope": {"en": result["primary_scope"], "full_spec_gate": "NEEDS_MORE_DATA",
                                       "cockpit_and_general": "separate regression results; not default routes"}}
        atomic_json(out / "recipe/selected.json", recipe)
    print(json.dumps({"decision": decision, "atcosim": {s: {k: summaries["atcosim"][s][k]["wer_lexical_corpus"]
                       for k in ("lexical", "canonical")} for s in systems}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "infer", "score"])
    parser.add_argument("system", nargs="?", choices=list(MODELS))
    args = parser.parse_args()
    if args.stage == "infer":
        if args.system is None:
            parser.error("infer requires a system")
        infer(args.system)
    else:
        {"prepare": prepare, "score": score}[args.stage]()
