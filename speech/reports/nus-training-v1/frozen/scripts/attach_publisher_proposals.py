"""Add separate script proposals to an existing packet without changing human revisions."""

import argparse
import json
from pathlib import Path

from north55_speech.core import atomic_json, file_hash
from north55_speech.datasets import load_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publisher", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    proposals = {}
    for split in ("train", "dev"):
        for sample in load_manifest(args.publisher / "all" / f"{split}.jsonl"):
            if sample.split != split:
                raise ValueError("Expected train/dev only")
            path = args.publisher / "proposals" / f"{sample.variant_of or sample.sample_id}.json"
            proposal = json.loads(path.read_text())
            proposals[sample.sample_id] = {**proposal, "sample_id": sample.sample_id, "split": split,
                "source_sample_id": sample.annotation_provenance["source_sample_id"],
                "original_start_sec": sample.annotation_provenance["original_start_sec"],
                "alignment_sha256": file_hash(path), "paired_variant": sample.variant_of is not None}
    attached = []
    for split in ("train", "dev"):
        for sample in load_manifest(args.packet / f"{split}.jsonl"):
            if sample.split != split:
                raise ValueError("Only train/dev annotation packets are supported")
            if sample.sample_id not in proposals:
                continue
            proposal = proposals[sample.sample_id]
            if proposal["source_sample_id"] != sample.annotation_provenance["source_sample_id"] or proposal["split"] != split:
                raise ValueError("Source identity mismatch")
            proposal["target_source_audio_sha256"] = sample.annotation_provenance["source_audio_sha256"]
            path = args.packet / "publisher-proposals" / f"{sample.sample_id}.json"
            if path.exists() and json.loads(path.read_text()) != proposal:
                raise ValueError("Preserve the previous proposal version")
            atomic_json(path, proposal)
            attached.append({"id": sample.sample_id, "eligible": proposal["eligible_for_exploratory_training"],
                             "nonempty": bool(proposal["text"])})
    atomic_json(args.report, {"status": "ATTACHED", "items": attached, "human_revision_writes": 0,
                             "test_accessed": False, "original_manifest_writes": 0})
    print(json.dumps({"status": "ATTACHED", "count": len(attached), "human_revision_writes": 0}))


if __name__ == "__main__":
    main()
