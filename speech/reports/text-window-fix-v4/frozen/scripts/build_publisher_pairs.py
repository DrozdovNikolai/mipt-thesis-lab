"""Build reproducible weak audio/publisher-text pairs from existing train/dev only."""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from north55_speech.asr import load_model, local_model_manifest
from north55_speech.core import atomic_json, digest, file_hash, read_yaml, settings
from north55_speech.datasets import decoded_audio_hash, load_manifest, validate_groups, write_manifest
from north55_speech.training import check_training_partitions
from scripts.publisher_alignment import METHOD, align, locate, prepare_document

MAPPING = {
    "BEA_checklists": ["BEA_checklist_A320-NormalChecklist", "BEA_checklist_A320_pilote", "BEA_checklist_B737_NORMAL_CHECKLIST"],
    "DGA_checklist-Beech": ["DGA_checklist-Beech"],
    "DGA_checklist-PC7": ["DGA_checklist-PC7"],
}


def clip(source, start, duration, output):
    path = settings.audio_root / source.audio_path
    with sf.SoundFile(path) as stream:
        rate = stream.samplerate
        stream.seek(round(start * rate))
        waveform = stream.read(round(duration * rate), dtype="float32", always_2d=True)[:, source.channel]
    divisor = math.gcd(rate, 16000)
    audio = resample_poly(waveform, 16000 // divisor, rate // divisor).astype(np.float32)
    if len(audio) != round(duration * 16000):
        raise ValueError("Audio window length mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        old, old_rate = sf.read(output, dtype="float32")
        if old_rate != 16000 or not np.array_equal(old, audio):
            raise ValueError("Immutable clip differs")
    else:
        sf.write(output, audio, 16000, subtype="FLOAT")
    return audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["documents", "align"])
    parser.add_argument("--source-documents", type=Path, default=Path("/source-documents"))
    parser.add_argument("--extracted-documents", type=Path, default=Path("/extracted"))
    parser.add_argument("--manifests", type=Path, default=Path("/train-dev"))
    parser.add_argument("--output", type=Path, default=Path("/publisher"))
    parser.add_argument("--config", type=Path, default=Path("/app/configs/publisher_experiment.yaml"))
    args = parser.parse_args()
    docs_dir = args.output / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    names = sorted({name for values in MAPPING.values() for name in values})
    if args.action == "documents":
        for name in names:
            target = docs_dir / f"{name}.json"
            document = prepare_document(json.loads((args.extracted_documents / f"{name}.json").read_text()), args.source_documents)
            if target.exists() and json.loads(target.read_text()) != document:
                raise ValueError("Use a new document preparation version")
            atomic_json(target, document)
        print(json.dumps({"status": "PREPARED", "documents": len(names), "method": METHOD}))
        return
    config = read_yaml(args.config)
    expected = {"minimum_exact_anchor_coverage": .45, "minimum_exact_anchor_tokens": 8,
                "minimum_median_alignment_score": .35, "maximum_zero_duration_fraction": .25,
                "reject_numeric_disagreement": True, "use_test": False, "selection_allowed": False,
                "quality_evidence": False}
    if any(config.get(k) != value for k, value in expected.items()):
        raise ValueError("Preparation policy differs from the implemented frozen method")
    sources = []
    for split in ("train", "dev"):
        loaded = load_manifest(args.manifests / f"{split}.jsonl")
        if any(s.split != split for s in loaded):
            raise ValueError("Only independent train/dev partitions may be used")
        sources.extend(loaded)
    parents = [s for s in sources if s.source_dataset == "BLeRIOT-A" and any(family in s.sample_id for family in MAPPING)]
    variants = {s.variant_of: s for s in sources if s.variant_of
                and (s.augmentation or {}).get("parent_link_status") == "ACOUSTICALLY_CONFIRMED"}
    documents = {name: json.loads((docs_dir / f"{name}.json").read_text()) for name in names}
    model_manifest = local_model_manifest(config["alignment_model"])
    plan = {"config": config, "manifests": {split: file_hash(args.manifests / f"{split}.jsonl") for split in ("train", "dev")},
            "documents": {name: file_hash(docs_dir / f"{name}.json") for name in names},
            "parents": [s.sample_id for s in parents], "model": model_manifest,
            "code": {Path(__file__).name: file_hash(Path(__file__)), "publisher_alignment.py": file_hash(Path(__file__).with_name("publisher_alignment.py"))},
            "method": METHOD, "human_verified": False, "test_accessed": False}
    plan_path = args.output / "plan.json"
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError("Frozen preparation plan differs; use a new version")
    atomic_json(plan_path, plan)
    model = load_model(config["alignment_model"], config["alignment_device"], config["alignment_precision"], digest(model_manifest))
    rows, report_rows = [], []
    for parent in parents:
        family = next(name for name in MAPPING if name in parent.sample_id)
        if file_hash(settings.audio_root / parent.audio_path) != parent.audio_sha256:
            raise ValueError("Parent audio checksum mismatch")
        for start in config["window_starts_sec"]:
            duration = config["window_duration_sec"]
            if start + duration > parent.duration_sec:
                continue
            sample_id = digest({"source": parent.sample_id, "window": [start, start + duration]})[:32]
            audio_path = settings.audio_root / "publisher-clips-v1" / f"{sample_id}.wav"
            audio = clip(parent, start, duration, audio_path)
            proposal_path = args.output / "proposals" / f"{sample_id}.json"
            if proposal_path.exists():
                proposal = json.loads(proposal_path.read_text())
            else:
                segments, info = model.transcribe(audio, beam_size=5, temperature=0, task="transcribe", vad_filter=False,
                                                  word_timestamps=True, condition_on_previous_text=True)
                draft = " ".join(s.text.strip() for s in segments)
                ranked = sorted(MAPPING[family], key=lambda name: -locate(draft, documents[name])["matched_tokens"])
                proposal = align(model, audio, documents[ranked[0]], draft, start)
                proposal.update({"sample_id": sample_id, "draft": draft, "detected_language": info.language,
                                 "source_sample_id": parent.sample_id, "split": parent.split, "start_sec": start,
                                 "plan_sha256": file_hash(plan_path), "source_audio_sha256": parent.audio_sha256})
                if info.language not in {"en", "fr"}:
                    proposal["reasons"].append("unexpected_detected_language")
                    proposal["eligible_for_exploratory_training"] = False
                atomic_json(proposal_path, proposal)
            if proposal["plan_sha256"] != file_hash(plan_path):
                raise ValueError("Cached alignment belongs to a different plan")
            for source in [parent] + ([variants[parent.sample_id]] if parent.sample_id in variants else []):
                variant = source.sample_id != parent.sample_id
                identity = digest({"source": source.sample_id, "window": [start, start + duration]})[:32]
                path = settings.audio_root / "publisher-clips-v1" / f"{identity}.wav"
                if variant:
                    if file_hash(settings.audio_root / source.audio_path) != source.audio_sha256:
                        raise ValueError("Paired variant audio checksum mismatch")
                    clip(source, start, duration, path)
                sample = source.model_copy(deep=True, update={
                    "sample_id": identity, "audio_path": str(path.relative_to(settings.audio_root)),
                    "audio_sha256": file_hash(path), "decoded_audio_sha256": decoded_audio_hash([path]),
                    "duration_sec": duration, "channel": 0, "group_id": None,
                    "original_utterance_id": f"{parent.original_utterance_id}@{start}:{start+duration}",
                    "variant_of": sample_id if variant else None, "primary": False, "clean_control": False,
                    "scope": "read_cockpit", "scope_verified": False, "language": "en",
                    "reference_text": proposal["text"] or None, "transcript_status": "weak" if proposal["text"] else "missing",
                    "annotation_provenance": {"method": METHOD, "reviewed_audio": False, "annotator": None,
                        "publisher_transcript": True, "source_file": proposal["source_file"], "source_sha256": proposal["source_sha256"],
                        "alignment_sha256": file_hash(proposal_path), "preparation_plan_sha256": file_hash(plan_path),
                        "parent_group_id": source.group_id, "source_sample_id": source.sample_id,
                        "original_start_sec": start, "original_end_sec": start + duration,
                        "automatic_training_eligible": proposal["eligible_for_exploratory_training"],
                        "eligibility_reasons": proposal["reasons"], "language_basis": "English publisher checklist; audio not human verified",
                        "paired_target_from_clean_original": variant},
                })
                rows.append(sample)
                report_rows.append({"id": identity, "split": sample.split, "condition": sample.acoustic_condition,
                                    "eligible": proposal["eligible_for_exploratory_training"], "reasons": proposal["reasons"],
                                    "matched_coverage": proposal["coverage"]})
            print(json.dumps({"sample": sample_id, "source": parent.sample_id, "start": start,
                              "eligible": proposal["eligible_for_exploratory_training"], "reasons": proposal["reasons"]}), flush=True)
    groups = validate_groups(rows)
    accepted = [s for s in rows if s.annotation_provenance["automatic_training_eligible"]]
    train, dev = [[s for s in accepted if s.split == split] for split in ("train", "dev")]
    if train and dev:
        check_training_partitions(train, dev)
    for split in ("train", "dev"):
        write_manifest(args.output / "all" / f"{split}.jsonl", [s for s in rows if s.split == split])
        write_manifest(args.output / "training" / f"{split}.jsonl", [s for s in accepted if s.split == split])
    atomic_json(args.output / "preparation-report.json", {
        "status": "READY_FOR_EXPLORATORY_TRAINING" if train and dev else "NEEDS_MORE_DATA",
        "plan_sha256": file_hash(plan_path), "groups": groups, "total_rows": len(rows),
        "eligible_train": len(train), "eligible_dev": len(dev), "items": report_rows,
        "human_verified": 0, "quality_evidence": False, "test_accessed": False,
        "limitations": ["Machine ASR helps locate publisher text; these targets are not independent evaluation gold",
                        "English publisher text is a language proposal, not verification of every spoken word",
                        "Unsupported French checklist families are excluded before this experiment",
                        "Numbers with a draft/script disagreement are withheld from training, never corrected by context",
                        "Same script families can occur across source splits; no script-disjoint generalization"]})


if __name__ == "__main__":
    main()
