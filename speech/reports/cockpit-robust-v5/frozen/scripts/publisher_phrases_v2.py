"""Build traceable weak training transcripts from pause clips and repaired scripts."""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from north55_speech.core import atomic_json, file_hash
from scripts.expand_publisher_pairs import FAMILIES
from scripts.publisher_phrase_support import POLICY, assess

MODEL = "whisper-medium-en-ct2"


def read(path):
    return json.loads(path.read_bytes())


def code_hashes():
    root = Path("/code")
    return {name: file_hash(root / name) for name in (
        "scripts/publisher_phrases_v2.py", "scripts/publisher_phrase_support.py",
        "scripts/publisher_alignment.py", "src/north55_speech/asr.py",
        "src/north55_speech/metrics.py", "src/north55_speech/schemas.py")}


def prepare(workspace, out):
    from north55_speech.asr import local_model_manifest

    if (out / "inference/plan.json").exists():
        raise ValueError("Preserve the existing frozen preparation")
    previous = workspace / "data/curated/pair-quality-v1"
    plan = read(previous / "plan.json")
    sources = read(previous / "sources.json")
    if any(s["split"] != "train" for s in sources.values()):
        raise ValueError("Only original training sources are allowed")
    items = plan["items"]
    assert len(items) == 675
    execution = read(previous / "small/execution.json")
    if set(execution["prediction_sha256"]) != {i["id"] + ".json" for i in items}:
        raise ValueError("Historical small execution is incomplete")
    for item in items:
        path = previous / "small/predictions" / f"{item['id']}.json"
        if file_hash(path) != execution["prediction_sha256"][path.name]:
            raise ValueError("Historical prediction changed")
    documents = read(out / "documents/documents.json")
    visual_path = workspace / "configs/publisher_visual_lines_v2.json"
    visual = read(visual_path)
    for name, corrected in visual["documents"].items():
        doc = documents[name]
        if corrected["source_sha256"] != doc["source_sha256"]:
            raise ValueError("Visual transcription source mismatch")
        doc["previous_ocr_lines"] = doc["lines"]
        doc["lines"] = [{"text": line, "page": int(page), "excluded_layout": False,
                         "method": visual["method"]} for page, lines in corrected["pages"].items() for line in lines]
        doc["visual_transcription_sha256"] = file_hash(visual_path)
        doc["visual_pages_sha256"] = {page: file_hash(workspace / "data/curated/bleriot-documents/v1" /
                                        f"{Path(name).stem}_pages/page-{int(page):03d}.png") for page in corrected["pages"]}
    atomic_json(out / "scoring/documents.json", documents)
    atomic_json(out / "scoring/source-plan.json", plan)
    atomic_json(out / "scoring/sources.json", sources)
    inputs = [{k: i[k] for k in ("id", "audio_path", "audio_sha256", "duration_sec")} for i in items]
    atomic_json(out / "inference/inputs.json", inputs)
    frozen = {"policy": POLICY, "model": MODEL, "model_manifest": local_model_manifest(MODEL),
              "code_sha256": code_hashes(), "source_plan_sha256": file_hash(previous / "plan.json"),
              "source_rows_sha256": file_hash(previous / "sources.json"),
              "small_execution_sha256": file_hash(previous / "small/execution.json"),
              "old_train_sha256": file_hash(workspace / "data/curated/publisher-recovery-v1/train.jsonl"),
              "dev_sha256": file_hash(workspace / "data/curated/publisher-expanded-v1/training/dev.jsonl"),
              "documents_sha256": file_hash(out / "scoring/documents.json"),
              "inputs_sha256": file_hash(out / "inference/inputs.json"), "asr_calls_planned": len(inputs),
              "test_accessed": False, "dev_used_for_selection": False}
    atomic_json(out / "inference/plan.json", frozen)
    print(json.dumps({"inputs": len(inputs), "source_minutes": sum(i['duration_sec'] for i in items)/60,
                      "training_sources": len(sources), "policy": POLICY}, indent=2))


def infer(study, predictions):
    import soundfile as sf

    from north55_speech.asr import AsrProvider
    from north55_speech.core import settings
    from north55_speech.schemas import PipelineConfig

    plan, plan_sha = read(study / "plan.json"), file_hash(study / "plan.json")
    if plan["policy"] != POLICY or code_hashes() != plan["code_sha256"]:
        raise ValueError("Frozen code or policy changed")
    if file_hash(study / "inputs.json") != plan["inputs_sha256"]:
        raise ValueError("Frozen input list changed")
    items = read(study / "inputs.json")
    execution_path = predictions / "execution.json"
    if execution_path.exists():
        execution = read(execution_path)
        if execution["plan_sha256"] != plan_sha or set(execution["predictions"]) != {i["id"] for i in items}:
            raise ValueError("Completed execution mismatch")
        for key, sha in execution["predictions"].items():
            if file_hash(predictions / f"{key}.json") != sha:
                raise ValueError("Completed prediction changed")
        print("Completed inference verified; no new ASR calls")
        return
    provider = AsrProvider(PipelineConfig(model=MODEL, device="cuda", compute_type="float16",
                                          condition_on_previous_text=False))
    if provider.manifest != plan["model_manifest"]:
        raise ValueError("Measured model changed")
    begun, hashes, failures, new = time.perf_counter(), {}, [], 0
    for index, item in enumerate(items):
        path = predictions / f"{item['id']}.json"
        if path.exists():
            prediction = read(path)
            if prediction["plan_sha256"] != plan_sha or prediction["audio_sha256"] != item["audio_sha256"]:
                raise ValueError("Resume identity mismatch")
        else:
            audio_path = settings.audio_root / item["audio_path"]
            if file_hash(audio_path) != item["audio_sha256"]:
                raise ValueError("Audio checksum mismatch")
            audio, rate = sf.read(audio_path, dtype="float32")
            if rate != 16000 or audio.ndim != 1 or abs(len(audio)/rate - item["duration_sec"]) > 0.001:
                raise ValueError("Audio contract mismatch")
            prediction = {"id": item["id"], "plan_sha256": plan_sha,
                          "audio_sha256": item["audio_sha256"], "options": provider.options("en"),
                          "hypothesis": "", "segments": [], "error": None}
            try:
                segments = provider.transcribe(audio, 0, "en", item["id"], lambda: None)
                prediction.update(hypothesis=" ".join(s.raw_asr_text.strip() for s in segments),
                                  segments=[s.model_dump(mode="json") for s in segments])
            except Exception as exc:
                prediction["error"] = f"{type(exc).__name__}: {exc}"
            atomic_json(path, prediction)
            new += 1
        hashes[item["id"]] = file_hash(path)
        if prediction["error"]:
            failures.append(item["id"])
        if (index+1) % 25 == 0:
            print(json.dumps({"completed": index+1, "total": len(items)}), flush=True)
    atomic_json(execution_path, {"plan_sha256": plan_sha, "predictions": hashes, "new_asr_calls": new,
                "failures": failures, "seconds": time.perf_counter()-begun,
                "device": provider.model.model.device, "precision": provider.model.model.compute_type})


def assemble(workspace, out, dataset):
    from north55_speech.core import settings
    from north55_speech.datasets import (
        Sample,
        decoded_audio_hash,
        load_manifest,
        validate_groups,
        write_manifest,
    )
    from north55_speech.lora import validate_references

    plan_path = out / "inference/plan.json"
    frozen, plan_sha = read(plan_path), file_hash(plan_path)
    previous = workspace / "data/curated/pair-quality-v1"
    if code_hashes() != frozen["code_sha256"] or POLICY != frozen["policy"]:
        raise ValueError("Frozen selection code changed")
    for path, key in ((previous / "plan.json", "source_plan_sha256"),
                      (previous / "sources.json", "source_rows_sha256"),
                      (previous / "small/execution.json", "small_execution_sha256"),
                      (out / "scoring/documents.json", "documents_sha256")):
        if file_hash(path) != frozen[key]:
            raise ValueError("Source evidence changed")
    source_plan, sources = read(previous / "plan.json"), read(previous / "sources.json")
    small_execution = read(previous / "small/execution.json")
    execution = read(out / "predictions/execution.json")
    items = source_plan["items"]
    if execution["plan_sha256"] != plan_sha or set(execution["predictions"]) != {i["id"] for i in items}:
        raise ValueError("Incomplete medium execution")
    documents = read(out / "scoring/documents.json")
    accepted, decisions = [], []
    for index, item in enumerate(items):
        small_path = previous / "small/predictions" / f"{item['id']}.json"
        medium_path = out / "predictions" / f"{item['id']}.json"
        if (file_hash(small_path) != small_execution["prediction_sha256"][small_path.name]
                or file_hash(medium_path) != execution["predictions"][item["id"]]):
            raise ValueError("Prediction integrity mismatch")
        relevant = {n + ".json": documents[n + ".json"] for n in FAMILIES[item["family"]]}
        decision = {"id": item["id"], "source": item["source"],
                    **assess(read(small_path), read(medium_path), relevant, item["duration_sec"])}
        decisions.append(decision)
        if decision["accepted"]:
            parent = sources[item["source"]]
            doc = relevant[decision["publisher"]["document"]]
            row = {**parent, "sample_id": item["id"], "audio_path": item["audio_path"],
                   "audio_sha256": item["audio_sha256"],
                   "decoded_audio_sha256": decoded_audio_hash([settings.audio_root / item["audio_path"]]),
                   "duration_sec": item["duration_sec"], "channel": 0, "variant_of": None,
                   "original_utterance_id": f"{parent['original_utterance_id']}@{item['start_sample']}:{item['end_sample']}",
                   "language": "en", "input_language": "en", "scope": "read_cockpit", "scope_verified": False,
                   "reference_text": decision["target"], "transcript_status": "weak", "primary": False,
                   "continuous_recording": False, "group_id": None,
                   "annotation_provenance": {"method": POLICY["version"], "publisher_transcript": False,
                       "publisher_supported": True, "reviewed_audio": False, "annotator": None,
                       "automatic_training_eligible": True, "eligibility_reasons": [],
                       "source_file": doc["source_file"], "source_sha256": doc["source_sha256"],
                       "document_bundle_sha256": frozen["documents_sha256"], "selection_plan_sha256": plan_sha,
                       "small_prediction_sha256": file_hash(small_path), "medium_prediction_sha256": file_hash(medium_path),
                       "source_sample_id": item["source"], "original_start_sec": item["original_start_sec"],
                       "original_end_sec": item["original_end_sec"], "asr_disagreement": decision["asr_disagreement"],
                       "publisher_coverage": decision["publisher"]["coverage"], "language_verified": False,
                       "target_origin": "unprompted_medium_en_prediction"}}
            accepted.append(Sample.model_validate(row))
        if (index+1) % 100 == 0:
            print(json.dumps({"assessed": index+1, "accepted": len(accepted)}), flush=True)
    dev_path = workspace / "data/curated/publisher-expanded-v1/training/dev.jsonl"
    if file_hash(dev_path) != frozen["dev_sha256"]:
        raise ValueError("Previous dev changed")
    dev = load_manifest(dev_path)
    if accepted:
        validate_groups(accepted)
        validate_references(accepted, dev, {"reference_policy": POLICY["version"],
                            "quality_evidence": False, "selection_allowed": False})
    if (dataset / "train.jsonl").exists():
        raise ValueError("Do not overwrite a dataset version")
    write_manifest(dataset / "train.jsonl", accepted)
    (dataset / "dev.jsonl").write_bytes(dev_path.read_bytes())
    atomic_json(out / "decisions.json", decisions)
    total = sum(s.duration_sec for s in accepted) / 60
    result = {"status": "READY_WEAK_TRAINING_PAIRS" if accepted else "NO_PAIRS", "considered_pause_clips": len(items),
              "accepted_pairs": len(accepted), "accepted_minutes": total,
              "speakers": len({v for s in accepted for v in s.speaker_ids}),
              "short_pairs_under_eight_words": sum(len(s.reference_text.split()) < 8 for s in accepted),
              "all_input_minutes": sum(i["duration_sec"] for i in items)/60,
              "per_source": dict(Counter(d["source"] for d in decisions if d["accepted"])),
              "rejection_reasons": dict(Counter(r for d in decisions for r in d["reasons"])),
              "train_sha256": file_hash(dataset / "train.jsonl"), "dev_sha256": file_hash(dataset / "dev.jsonl"),
              "dev_byte_identical": file_hash(dataset / "dev.jsonl") == frozen["dev_sha256"],
              "new_asr_calls": execution["new_asr_calls"], "runtime_failures": len(execution["failures"]),
              "human_verified_added": 0, "training_steps": 0, "asr_quality_improvement": "NOT_MEASURED"}
    atomic_json(out / "result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "infer", "assemble"))
    parser.add_argument("--workspace", type=Path, default=Path("/workspace"))
    parser.add_argument("--out", type=Path, default=Path("/output"))
    parser.add_argument("--study", type=Path, default=Path("/study"))
    parser.add_argument("--predictions", type=Path, default=Path("/predictions"))
    parser.add_argument("--dataset", type=Path, default=Path("/dataset"))
    args = parser.parse_args()
    if args.stage == "prepare":
        prepare(args.workspace, args.out)
    elif args.stage == "infer":
        infer(args.study, args.predictions)
    else:
        assemble(args.workspace, args.out, args.dataset)


if __name__ == "__main__":
    main()
