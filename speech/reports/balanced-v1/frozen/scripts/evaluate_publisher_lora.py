"""Separate A5 checkpoint experiment: unverified dev agreement and two general controls."""

import json
import time
from pathlib import Path

import soundfile as sf

from north55_speech.asr import AsrProvider
from north55_speech.core import atomic_json, file_hash, read_yaml, settings
from north55_speech.datasets import load_manifest
from north55_speech.metrics import corpus_counts, edit_counts
from north55_speech.reporting import write_csv
from north55_speech.schemas import PipelineConfig


def main():
    output = settings.report_root / "publisher-weak-v1"
    publisher = Path("/publisher")
    adapted_root = settings.model_root / "whisper-small-publisher-lora-v2"
    adapted = json.loads((adapted_root / "manifest.json").read_text())
    if adapted["reference_policy"] != "publisher_weak_exploratory_v1" or adapted["converted_inference"] != "executed":
        raise ValueError("Expected the completed, explicitly exploratory adaptation")
    for split, key in (("train", "train_sha256"), ("dev", "dev_sha256")):
        if file_hash(publisher / "training" / f"{split}.jsonl") != adapted[key]:
            raise ValueError("Data changed after training")
    base = settings.model_root / "whisper-small-transformers"
    base_manifest = json.loads((base / "manifest.json").read_text())
    baseline_path = settings.model_root / "whisper-small-publisher-base-ct2"
    if not (baseline_path / "manifest.json").is_file():
        from ctranslate2.converters import TransformersConverter

        for name, checksum in base_manifest["files"].items():
            if file_hash(base / name) != checksum:
                raise ValueError("Base checkpoint checksum mismatch")
        TransformersConverter(str(base), copy_files=["tokenizer.json", "preprocessor_config.json"]).convert(
            str(baseline_path), quantization="float16")
        atomic_json(baseline_path / "manifest.json", {
            "model": baseline_path.name, "repo": "local_unadapted_conversion", "revision": base_manifest["revision"],
            "source_manifest_sha256": file_hash(base / "manifest.json"), "license": base_manifest.get("license", "Apache-2.0"),
            "files": {p.name: file_hash(p) for p in baseline_path.iterdir() if p.is_file()},
            "purpose": "same source weights and CT2 float16 conversion control for A5"})
    controls = json.loads((settings.audio_root / "smoke/provenance.json").read_text())
    dev = load_manifest(publisher / "all/dev.jsonl")
    if any(s.split != "dev" for s in dev):
        raise ValueError("No train/test examples may enter this dev comparison")
    items = [{"id": s.sample_id, "audio_path": s.audio_path, "audio_sha256": s.audio_sha256,
              "reference": s.reference_text if s.annotation_provenance["automatic_training_eligible"] else None,
              "reference_kind": "publisher_weak_alignment", "group": s.group_id, "condition": s.acoustic_condition,
              "cohort": "dev", "input_language": "auto", "duration_sec": s.duration_sec,
              "alignment_eligible": s.annotation_provenance["automatic_training_eligible"]} for s in dev]
    for sample in controls["samples"]:
        path = settings.audio_root / "smoke" / sample["filename"]
        items.append({"id": sample["sample_id"], "audio_path": "smoke/" + sample["filename"],
                      "audio_sha256": sample["sha256"], "reference": sample["reference_text"],
                      "reference_kind": "publisher_LibriSpeech_transcript", "group": "librispeech-2277",
                      "condition": "clean_general_read_speech", "cohort": "general_control",
                      "input_language": "en", "duration_sec": sf.info(path).duration, "alignment_eligible": None})
    config = PipelineConfig.model_validate(read_yaml(Path("/app/configs/baseline.yaml")))
    config.device, config.compute_type = "cuda", "float16"
    plan = {"task": "A5_separate_checkpoint_comparison", "items": [{k: v for k, v in r.items() if k != "reference"} for r in items],
            "dev_sha256": file_hash(publisher / "all/dev.jsonl"), "controls_sha256": file_hash(settings.audio_root / "smoke/provenance.json"),
            "parent_model": baseline_path.name, "adapted_model": adapted["converted_model"]["model"],
            "base_source_sha256": file_hash(base / "manifest.json"), "adaptation_sha256": file_hash(adapted_root / "manifest.json"),
            "inference_config": config.model_dump(), "script_sha256": file_hash(Path(__file__)),
            "selection_allowed": False, "quality_gate_evidence": False, "test_accessed": False}
    plan_path = output / "comparison-plan.json"
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError("Preserve the earlier comparison plan")
    atomic_json(plan_path, plan)
    rows = []
    for system, name in (("parent", baseline_path.name), ("adapted", adapted["converted_model"]["model"])):
        provider = AsrProvider(config.model_copy(update={"model": name}))
        for item in items:
            path = settings.audio_root / item["audio_path"]
            if file_hash(path) != item["audio_sha256"]:
                raise ValueError("Evaluation audio changed")
            record_path = output / "comparison-predictions" / f"{system}-{item['id']}.json"
            if record_path.exists():
                record = json.loads(record_path.read_text())
                if record["plan_sha256"] != file_hash(plan_path):
                    raise ValueError("Prediction belongs to a different plan")
            else:
                audio, rate = sf.read(path, dtype="float32")
                if rate != 16000 or audio.ndim != 1:
                    raise ValueError("Comparison requires verified 16 kHz mono audio")
                started = time.perf_counter()
                record = {**{k: v for k, v in item.items() if k != "reference"}, "system": system,
                          "model": name, "plan_sha256": file_hash(plan_path), "runtime_failure": None}
                try:
                    segments = provider.transcribe(audio, 0, item["input_language"], "comparison", lambda: None)
                    hypothesis = " ".join(s.raw_asr_text.strip() for s in segments)
                    record.update(hypothesis=hypothesis, segments=[s.model_dump() for s in segments])
                except Exception as exc:
                    record.update(hypothesis="", segments=[], runtime_failure={"type": type(exc).__name__, "message": str(exc)})
                record["elapsed_sec"] = time.perf_counter() - started
                atomic_json(record_path, record)
            score = edit_counts(item["reference"], record["hypothesis"]) if item["reference"] is not None else None
            rows.append({**record, "score": score})
            print(json.dumps({"system": system, "id": item["id"], "failure": record["runtime_failure"]}), flush=True)
    summaries = {}
    for cohort in ("dev", "general_control"):
        summaries[cohort] = {system: corpus_counts([r["score"] for r in rows if r["cohort"] == cohort
                              and r["system"] == system and r["score"] is not None]) for system in ("parent", "adapted")}
    report = {"status": "EXECUTED_EXPLORATORY", "plan_sha256": file_hash(plan_path), "comparison": summaries,
              "dev_total": len(dev), "dev_proxy_scored": sum(s.annotation_provenance["automatic_training_eligible"] for s in dev),
              "general_controls": len(controls["samples"]), "general_control_independent_groups": 1,
              "runtime_failures": sum(r["runtime_failure"] is not None for r in rows),
              "asr_quality_gate": "NEEDS_MORE_DATA", "candidate_selected": False, "release_promoted": False,
              "critical_entity_quality": "NOT_MEASURED", "nlp_quality": "NEEDS_MORE_DATA", "test_accessed": False,
              "interpretation": {"dev": "Lexical disagreement with automatically aligned publisher script; not independent WER gold. Alignment uses the parent ASR family and may bias this result.",
                "general_control": "WER against existing publisher transcripts for two recordings of one general-speech reader. Too little for the clean-control acceptance gate.",
                "comparison": "A5 model adaptation with both checkpoints converted from the same local base and decoded in float16. Not an A0-A4 pipeline improvement claim."},
              "training": {k: adapted[k] for k in ("train_metrics", "dev_metrics", "reference_policy", "gpu")},
              "rows": rows}
    atomic_json(output / "comparison.json", report)
    write_csv(output / "comparison.csv", ["id", "cohort", "condition", "system", "reference_kind", "S", "D", "I", "N", "wer", "hypothesis", "elapsed_sec"],
              [{**r, **(r["score"] or {})} for r in rows])
    atomic_json(output / "training-manifest.json", adapted)
    atomic_json(output / "training-history.json", json.loads((adapted_root / "training-history.json").read_text()))
    print(json.dumps({k: v for k, v in report.items() if k not in {"rows", "interpretation"}}, indent=2))


if __name__ == "__main__":
    main()
