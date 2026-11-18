"""Use all full English checklist windows in the existing train/dev partitions.

The original pilot, thresholds and human reviews stay immutable. This preparation
creates weak publisher targets only and includes the previously omitted TBM940.
"""

import argparse
import json
from pathlib import Path

from north55_speech.asr import load_model, local_model_manifest
from north55_speech.core import atomic_json, digest, file_hash, now, settings
from north55_speech.datasets import (
    decoded_audio_hash,
    load_manifest,
    validate_groups,
    write_manifest,
)
from north55_speech.training import check_training_partitions
from scripts.build_publisher_pairs import MAPPING, clip
from scripts.publisher_alignment import METHOD, align, locate, prepare_document

FAMILIES = {**MAPPING, "DGA_checklist-TBM940": ["DGA_checklist-TBM940"]}


def windows(duration):
    # Full windows avoid changing the existing clip/resampling contract.
    return [(start, 20) for start in range(0, int(duration), 20) if start + 20 <= duration]


def family_for(sample_id):
    return next((name for name in FAMILIES if name in sample_id), None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("documents", "align"))
    parser.add_argument("--output", type=Path, default=Path("/expanded"))
    args = parser.parse_args()
    documents_dir = args.output / "documents"
    documents_dir.mkdir(parents=True, exist_ok=True)
    if args.action == "documents":
        for name in sorted({name for names in FAMILIES.values() for name in names}):
            path = documents_dir / f"{name}.json"
            document = prepare_document(json.loads((Path("/extracted") / f"{name}.json").read_text()), Path("/source-documents"))
            if path.exists() and json.loads(path.read_text()) != document:
                raise ValueError("Prepared publisher document changed")
            atomic_json(path, document)
        print(json.dumps({"prepared_documents": len(list(documents_dir.glob('*.json')))}))
        return
    documents = {p.stem: json.loads(p.read_text()) for p in documents_dir.glob("*.json")}
    if set(documents) != {name for names in FAMILIES.values() for name in names}:
        raise ValueError("Prepare every required document first")
    paths = {split: Path("/train-dev") / f"{split}.jsonl" for split in ("train", "dev")}
    source = [s for p in paths.values() for s in load_manifest(p)]
    validate_groups(source)  # Complete original train/dev graph; no test references.
    parents = [s for s in source if s.variant_of is None and family_for(s.sample_id)]
    variants = {s.variant_of: s for s in source if s.variant_of}
    if any(s.split not in {"train", "dev"} for s in source):
        raise ValueError("No test or unassigned samples may enter expanded preparation")
    manifest = local_model_manifest("small")
    plan = {
        "version": "publisher-expanded-v1", "source_families": FAMILIES, "method": METHOD,
        "selection": "every_complete_nonoverlapping_20_second_window_from_zero_no_ASR_based_selection",
        "source_manifest_sha256": {s: file_hash(p) for s, p in paths.items()},
        "source_audio_sha256": {s.sample_id: s.audio_sha256 for s in source if family_for(s.sample_id)},
        "code": {name: file_hash(Path(__file__).with_name(name)) for name in (Path(__file__).name, "publisher_alignment.py", "build_publisher_pairs.py")},
        "documents": {p.name: file_hash(p) for p in documents_dir.glob('*.json')},
        "alignment": {"model": "small", "precision": "float16", "device": "cuda", "manifest": manifest},
        "planned_windows": {s.sample_id: windows(s.duration_sec) for s in parents},
        "omitted_short_tails": {s.sample_id: {"start_sec": len(windows(s.duration_sec)) * 20, "end_sec": s.duration_sec} for s in parents},
        "excluded_sources": [{"id": s.sample_id, "reason": "outside_English_documented_checklist_scope_or_variant_of_excluded_source"} for s in source if not family_for(s.sample_id)],
        "threshold_policy": "unchanged_publisher_columns_and_whisper_dtw_v1",
        "training_budget": {"max_steps": 40, "eval_steps": 10, "rank": 8, "learning_rate": .0001, "seed": 55},
        "test_accessed": False, "quality_evidence": False, "selection_allowed": False,
        "human_verified": False, "previous_human_reviews_modified": False,
    }
    plan_path = args.output / "plan.json"
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError("Expanded preparation plan changed; preserve previous outputs")
    atomic_json(plan_path, plan)
    model = load_model("small", "cuda", "float16", digest(manifest))
    rows, diagnostics = [], []
    for parent in parents:
        paired_sources = [parent] + ([variants[parent.sample_id]] if parent.sample_id in variants else [])
        for s in paired_sources:
            if file_hash(settings.audio_root / s.audio_path) != s.audio_sha256:
                raise ValueError("Source audio checksum mismatch")
        for start, duration in windows(parent.duration_sec):
            sample_id = digest({"source": parent.sample_id, "window": [start, start + duration]})[:32]
            path = settings.audio_root / "publisher-expanded-clips-v1" / f"{sample_id}.wav"
            audio = clip(parent, start, duration, path)
            proposal_path = args.output / "proposals" / f"{sample_id}.json"
            if proposal_path.exists():
                proposal = json.loads(proposal_path.read_text())
            else:
                segments, info = model.transcribe(audio, beam_size=5, temperature=0, task="transcribe", vad_filter=False,
                                                  word_timestamps=True, condition_on_previous_text=True)
                draft = " ".join(s.text.strip() for s in segments)
                ranked = sorted(FAMILIES[family_for(parent.sample_id)], key=lambda name: -locate(draft, documents[name])["matched_tokens"])
                proposal = align(model, audio, documents[ranked[0]], draft, start)
                proposal.update(sample_id=sample_id, draft=draft, detected_language=info.language,
                                source_sample_id=parent.sample_id, split=parent.split, start_sec=start,
                                plan_sha256=file_hash(plan_path), source_audio_sha256=parent.audio_sha256)
                # English document does not justify training on a French or other-language utterance.
                if info.language != "en":
                    proposal["reasons"].append("non_English_or_uncertain_detected_language")
                    proposal["eligible_for_exploratory_training"] = False
                atomic_json(proposal_path, proposal)
            if proposal["plan_sha256"] != file_hash(plan_path):
                raise ValueError("Proposal belongs to another frozen plan")
            for src in paired_sources:
                identity = digest({"source": src.sample_id, "window": [start, start + duration]})[:32]
                path = settings.audio_root / "publisher-expanded-clips-v1" / f"{identity}.wav"
                if src != parent:
                    clip(src, start, duration, path)
                item = src.model_copy(deep=True, update={
                    "sample_id": identity, "audio_path": str(path.relative_to(settings.audio_root)),
                    "audio_sha256": file_hash(path), "decoded_audio_sha256": decoded_audio_hash([path]),
                    "duration_sec": duration, "channel": 0, "group_id": None,
                    "original_utterance_id": f"{parent.original_utterance_id}@{start}:{start+duration}",
                    "variant_of": sample_id if src != parent else None, "primary": False, "clean_control": False,
                    "scope": "read_cockpit", "scope_verified": False, "language": "en",
                    "reference_text": proposal["text"] or None, "transcript_status": "weak" if proposal["text"] else "missing",
                    "annotation_provenance": {"method": METHOD, "publisher_transcript": True, "reviewed_audio": False,
                        "annotator": None, "source_file": proposal["source_file"], "source_sha256": proposal["source_sha256"],
                        "alignment_sha256": file_hash(proposal_path), "preparation_plan_sha256": file_hash(plan_path),
                        "parent_group_id": src.group_id, "source_sample_id": src.sample_id,
                        "original_start_sec": start, "original_end_sec": start + duration,
                        "automatic_training_eligible": proposal["eligible_for_exploratory_training"],
                        "eligibility_reasons": proposal["reasons"], "language_basis": "English document and machine language screen, not human verification",
                        "paired_target_from_clean_original": src != parent},
                })
                rows.append(item)
                diagnostics.append({"id": identity, "source": src.sample_id, "split": src.split,
                                    "eligible": proposal["eligible_for_exploratory_training"], "reasons": proposal["reasons"]})
            if len(diagnostics) % 10 == 0:
                print(json.dumps({"prepared": len(diagnostics), "source": parent.sample_id, "start_sec": start}), flush=True)
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
        "finished_at": now().isoformat(), "plan_sha256": file_hash(plan_path), "groups": groups,
        "total_rows": len(rows), "eligible_train": len(train), "eligible_dev": len(dev), "items": diagnostics,
        "human_verified": 0, "quality_evidence": False, "test_accessed": False,
        "limitations": ["Automatic alignment is not independent evaluation gold", "Numeric disagreement remains rejected",
                        "Original train/dev assignment unchanged; repeated scripts are not script-disjoint",
                        "Final tails under 20 seconds are held, not padded or given invented words"]})
    print(json.dumps({"rows": len(rows), "eligible_train": len(train), "eligible_dev": len(dev), "groups": groups}, indent=2))


if __name__ == "__main__":
    main()
