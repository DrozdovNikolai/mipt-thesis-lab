"""Keep all unique C recordings for review, preserving the existing split identities."""

import json
import re
from pathlib import Path

import soundfile as sf

from north55_speech.core import atomic_json, digest, file_hash
from north55_speech.datasets import (
    annotation_template,
    import_local,
    load_manifest,
    publish_partitions,
    validate_groups,
    verify_partition_proof,
    write_manifest,
)

source = Path("/data/input/bleriot")
prior = Path("/data/curated/bleriot-v1")
output = Path("/data/curated/bleriot-v2")
if output.exists():
    raise ValueError("The v2 output must be new")
proof = json.loads((prior/"manifests/protocol/partition-proof.json").read_text())
verify_partition_proof(proof)
membership = {row["sample_id"]: split for split, rows in proof["partitions"].items() for row in rows}
all_prior = load_manifest(prior/"manifest.jsonl")
raw = {}
for sample in all_prior:
    sample.split = membership[digest(sample.sample_id)[:32]]
    if sample.source_dataset == "BLeRIOT-A":
        name = sample.sample_id.split(":", 1)[1] + ".wav"
        sample.audio_path = str(source/"verified/a/raw-speech"/name)
        raw[name] = sample
samples = list(raw.values())
linkage = json.loads(Path("/reports/bleriot-linkage-v2.json").read_text())
links = {row["c"]: row for row in linkage["rows"]}
paths = sorted((source/"verified/c").rglob("*.wav"))
seen: dict[str, str] = {}
duplicates, pending = [], []
# Prefer the publisher filename that identifies the actual DGA parent over its
# misleading BEA alias. The exclusion is based on exact bytes, never ASR errors.
paths.sort(key=lambda path: (links[path.name]["metadata_candidate"] is None, path.name))
for path in paths:
    checksum = file_hash(path)
    if checksum in seen:
        duplicates.append({"excluded_alias": path.name, "retained": seen[checksum], "sha256": checksum,
                           "reason": "exact_byte_duplicate_with_misleading_filename"})
        continue
    seen[checksum] = path.name
    link = links[path.name]
    key = re.sub(r"_sp(\d+)(?=\.wav$)", lambda match: f"_sp{int(match[1]):03d}",
                 path.name.removeprefix("CVR_"))
    if key not in raw or link["best"]["a"] != key:
        raise ValueError(f"Unresolved unique source parent: {path.name}")
    parent = raw[key]
    duration = sf.info(path).duration
    if abs(duration-parent.duration_sec) > 0.1:
        raise ValueError("Unresolved source timeline")
    if link["status"] != "ACOUSTICALLY_CONFIRMED":
        pending.append(path.name)
    sample = parent.model_copy(update={
        "sample_id": f"bleriot-c:{path.stem}", "audio_path": str(path), "audio_sha256": checksum,
        "decoded_audio_sha256": None, "source_dataset": "BLeRIOT-C", "duration_sec": duration,
        "variant_of": parent.sample_id, "acoustic_condition": "publisher_CVR_simulation_single_chain",
        "provenance": "BLeRIOT-C 10.57745/ASYVFP v1.0; local noncommercial diploma research",
        "augmentation": {"type": "publisher_audio_chain", "parent_link_status": link["status"],
                         "parent_evidence": "publisher filename, exact duration and highest acoustic coherence",
                         "grouping_policy": "conservative same-parent grouping even when review remains",
                         "source_sha256": parent.audio_sha256, "linkage_report_sha256": file_hash(Path('/reports/bleriot-linkage-v2.json'))},
    })
    samples.append(sample)
validate_groups(samples)
initial = source / "manifest.review-v2.jsonl"
if initial.exists():
    raise ValueError("The source manifest revision must be new")
write_manifest(initial, samples)
output.mkdir(parents=True)
import_report = import_local(initial, Path("/data/input"), output/"manifest.jsonl")
curated = load_manifest(output/"manifest.jsonl")
partitions = publish_partitions(curated, output/"manifests")
for split in ("train", "dev"):
    annotation_template(output/f"manifests/train-dev/{split}.jsonl", output/f"annotation/{split}.jsonl")
old_groups = {sample.sample_id: sample.group_id for sample in all_prior}
if any(sample.group_id != old_groups[sample.sample_id] for sample in curated if sample.sample_id in old_groups):
    raise ValueError("Existing group identities changed")
report = {
    "status": "ALL_UNIQUE_RECORDINGS_PREPARED_FOR_REVIEW", "recordings": len(curated),
    "raw": len(raw), "unique_noisy": len(seen), "duplicates": duplicates,
    "parent_acoustic_review_pending": pending, "no_noise_difficulty_exclusions": True,
    "existing_groups_unchanged": True, "import": import_report, "partitions": partitions,
    "test_gold_opened": False, "human_verified_annotations": 0, "benchmark_admitted": False,
    "counts": {split: sum(s.split == split for s in curated) for split in ("train", "dev", "test")},
}
atomic_json(Path("/reports/bleriot-preparation-v2.json"), report)
print(json.dumps(report))
