from __future__ import annotations

import csv
import hashlib
import json
import random
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from north55_speech.audio import AudioPreprocessor
from north55_speech.core import (
    SpeechError,
    StrictModel,
    atomic_json,
    confined,
    digest,
    file_hash,
    settings,
)
from north55_speech.schemas import InferenceRequest

AnnotationStatus = Literal["missing", "machine", "weak", "human_verified"]


class Sample(StrictModel):
    sample_id: str = Field(min_length=1)
    audio_path: str
    audio_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    decoded_audio_sha256: str | None = None
    source_dataset: str
    source_version: str
    recording_id: str
    session_id: str
    original_utterance_id: str
    speaker_ids: list[str] = Field(default_factory=list)
    script_id: str | None = None
    language: str
    input_language: Literal["en", "ru", "mixed", "auto"] = "auto"
    scope: Literal[
        "cockpit", "simulator", "read_cockpit", "atc", "unknown", "general_control", "non_speech"
    ]
    scope_verified: bool = False
    speech_origin: Literal["recorded_human", "synthetic", "noise", "unknown"]
    acoustic_condition: str = "original"
    variant_of: str | None = None
    duration_sec: float = Field(gt=0)
    channel: int = Field(default=0, ge=0, lt=8)
    license_id: str = Field(min_length=1)
    provenance: str = Field(min_length=1)
    rights_confirmed: bool
    transcript_status: AnnotationStatus = "missing"
    entities_status: AnnotationStatus = "missing"
    events_status: AnnotationStatus = "missing"
    temporal_status: AnnotationStatus = "missing"
    diarization_status: AnnotationStatus = "missing"
    reference_text: str | None = None
    critical_entities: list[dict] | None = None
    events: list[dict] | None = None
    labels: list[str] | None = None
    salient_for_review: bool | None = None
    unintelligible: list[dict] = Field(default_factory=list)
    continuous_recording: bool = False
    primary: bool = True
    clean_control: bool = False
    group_id: str | None = None
    split: Literal["train", "dev", "test", "unassigned"] = "unassigned"
    annotation_provenance: dict = Field(default_factory=dict)
    augmentation: dict | None = None

    @model_validator(mode="after")
    def annotations(self):
        if not self.rights_confirmed:
            raise ValueError("Rights to use this recording must be confirmed")
        for status, value in [
            (self.transcript_status, self.reference_text),
            (self.entities_status, self.critical_entities),
            (self.events_status, self.labels),
            (self.temporal_status, self.events),
        ]:
            if status == "human_verified" and value is None:
                raise ValueError("Verified annotation cannot be absent")
        return self


def load_manifest(path: Path) -> list[Sample]:
    if path.suffix.casefold() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            data = []
            for row in csv.DictReader(f):
                parsed = {}
                for key, value in row.items():
                    try:
                        parsed[key] = json.loads(value)
                    except (ValueError, TypeError):
                        parsed[key] = value
                data.append(parsed)
    else:
        data = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    samples = [Sample.model_validate(row) for row in data]
    if len({s.sample_id for s in samples}) != len(samples):
        raise SpeechError("DUPLICATE_SAMPLE_ID", "Manifest contains duplicate sample IDs")
    return samples


def write_manifest(path: Path, samples: list[Sample]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(s.model_dump_json() + "\n" for s in samples), encoding="utf-8")
    temporary.replace(path)


def validate_groups(samples: list[Sample], assign: bool = False, seed: int = 55) -> dict:
    """Connected components, including transitive shared-speaker and variant constraints."""
    parents = list(range(len(samples)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    seen: dict[tuple[str, str], int] = {}
    sample_ids = {s.sample_id: index for index, s in enumerate(samples)}
    for i, sample in enumerate(samples):
        constraints = [
            ("session", sample.session_id),
            ("recording", sample.recording_id),
            ("original", sample.original_utterance_id),
            ("sha", sample.audio_sha256),
        ]
        if sample.decoded_audio_sha256:
            constraints.append(("decoded", sample.decoded_audio_sha256))
        constraints.extend(("speaker", speaker) for speaker in sample.speaker_ids)
        for key in constraints:
            if key in seen:
                parents[root(i)] = root(seen[key])
            else:
                seen[key] = i
        if sample.variant_of:
            if sample.variant_of not in sample_ids:
                raise SpeechError(
                    "MISSING_VARIANT_PARENT",
                    "All variants require their original in the full manifest",
                )
            parents[root(i)] = root(sample_ids[sample.variant_of])
    components: dict[int, list[Sample]] = defaultdict(list)
    for i, sample in enumerate(samples):
        components[root(i)].append(sample)
    groups = sorted(components.values(), key=lambda group: min(s.sample_id for s in group))
    random.Random(seed).shuffle(groups)
    boundaries = (max(1, int(len(groups) * 0.7)), max(2, int(len(groups) * 0.85)))
    for index, group in enumerate(groups):
        # Stable under augmentation: adding a variant does not create a new independent group.
        group_id = digest(
            {
                "originals": sorted({s.original_utterance_id for s in group}),
                "recordings": sorted({s.recording_id for s in group}),
                "sessions": sorted({s.session_id for s in group}),
                "speakers": sorted({speaker for s in group for speaker in s.speaker_ids}),
            }
        )[:24]
        partitions = {s.split for s in group} - {"unassigned"}
        if len(partitions) > 1:
            raise SpeechError(
                "SPLIT_LEAKAGE", "Connected speaker/session/original/duplicate group crosses splits"
            )
        for sample in group:
            if not assign and sample.group_id and sample.group_id != group_id:
                raise SpeechError(
                    "GROUP_TAMPERING", "Stored group ID does not match the split graph"
                )
            sample.group_id = group_id
            if assign:
                sample.split = (
                    "train" if index < boundaries[0] else "dev" if index < boundaries[1] else "test"
                )
    scripts: dict[str, set[str]] = defaultdict(set)
    for sample in samples:
        if sample.script_id:
            scripts[sample.script_id].add(sample.split)
    return {
        "independent_groups": len(groups),
        "split_groups": {
            split: len({s.group_id for s in samples if s.split == split})
            for split in ("train", "dev", "test")
        },
        "unknown_speakers": sum(not s.speaker_ids for s in samples),
        "script_overlap": {k: sorted(v) for k, v in scripts.items() if len(v) > 1},
        "claim_limitation": "unknown speakers cannot establish speaker-disjoint generalization"
        if any(not s.speaker_ids for s in samples)
        else None,
    }


def decoded_audio_hash(paths: list[Path]) -> str:
    import soundfile as sf

    h = hashlib.sha256()
    h.update(json.dumps({"rate": 16000, "channels": len(paths)}, sort_keys=True).encode())
    for path in paths:
        with sf.SoundFile(path) as stream:
            for block in stream.blocks(16000 * 30, dtype="float32"):
                h.update(block.astype("<f4").tobytes())
    return h.hexdigest()


def import_local(manifest: Path, allowed_root: Path, output: Path) -> dict:
    manifest = confined(allowed_root, manifest)
    samples = load_manifest(manifest)
    for sample in samples:
        source = confined(allowed_root, sample.audio_path)
        if file_hash(source) != sample.audio_sha256:
            raise SpeechError("AUDIO_CHECKSUM_MISMATCH", "Imported audio differs from manifest")
        with tempfile.TemporaryDirectory() as tmp:
            info, paths = AudioPreprocessor().prepare(source, Path(tmp), "separate_channels")
            sample.decoded_audio_sha256 = decoded_audio_hash(paths)
            if abs(info.duration_sec - sample.duration_sec) > 0.1:
                raise SpeechError(
                    "DURATION_MISMATCH", "Manifest duration differs from decoded audio"
                )
        # Opaque path prevents semantic filename hints; no reference files enter worker mounts.
        locator = f"datasets/{digest(sample.sample_id)}/original"
        destination = confined(settings.audio_root, locator, must_exist=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and file_hash(destination) != sample.audio_sha256:
            raise SpeechError("IMMUTABLE_AUDIO_CONFLICT", "Sample ID already has different audio")
        if not destination.exists():
            temporary = destination.with_suffix(".tmp")
            shutil.copyfile(source, temporary)
            temporary.replace(destination)
        sample.audio_path = locator
    report = validate_groups(samples)
    write_manifest(output, samples)
    atomic_json(output.with_suffix(".import.json"), report | {"manifest_sha256": file_hash(output)})
    return report


def inference_projection(sample: Sample) -> InferenceRequest:
    # Input language is explicitly runtime-available, never inferred from reference language.
    return InferenceRequest(
        sample_id=digest(sample.sample_id)[:32],
        audio_locator=sample.audio_path,
        audio_sha256=sample.audio_sha256,
        language=sample.input_language,
        channel_mode="separate_channels",
        audio_channel=sample.channel,
    )


def prepare_splits(manifest: Path, output: Path) -> dict:
    samples = load_manifest(manifest)
    if any(s.split != "unassigned" for s in samples):
        raise SpeechError(
            "SPLITS_ALREADY_ASSIGNED", "Repartitioning an existing dataset is forbidden"
        )
    report = validate_groups(samples, assign=True)
    return publish_partitions(samples, output, report)


def publish_partitions(samples: list[Sample], output: Path, report: dict | None = None) -> dict:
    """Publish already assigned groups after annotation/augmentation, before any test opening."""
    if any(s.split == "unassigned" for s in samples):
        raise SpeechError("SPLITS_REQUIRED", "Assign groups before publishing projections")
    report = report or validate_groups(samples)
    if (output / "protocol" / "partition-proof.json").exists():
        raise SpeechError(
            "PARTITION_EXISTS", "Publish a new protocol directory; never overwrite a freeze"
        )
    sealed = output.parent / "sealed"
    if any((sealed / name).exists() for name in ("full-manifest.jsonl", "test.jsonl")):
        raise SpeechError(
            "SEALED_PARTITION_EXISTS",
            "Use a fresh protocol parent directory; existing sealed answers are immutable",
        )
    write_manifest(sealed / "full-manifest.jsonl", samples)
    for split in ("train", "dev"):
        write_manifest(
            output / "train-dev" / f"{split}.jsonl", [s for s in samples if s.split == split]
        )
    test = [s for s in samples if s.split == "test"]
    # Sealed references are outside the tools/train/dev mount tree.
    write_manifest(sealed / "test.jsonl", test)
    inference_dir = output / "test-inference"
    inference_dir.mkdir(parents=True, exist_ok=True)
    (inference_dir / "test.jsonl").write_text(
        "".join(inference_projection(s).model_dump_json() + "\n" for s in test), encoding="utf-8"
    )
    atomic_json(output / "split-report.json", report)
    proof = {
        "schema_version": "1.0",
        "full_manifest_sha256": file_hash(sealed / "full-manifest.jsonl"),
        "test_references_sha256": file_hash(sealed / "test.jsonl"),
        "partitions": {
            split: [partition_identity(s) for s in samples if s.split == split]
            for split in ("train", "dev", "test")
        },
        "split_report": report,
    }
    atomic_json(output / "protocol" / "partition-proof.json", proof)
    return report


def partition_identity(sample: Sample) -> dict:
    return {
        "sample_id": digest(sample.sample_id)[:32],
        "group_id": sample.group_id,
        "session": digest(sample.session_id),
        "recording": digest(sample.recording_id),
        "original": digest(sample.original_utterance_id),
        "speakers": [digest(s) for s in sample.speaker_ids],
        "audio_sha256": sample.audio_sha256,
        "decoded_audio_sha256": sample.decoded_audio_sha256,
    }


def verify_partition_proof(
    proof: dict, samples: list[Sample] | None = None, split: str | None = None
) -> None:
    partitions = proof["partitions"]
    for left, right in (("train", "dev"), ("train", "test"), ("dev", "test")):
        for key in (
            "group_id",
            "session",
            "recording",
            "original",
            "audio_sha256",
            "decoded_audio_sha256",
            "speakers",
        ):

            def values(partition, field=key):
                result = set()
                for row in partitions[partition]:
                    value = row[field]
                    result.update(value if isinstance(value, list) else [value])
                return result - {None}

            if values(left) & values(right):
                raise SpeechError(
                    "SPLIT_LEAKAGE", f"Partition proof shares {key} across {left}/{right}"
                )
    if samples is not None:
        actual = sorted((partition_identity(s) for s in samples), key=lambda row: row["sample_id"])
        expected = sorted(partitions[split], key=lambda row: row["sample_id"])
        if actual != expected:
            raise SpeechError(
                "PARTITION_PROOF_MISMATCH", "Samples do not match the frozen curator proof"
            )


def annotation_template(manifest: Path, output: Path) -> None:
    samples = load_manifest(manifest)
    # No automatic upgrading of suggestions to human ground truth.
    for sample in samples:
        sample.annotation_provenance = {
            "guide": "annotation_guide_v1",
            "annotator": None,
            "reviewed_audio": False,
            "adjudicator": None,
        }
    write_manifest(output, samples)


def import_annotations(manifest: Path, annotations: Path, output: Path) -> None:
    original = {s.sample_id: s for s in load_manifest(manifest)}
    revised = load_manifest(annotations)
    mutable = {
        "reference_text",
        "critical_entities",
        "events",
        "labels",
        "salient_for_review",
        "transcript_status",
        "entities_status",
        "events_status",
        "temporal_status",
        "diarization_status",
        "unintelligible",
        "annotation_provenance",
    }
    for sample in revised:
        prior = original.get(sample.sample_id)
        if prior is None or prior.model_dump(exclude=mutable) != sample.model_dump(exclude=mutable):
            raise SpeechError(
                "ANNOTATION_IDENTITY_CHANGED", "Annotations cannot alter audio or frozen groups"
            )
        if any(
            getattr(sample, field) == "human_verified"
            for field in (
                "transcript_status",
                "entities_status",
                "events_status",
                "temporal_status",
            )
        ):
            if not sample.annotation_provenance.get(
                "annotator"
            ) or not sample.annotation_provenance.get("reviewed_audio"):
                raise SpeechError(
                    "MISSING_HUMAN_PROVENANCE",
                    "Human verification requires an identified annotator and listened audio",
                )
        original[sample.sample_id] = sample
    if output.exists():
        raise SpeechError(
            "IMMUTABLE_ANNOTATION_REVISION", "Write annotations to a new revision path"
        )
    write_manifest(output, list(original.values()))
    atomic_json(
        output.with_suffix(".audit.json"),
        {
            "before_sha256": file_hash(manifest),
            "annotation_sha256": file_hash(annotations),
            "after_sha256": file_hash(output),
        },
    )
