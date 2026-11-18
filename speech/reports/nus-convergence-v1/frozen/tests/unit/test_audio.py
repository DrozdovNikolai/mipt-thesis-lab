import numpy as np
import pytest
import soundfile as sf

from north55_speech.audio import AudioPreprocessor, VadProvider, channel_crosstalk, denoise, probe
from north55_speech.core import SpeechError
from north55_speech.schemas import DenoiseConfig, VadConfig


def test_corrupt_container(tmp_path):
    source = tmp_path / "fake.wav"
    source.write_bytes(b"not audio")
    with pytest.raises(SpeechError):
        probe(source)


def test_silence_and_resample(tmp_path):
    source = tmp_path / "silence.wav"
    sf.write(source, np.zeros(44100), 44100)
    info, paths = AudioPreprocessor().prepare(source, tmp_path / "prepared", "mixed")
    waveform, rate = sf.read(paths[0], dtype="float32")
    assert rate == 16000 and len(waveform) == 16000
    assert info.sample_rate == 44100 and info.channel_diagnostics[0]["rms"] == 0
    assert VadProvider().intervals(waveform, VadConfig(enabled=True)) == []
    assert np.array_equal(denoise(waveform, DenoiseConfig(enabled=True)), waveform)


def test_channels_crosstalk_clipping(tmp_path):
    source = tmp_path / "two.wav"
    signal = np.ones(16000, dtype=np.float32)
    sf.write(source, np.stack([signal, signal], axis=1), 16000, subtype="FLOAT")
    info, paths = AudioPreprocessor().prepare(source, tmp_path / "prepared", "separate_channels")
    assert len(paths) == 2 and info.channels == 2
    assert info.channel_diagnostics[0]["clipping_fraction"] == 1
    assert len(channel_crosstalk(paths)) == 1


def test_real_spectral_denoise_preserves_length():
    rng = np.random.default_rng(55)
    signal = rng.normal(0, 0.01, 32000).astype(np.float32)
    cleaned = denoise(signal, DenoiseConfig(enabled=True))
    assert len(cleaned) == len(signal) and np.isfinite(cleaned).all()
    assert np.mean(cleaned**2) < np.mean(signal**2)
