"""Generated signals verify mixing arithmetic only; never research evidence."""

import numpy as np
import soundfile as sf

from north55_speech.augmentation import augment
from north55_speech.core import file_hash, settings
from north55_speech.datasets import load_manifest, validate_groups, write_manifest
from tests.unit.test_data_gates import sample


def test_active_snr_clipping_and_variant_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "audio_root", tmp_path)
    count = 16000
    speech = (0.3 * np.sin(np.arange(count) * 0.08)).astype("float32")
    noise = np.random.default_rng(55).normal(0, 0.1, count).astype("float32")
    sf.write(tmp_path / "speech.wav", speech, 16000, subtype="FLOAT")
    sf.write(tmp_path / "noise.wav", noise, 16000, subtype="FLOAT")
    original = sample(
        1,
        audio_path="speech.wav",
        audio_sha256=file_hash(tmp_path / "speech.wav"),
        split="train",
        duration_sec=1,
        speech_origin="recorded_human",
    )
    noise_sample = sample(
        2,
        audio_path="noise.wav",
        audio_sha256=file_hash(tmp_path / "noise.wav"),
        split="train",
        duration_sec=1,
        scope="non_speech",
        speech_origin="noise",
        scope_verified=True,
    )
    validate_groups([original, noise_sample])
    write_manifest(tmp_path / "speech.jsonl", [original])
    write_manifest(tmp_path / "noise.jsonl", [noise_sample])
    monkeypatch.setattr(
        "north55_speech.augmentation.VadProvider.intervals", lambda *args: [(0, count)]
    )
    augment(tmp_path / "speech.jsonl", tmp_path / "noise.jsonl", tmp_path / "augmented.jsonl", 10)
    a, b = load_manifest(tmp_path / "augmented.jsonl")
    meta = b.augmentation
    measured = 20 * np.log10(meta["active_speech_rms"] / (meta["alpha"] * meta["active_noise_rms"]))
    assert abs(measured - 10) < 1e-6
    assert a.group_id == b.group_id and a.split == b.split
    assert b.decoded_audio_sha256 and b.transcript_status == "weak"
    assert not b.annotation_provenance["reviewed_audio"]
    assert not b.primary and not b.clean_control
