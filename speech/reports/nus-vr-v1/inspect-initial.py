"""Offline, non-executable inspection of quarantined NUS Parquet audio/text pairs.

This produces no training/evaluation manifest, inferred labels or model predictions.
Embedded audio paths are recorded as provenance only and are never followed.
"""

import argparse
import hashlib
import io
import json
import math
import platform
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow
import pyarrow.parquet as pq
import soundfile as sf


def digest(body):
    return hashlib.sha256(body).hexdigest()


def normalized_reference(text):
    # No vocabulary substitutions, numeric conversions or punctuation deletion.
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def inspect_audio(payload):
    if not isinstance(payload, bytes) or not 0 < len(payload) <= 16 * 1024 * 1024:
        raise ValueError("Expected bounded embedded audio bytes")
    with sf.SoundFile(io.BytesIO(payload)) as source:
        if not (1 <= source.channels <= 8 and 8000 <= source.samplerate <= 192000
                and 0 < source.frames <= source.samplerate * 120):
            raise ValueError("Audio shape outside inspection limits")
        samples = source.read(dtype="float32", always_2d=True)
        if not np.isfinite(samples).all():
            raise ValueError("Non-finite audio")
        header = f"float32le:{source.samplerate}:{source.channels}:{source.frames}\0".encode()
        return {
            "audio_sha256": digest(payload),
            "pcm_sha256": digest(header + samples.astype("<f4").tobytes()),
            "sample_rate": source.samplerate, "channels": source.channels,
            "frames": source.frames, "duration_sec": source.frames / source.samplerate,
            "format": source.format, "subtype": source.subtype,
            "peak": float(np.abs(samples).max()),
            "rms": float(np.sqrt(np.mean(np.square(samples.astype("float64"))))),
        }


def duplicate_summary(records):
    by_pcm = defaultdict(list)
    for row in records:
        by_pcm[row["pcm_sha256"]].append(row)
    conflicts = []
    for pcm_hash, rows in by_pcm.items():
        if len({row["normalized_text_sha256"] for row in rows}) > 1:
            conflicts.append({"pcm_sha256": pcm_hash, "rows": [row["row_id"] for row in rows]})
    unique = [rows[0] for rows in by_pcm.values()]
    return {
        "unique_pcm_clips": len(unique), "duplicate_rows": len(records) - len(unique),
        "unique_audio_duration_sec": sum(row["duration_sec"] for row in unique),
        "unique_reference_words_first_occurrence": sum(row["reference_words"] for row in unique),
        "conflicting_reference_audio_groups": conflicts,
        "duplicate_groups": [[row["row_id"] for row in rows]
                             for rows in by_pcm.values() if len(rows) > 1],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquisition", type=Path, default=Path("reports/nus-vr-v1/acquisition.json"))
    parser.add_argument("--metadata", type=Path, default=Path("reports/nus-vr-v1/metadata"))
    parser.add_argument("--output", type=Path, default=Path("reports/nus-vr-v1/inspection.json"))
    parser.add_argument("--private-index", type=Path,
                        default=Path("data/quarantine/nus-vr-v1/inspection-index.json"))
    args = parser.parse_args()
    if args.output.exists() or args.private_index.exists():
        raise FileExistsError("Use new output paths to preserve prior audit measurements")
    acquisition = json.loads(args.acquisition.read_bytes())
    if acquisition.get("retrieval_status") != "PASS" or not acquisition["files"]:
        raise ValueError("Require a complete verified acquisition")
    records, failures, summaries = [], [], []
    for entry in acquisition["files"]:
        path = Path(entry["local_path"].replace("\\", "/"))
        body = path.read_bytes()
        if len(body) != entry["bytes"] or digest(body) != entry["sha256"]:
            raise ValueError(f"Quarantined file changed: {path.name}")
        parquet = pq.ParquetFile(io.BytesIO(body))
        if parquet.metadata.num_rows > 2000:
            raise ValueError("Unexpected row count")
        schema = parquet.schema_arrow
        file_summary = {"file": path.name, "rows": parquet.metadata.num_rows,
                        "schema": str(schema), "schema_metadata_keys": sorted(
                            key.decode("utf-8", errors="replace") for key in (schema.metadata or {})),
                        "decoded": 0, "duration_sec_including_duplicates": 0.0}
        summaries.append(file_summary)
        required = {"id", "audio", "text", "segment_start_time", "segment_end_time", "duration"}
        if not required.issubset(schema.names):
            failures.append({"file": path.name, "error": "Missing expected columns"})
            continue
        for index, row in enumerate(parquet.read().to_pylist()):
            row_id = f"{path.name}:{index}"
            try:
                text = row["text"]
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("Empty/non-string source reference")
                # External paths must not trigger local reads or network downloads.
                audio = inspect_audio(row["audio"]["bytes"])
                start, end, duration = (row[key] for key in
                                        ("segment_start_time", "segment_end_time", "duration"))
                if not all(isinstance(value, (int, float)) and math.isfinite(value)
                           for value in (start, end, duration)) or not 0 <= start < end:
                    raise ValueError("Invalid source time interval")
                record = {
                    "row_id": row_id, "file": path.name, "row_index": index,
                    "source_id": row["id"], "embedded_audio_path_untrusted": row["audio"].get("path"),
                    "source_reference_text": text,
                    "normalized_text_sha256": digest(normalized_reference(text).encode()),
                    "reference_words": len(text.split()),
                    "source_start_sec": start, "source_end_sec": end,
                    "declared_duration_sec": duration,
                    "interval_audio_delta_sec": (end - start) - audio["duration_sec"],
                    "declared_audio_delta_sec": duration - audio["duration_sec"],
                    "reference_status": "SOURCE_REFERENCE_NOT_PROJECT_VERIFIED",
                    "scope_status": "AUDIO_SCOPE_NOT_REVIEWED", "language_verified": False,
                    "speaker_id": None, "session_id": None,
                    "conservative_leakage_group": "nus-vr-entire-source-v1",
                    "admission": "QUARANTINE_RIGHTS_NOT_ESTABLISHED", **audio,
                }
                records.append(record)
                file_summary["decoded"] += 1
                file_summary["duration_sec_including_duplicates"] += audio["duration_sec"]
            except (KeyError, TypeError, ValueError, RuntimeError) as exc:
                failures.append({"row_id": row_id, "error": f"{type(exc).__name__}: {exc}"})
    duplicates = duplicate_summary(records)
    by_file = defaultdict(set)
    for row in records:
        by_file[row["file"]].add(row["pcm_sha256"])
    relationships = []
    for name, values in sorted(by_file.items()):
        for other, other_values in sorted(by_file.items()):
            if name < other and values & other_values:
                relationships.append({"left": name, "right": other,
                                      "shared_unique_pcm": len(values & other_values),
                                      "identical_audio_sets": values == other_values})
    repo = json.loads((args.metadata / "repository.response").read_bytes())
    tree = json.loads((args.metadata / "current-tree.response").read_bytes())
    permission_paths = [row["path"] for row in tree["tree"]
                        if re.search("license|licence|copying|permission|terms|consent", row["path"], re.I)]
    # Presence of a file/field is only a discovery signal; admission requires its review.
    rights = {"status": "BLOCKED", "reason": "SOURCE_USE_PERMISSION_NOT_ESTABLISHED",
              "github_license_metadata": repo.get("license"),
              "current_tree_sha": tree["sha"], "tree_complete": not tree["truncated"],
              "permission_file_candidates": permission_paths,
              "source_readme_reviewed": True, "public_visibility_is_not_training_permission": True}
    summary = {
        "checked_at": datetime.now(UTC).isoformat(),
        "source_revision": acquisition["revision"],
        "acquisition_sha256": digest(args.acquisition.read_bytes()),
        "script_sha256": digest(Path(__file__).read_bytes()),
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    "pyarrow": pyarrow.__version__, "soundfile": sf.__version__, "numpy": np.__version__},
        "files": summaries, "row_count": sum(row["rows"] for row in summaries),
        "decoded_rows": len(records), "failures": failures,
        "decode_status": "PASS" if records and not failures else "FAIL",
        "sample_rates": dict(Counter(row["sample_rate"] for row in records)),
        "channels": dict(Counter(row["channels"] for row in records)),
        "audio_formats": dict(Counter(row["format"] for row in records)),
        "min_clip_sec": min((row["duration_sec"] for row in records), default=None),
        "max_clip_sec": max((row["duration_sec"] for row in records), default=None),
        "zero_signal_rows": sum(row["peak"] == 0 for row in records),
        "interval_mismatch_over_20ms": sum(abs(row["interval_audio_delta_sec"]) > 0.02 for row in records),
        "duration_mismatch_over_20ms": sum(abs(row["declared_audio_delta_sec"]) > 0.02 for row in records),
        "source_ids_count": len({str(row["source_id"]) for row in records}),
        "source_audio_paths_count": len({str(row["embedded_audio_path_untrusted"]) for row in records}),
        "duplicates": duplicates, "cross_file_audio_overlap": relationships,
        "rights": rights, "technical_inspection_executed": True,
        "listening_executed": False, "alignment_human_verified": False,
        "speaker_session_groups_verified": False, "provisional_leakage_groups": 1,
        "train_dev_test_split_created": False, "all_rows_exposed_for_inspection": True,
        "final_test_eligible": False, "asr_inference_executed": False,
        "training_executed": False, "wer": None, "nlp_f1": None,
        "project_quality_gate": "NEEDS_MORE_DATA", "release_gate": "BLOCKED",
        "candidate_promoted": False,
    }
    args.private_index.parent.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.private_index.open("x", encoding="utf-8") as stream:
        json.dump({"not_a_training_manifest": True, "records": records}, stream, indent=2)
    summary["private_index_sha256"] = digest(args.private_index.read_bytes())
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2)
    print(json.dumps({key: summary[key] for key in (
        "row_count", "decoded_rows", "decode_status", "min_clip_sec", "max_clip_sec",
        "sample_rates", "channels", "interval_mismatch_over_20ms", "duration_mismatch_over_20ms")}, indent=2))
    print(json.dumps({key: value for key, value in duplicates.items() if key != "duplicate_groups"}, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
