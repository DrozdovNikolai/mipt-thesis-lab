from types import SimpleNamespace

import numpy as np
import pytest
from faster_whisper import WhisperModel

from north55_speech.audio import VadProvider
from north55_speech.core import SpeechError
from north55_speech.text_windows import TextWindowWhisperModel


def test_vad_finalization_never_extends_the_asr_waveform(monkeypatch):
    original = np.linspace(-.1, .1, 16000, dtype='float32')
    observed = {}

    def intervals(_, audio, config):
        observed['vad'] = audio
        return [(0, len(audio))]

    def transcribe(_, audio, *args, **kwargs):
        observed['asr'] = audio
        def segments():
            yield from ()
        return segments(), SimpleNamespace()

    monkeypatch.setattr(VadProvider, 'intervals', intervals)
    monkeypatch.setattr(WhisperModel, 'transcribe', transcribe)
    model = object.__new__(TextWindowWhisperModel)
    generator, info = model.transcribe(original)
    assert list(generator) == []
    assert observed['asr'] is original
    assert np.array_equal(observed['vad'][:len(original)], original)
    assert len(observed['vad']) == len(original) + 16000
    assert np.count_nonzero(observed['vad'][len(original):]) == 0
    assert info.north55_text_window_audit['speech_intervals_sec'] == ((0., 1.),)


@pytest.mark.parametrize('audio', [np.array([np.nan]), np.zeros((10, 2))])
def test_invalid_audio_is_rejected_before_backend(audio):
    model = object.__new__(TextWindowWhisperModel)
    with pytest.raises(SpeechError):
        model.transcribe(audio)
