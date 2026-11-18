"""Fetch the MIT-labelled Boeing training file only; preserve native annotations."""

import hashlib
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REVISION = "36832b83a85b15936b6f2dd15c7cd886194a9535"
FILENAME = "train.10.23.bio.json"
GIT_BLOB = "3c414e83e464efcc677e40e62c9466d26dbf6f48"
SIZE = 986339


def main():
    target = Path("data/input/boeing-ner-v1")
    target.mkdir(parents=True, exist_ok=True)
    path = target / FILENAME
    url = f"https://huggingface.co/datasets/boeing/aviation-ner-BIO/resolve/{REVISION}/{FILENAME}"
    if path.exists():
        body = path.read_bytes()
    else:
        with urllib.request.urlopen(url, timeout=25) as response:
            body = response.read(SIZE + 1)
    actual_git_blob = hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()
    if len(body) != SIZE or actual_git_blob != GIT_BLOB:
        raise ValueError("Publisher Git blob/length verification failed")
    data = json.loads(body)
    if not isinstance(data, list) or not data or not all(isinstance(row, dict) for row in data):
        raise ValueError("Expected a nonempty JSON record list")
    if not path.exists():
        path.write_bytes(body)
    audit = Path("reports/direct-data-search-v1")
    result = {"checked_at": datetime.now(UTC).isoformat(), "source": "boeing/aviation-ner-BIO",
              "revision": REVISION, "url": url, "path": str(path), "bytes": len(body),
              "sha256": hashlib.sha256(body).hexdigest(), "publisher_git_blob": GIT_BLOB,
              "publisher_hash_verified": True, "license": "MIT (dataset card)",
              "license_evidence": "followup/boeing-aviation-ner-BIO-card.response",
              "rows": len(data), "fields": sorted({key for row in data for key in row}),
              "source_split": "train", "test_downloaded": False, "audio_present": False,
              "scope": "service_difficulty_reports_text_only_auxiliary_NER",
              "human_annotation_provenance": "NOT_ESTABLISHED",
              "project_event_labels": False, "project_critical_entity_gold": False,
              "training_executed": False, "admission": "AUXILIARY_SOURCE_NATIVE_INSPECTION_ONLY"}
    (audit / "boeing-acquisition.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
