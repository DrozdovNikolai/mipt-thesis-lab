import numpy as np
import pytest

from north55_speech.audio import VadProvider
from north55_speech.local_transcription import config_for_language
from north55_speech.schemas import VadConfig


def test_only_explicit_russian_selects_russian_model():
    recipe = {"schema_version": "1.0", "default": {"model": "small"},
              "by_language": {"ru": {"model": "large"}}}
    assert config_for_language(recipe, "ru").model == "large"
    for language in ("auto", "en", "mixed"):
        assert config_for_language(recipe, language).model == "small"
    with pytest.raises(ValueError):
        config_for_language(recipe, "unrecognized")


def test_gate_keeps_the_complete_audio_context(monkeypatch):
    monkeypatch.setattr("faster_whisper.vad.get_speech_timestamps",
                        lambda *args, **kwargs: [{"start": 1600, "end": 3200}])
    audio = np.zeros(16000, dtype=np.float32)
    provider = VadProvider()
    assert provider.intervals(audio, VadConfig(enabled=True, mode="gate")) == [(0, 16000)]
    assert provider.intervals(audio, VadConfig(enabled=True)) == [(1600, 3200)]


def test_gate_does_not_invent_speech_or_silently_change_disabled_mode(monkeypatch):
    monkeypatch.setattr("faster_whisper.vad.get_speech_timestamps", lambda *args, **kwargs: [])
    audio = np.zeros(16000, dtype=np.float32)
    assert VadProvider().intervals(audio, VadConfig(enabled=True, mode="gate")) == []
    assert VadProvider().intervals(audio, VadConfig(enabled=False, mode="gate")) == [(0, 16000)]
