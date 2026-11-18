"""Prepare quarantined BLeRIOT manifests and review partitions inside the CPU image.

Uses actual archive contents and publisher speaker metadata. Does not read script
text, generate gold labels, claim language/scope verification, or open test answers.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import numpy as np
import soundfile as sf

from north55_speech.core import atomic_json, file_hash
from north55_speech.datasets import (
    Sample,
    annotation_template,
    import_local,
    prepare_splits,
    write_manifest,
)


def envelope(path: Path) -> np.ndarray:
    with sf.SoundFile(path) as stream:
        window = stream.samplerate // 50
        values = [
            np.sqrt(np.mean(block.astype(np.float64) ** 2))
            for block in stream.blocks(blocksize=window, dtype="float32", always_2d=True)
        ]
    return np.asarray(values)


def main() -> None:
    source = Path("/data/input/bleriot")
    raw_root, noisy_root = source / "verified/a", source / "verified/c"
    output = Path("/data/curated/bleriot-v1")
    if output.exists():
        raise ValueError("Preparation output is immutable; use a fresh protocol revision")
    metadata_path = source / "bleriot-a/raw-speech_metadata.csv"
    metadata = {row["FileName"]: row for row in csv.DictReader(metadata_path.open())}
    extracted = {
        corpus: json.loads((source / f"verified/{corpus}/extraction.json").read_text())
        for corpus in ("a", "c")
    }
    archive_hashes = {key: value["archive_sha256"] for key, value in extracted.items()}
    raw = {path.name: path for path in raw_root.rglob("*.wav")}
    if set(raw) != set(metadata):
        raise ValueError("Raw audio names and publisher metadata differ")
    samples = []
    parents = {}
    durations = []
    audio_inventory = []
    for name, path in sorted(raw.items()):
        row, info = metadata[name], sf.info(path)
        if abs(info.duration - float(row["Duration_min"]) * 60) > 3.1:
            durations.append({"file": name, "publisher_minutes": row["Duration_min"],
                              "decoded_header_sec": info.duration})
        actual_hash = file_hash(path)
        expected = next(item["sha256"] for item in extracted["a"]["entries"]
                        if Path(item["path"]).name == name)
        if actual_hash != expected:
            raise ValueError("Extracted source modified after verification")
        sample = Sample(
            sample_id=f"bleriot-a:{path.stem}", audio_path=str(path), audio_sha256=actual_hash,
            source_dataset="BLeRIOT-A", source_version="1.0", recording_id=f"bleriot:{path.stem}",
            session_id=f"bleriot:reader:{row['SpeakerID']}",
            original_utterance_id=f"bleriot:{path.stem}", speaker_ids=[f"bleriot:{row['SpeakerID']}"],
            script_id=f"bleriot:{row['Subcorpus']}:{row['Content']}",
            language="unknown", input_language="auto", scope="unknown", scope_verified=False,
            speech_origin="recorded_human", duration_sec=info.duration, license_id="CC-BY-NC-4.0",
            provenance="BLeRIOT-A 10.57745/EWXJLT v1.0; publisher metadata; local noncommercial diploma research",
            rights_confirmed=True, primary=False, continuous_recording=True,
            annotation_provenance={"publisher_transcript_available": row["Transcription"] == "1",
                                   "reviewed_audio": False, "annotator": None,
                                   "session_identity": "conservative reader grouping; session dates unavailable"},
        )
        samples.append(sample)
        parents[name] = sample
        audio_inventory.append({"file": name, "corpus": "A", "duration_sec": info.duration,
                                "sample_rate": info.samplerate, "channels": info.channels,
                                "subtype": info.subtype, "sha256": actual_hash})
    paired, quarantined = [], []
    for path in sorted(noisy_root.rglob("*.wav")):
        key = re.sub(r"_sp(\d+)(?=\.wav$)", lambda match: f"_sp{int(match[1]):03d}",
                     path.name.removeprefix("CVR_"))
        parent = parents.get(key)
        info = sf.info(path)
        if parent is None or abs(parent.duration_sec - info.duration) > 0.1:
            quarantined.append({"file": path.name, "reason": "unresolved_parent_or_duration",
                                "sha256": file_hash(path), "duration_sec": info.duration})
            continue
        # Metadata linkage is supported by an independent acoustic envelope check.
        # Its threshold is fixed here before any ASR hypotheses or reference text.
        a, c = envelope(Path(parent.audio_path)), envelope(path)
        n = min(len(a), len(c))
        correlation = float(np.corrcoef(a[:n], c[:n])[0, 1])
        if not np.isfinite(correlation) or correlation < 0.5:
            quarantined.append({"file": path.name, "reason": "acoustic_parent_check_unconfirmed",
                                "proposed_parent": key, "envelope_pearson_r": correlation})
            continue
        actual_hash = file_hash(path)
        expected = next(item["sha256"] for item in extracted["c"]["entries"]
                        if Path(item["path"]).name == path.name)
        if actual_hash != expected:
            raise ValueError("Extracted source modified after verification")
        sample = parent.model_copy(update={
            "sample_id": f"bleriot-c:{path.stem}", "audio_path": str(path),
            "audio_sha256": actual_hash, "source_dataset": "BLeRIOT-C",
            "duration_sec": info.duration, "variant_of": parent.sample_id,
            "acoustic_condition": "publisher_CVR_simulation_single_chain",
            "provenance": "BLeRIOT-C 10.57745/ASYVFP v1.0; derived from A; local noncommercial diploma research",
        })
        samples.append(sample)
        paired.append({"a": key, "c": path.name, "duration_delta_sec": info.duration-parent.duration_sec,
                       "envelope_pearson_r": correlation, "speaker": parent.speaker_ids,
                       "group_policy": "same original, session and speaker as parent"})
        audio_inventory.append({"file": path.name, "corpus": "C", "duration_sec": info.duration,
                                "sample_rate": info.samplerate, "channels": info.channels,
                                "subtype": info.subtype, "sha256": actual_hash})
    initial = source / "manifest.review-v1.jsonl"
    if initial.exists():
        raise ValueError("Initial source manifest already exists")
    write_manifest(initial, samples)
    # Full decode, canonical-audio duplicate hash, opaque storage and leakage validation.
    output.mkdir(parents=True)
    curated = output / "manifest.jsonl"
    import_result = import_local(initial, Path("/data/input"), curated)
    split_result = prepare_splits(curated, output / "manifests")
    for split in ("train", "dev"):
        annotation_template(output / f"manifests/train-dev/{split}.jsonl",
                            output / f"annotation/{split}.jsonl")
    report = {
        "status": "PREPARED_FOR_REVIEW", "archive_hashes": archive_hashes,
        "raw_recordings": len(raw), "paired_variants": len(paired), "quarantined": quarantined,
        "pairs": paired, "audio_inventory": audio_inventory, "duration_metadata_discrepancies": durations,
        "publisher_documents": [item for item in extracted["a"]["entries"]
                                if Path(item["path"]).suffix != ".wav"],
        "import_result": import_result, "split_result": split_result,
        "human_verified_annotations": 0, "benchmark_admitted": False,
        "asr_quality_gate": "NEEDS_MORE_DATA", "nlp_quality_gate": "NEEDS_MORE_DATA",
        "test_opened": False, "candidate_selected": False,
        "next_step": "review scope and align publisher scripts; annotate independent entities/events",
    }
    atomic_json(Path("/reports/bleriot-preparation.json"), report)
    print(json.dumps({key: report[key] for key in (
        "status", "raw_recordings", "paired_variants", "quarantined", "split_result"
    )}), flush=True)


if __name__ == "__main__":
    main()
