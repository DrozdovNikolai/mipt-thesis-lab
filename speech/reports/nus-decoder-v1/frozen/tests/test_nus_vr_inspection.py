"""Protect acquisition integrity and inspection semantics; no real corpus gold."""

import hashlib
import io

import numpy as np
import pytest
import soundfile as sf

from scripts.acquire_nus_vr import REVISION, select_files, verify_blob
from scripts.inspect_nus_vr import (
    duplicate_summary,
    finite_number,
    inspect_audio,
    normalized_reference,
)


def test_corrupted_same_length_payload_is_rejected():
    body = b"PAR1dataPAR1"
    row = {"path": "Sample01.parquet", "size": len(body),
           "sha": hashlib.sha1(f"blob {len(body)}\0".encode() + body).hexdigest()}
    verify_blob(body, row)
    with pytest.raises(ValueError, match="mismatch"):
        verify_blob(b"PAR1xxxxPAR1", row)


@pytest.mark.parametrize("tree", [
    {"sha": REVISION, "truncated": True, "tree": []},
    {"sha": "different", "truncated": False, "tree": []},
    {"sha": REVISION, "truncated": False, "tree": [
        {"type": "blob", "path": "faster_whisper/whisper_training/../../escape.parquet"}]},
])
def test_source_tree_cannot_silently_change_or_escape(tree):
    with pytest.raises(ValueError):
        select_files(tree)


def test_null_origin_times_are_unknown_not_clip_zero():
    assert finite_number(float("nan")) is None
    assert finite_number(float("inf")) is None
    assert finite_number(None) is None
    assert finite_number(0.0) == 0.0


def test_duplicate_audio_with_different_number_is_reference_conflict():
    records = [{"pcm_sha256": "same-audio", "row_id": str(index), "duration_sec": 1.0,
                "reference_words": 2, "normalized_text_sha256": normalized_reference(text)}
               for index, text in enumerate(["speed fifty", "speed fifteen", " SPEED  FIFTY "])]
    result = duplicate_summary(records)
    assert result["unique_pcm_clips"] == 1
    assert result["duplicate_rows"] == 2
    assert len(result["conflicting_reference_audio_groups"]) == 1
    assert result["unique_audio_duration_sec"] == 1.0


def test_audio_decode_uses_embedded_signal_and_rejects_garbage():
    buffer = io.BytesIO()
    samples = np.linspace(-0.2, 0.2, 1600, dtype="float32")
    sf.write(buffer, samples, 16000, format="WAV", subtype="PCM_16")
    result = inspect_audio(buffer.getvalue())
    assert result["duration_sec"] == 0.1
    assert result["channels"] == 1
    assert result["sample_rate"] == 16000
    assert result["rms"] > 0
    with pytest.raises((ValueError, RuntimeError)):
        inspect_audio(b"not audio")
