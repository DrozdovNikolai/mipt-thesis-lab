"""Export immutable, eligible train/dev revisions after actual human review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from north55_speech.core import atomic_json, digest, file_hash
from north55_speech.datasets import load_manifest, validate_groups, write_manifest
from north55_speech.training import check_training_partitions


def collect(packet: Path, task: str) -> tuple[list, list, list]:
    accepted, pending, revisions = [], [], []
    originals_by_split = {split: load_manifest(packet/f"{split}.jsonl") for split in ("train", "dev")}
    if any(s.split != split for split, rows in originals_by_split.items() for s in rows):
        raise ValueError("Only train/dev annotations may be exported")
    # Group identity comes from the complete packet, including unreviewed linked windows.
    # Recomputing the graph on accepted rows would rename groups or lose variant parents.
    validate_groups([s for rows in originals_by_split.values() for s in rows])
    immutable = ("sample_id", "audio_path", "audio_sha256", "source_dataset", "recording_id", "session_id",
                 "speaker_ids", "original_utterance_id", "group_id", "split", "variant_of", "duration_sec",
                 "rights_confirmed", "license_id", "provenance", "speech_origin")
    for split in ("train", "dev"):
        for original in originals_by_split[split]:
            if original.split != split:
                raise ValueError("Only train/dev annotations may be exported")
            paths = sorted((packet/"revisions"/original.sample_id).glob("revision-*.json"))
            reasons = []
            if not paths:
                pending.append({"id": original.sample_id, "split": split, "reasons": ["no_human_revision"]})
                continue
            record = json.loads(paths[-1].read_text(encoding="utf-8"))
            sample = type(original).model_validate(record["sample"])
            if any(getattr(original, key) != getattr(sample, key) for key in immutable):
                raise ValueError("A review changed an immutable source identity")
            if digest(sample.model_dump()) != record["audit"]["after_sha256"]:
                raise ValueError("Annotation revision checksum mismatch")
            required = {"scope", "transcript"} | ({"events"} if task == "events" else set())
            if not required <= set(record["audit"]["verified_tasks"]):
                reasons.append("missing_verified_tasks")
            provenance = sample.annotation_provenance
            if (not provenance.get("reviewed_audio") or not provenance.get("annotator")
                    or provenance.get("verification_method") != "identified_human_self_attestation"
                    or provenance["annotator"] != record["audit"]["actor"]):
                reasons.append("missing_identified_human_audio_review")
            if not sample.rights_confirmed or sample.speech_origin != "recorded_human":
                reasons.append("unverified_rights_or_human_origin")
            if not sample.scope_verified or sample.scope not in {"cockpit", "read_cockpit", "simulator"}:
                reasons.append("scope_outside_crew_training")
            if sample.language not in {"en", "ru", "mixed"}:
                reasons.append("language_outside_requested_training_scope")
            if sample.transcript_status != "human_verified" or sample.reference_text is None:
                reasons.append("missing_human_transcript")
            if task == "asr" and (sample.duration_sec > 30 or not sample.reference_text):
                reasons.append("asr_requires_nonempty_aligned_text_and_at_most_30_seconds")
            if task == "events" and (sample.events_status != "human_verified" or sample.labels is None
                                      or sample.salient_for_review is None):
                reasons.append("missing_human_event_or_salience_labels")
            if reasons:
                pending.append({"id": sample.sample_id, "split": split, "reasons": reasons})
            else:
                accepted.append(sample)
                revisions.append({"id": sample.sample_id, "file": str(paths[-1].relative_to(packet)),
                                  "sha256": file_hash(paths[-1])})
    # Every accepted group_id was checked against its immutable full-packet original above.
    return accepted, pending, revisions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task", choices=["asr", "events"], required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    accepted, pending, revisions = collect(args.packet, args.task)
    train, dev = [s for s in accepted if s.split == "train"], [s for s in accepted if s.split == "dev"]
    enough = bool(train and dev)
    if args.task == "events" and len({s.salient_for_review for s in train}) < 2:
        enough = False
    report = {"status": "READY_FOR_TRAINING_ATTEMPT" if enough else "NEEDS_MORE_DATA", "task": args.task,
              "eligible_train": len(train), "eligible_dev": len(dev), "pending": pending,
              "source_revisions": revisions, "training_executed": False, "quality_evidence": False,
              "test_data_accessed": False, "output": None}
    if enough:
        check_training_partitions(train, dev)
        if args.output.exists():
            raise ValueError("Choose a new immutable output version")
        args.output.mkdir(parents=True)
        write_manifest(args.output/"train.jsonl", train)
        write_manifest(args.output/"dev.jsonl", dev)
        report["output"] = str(args.output)
        atomic_json(args.output/"provenance.json", report)
    atomic_json(args.report, report)
    print(json.dumps({"status": report["status"], "eligible_train": len(train), "eligible_dev": len(dev)}))
    return 0 if enough else 4


if __name__ == "__main__":
    raise SystemExit(main())
