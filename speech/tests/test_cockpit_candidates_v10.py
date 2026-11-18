from __future__ import annotations

import numpy as np
import pytest

from north55_speech.cockpit_candidates_v10 import compose_candidates, deep_filter


def test_empty_decoder_does_not_delete_detected_speech():
    item = {'language': 'en', 'whisper': 'flight director on', 'parakeet': ''}
    prior = {'hypothesis': '', 'selected': 'parakeet'}
    rows = compose_candidates(item, prior, True, 'Flight director on.', None)
    assert rows['guarded_v9'] == rows['dfn_parakeet'] == item['whisper']
    assert rows['canary_router'] == 'Flight director on.'


def test_nonspeech_requires_both_empty_parakeet_and_negative_vad():
    item = {'language': 'en', 'whisper': 'hallucination', 'parakeet': ''}
    prior = {'hypothesis': '', 'selected': 'parakeet'}
    rows = compose_candidates(item, prior, False, 'new hallucination', None)
    assert rows['canary'] == 'new hallucination'
    assert rows['canary_guarded'] == rows['canary_router'] == ''
    item['parakeet'] = 'quiet speech'
    prior = {'hypothesis': item['whisper'], 'selected': 'whisper'}
    assert compose_candidates(item, prior, False, 'quiet speech', None)['canary_guarded'] == 'quiet speech'


def test_severe_noise_keeps_speech_even_if_vad_misses_it():
    item = {'language': 'en', 'whisper': 'bad', 'parakeet': 'noisy speech'}
    prior = {'hypothesis': 'noisy speech', 'selected': 'parakeet'}
    rows = compose_candidates(item, prior, False, 'canary', 'filtered speech')
    assert rows['canary_router'] == 'noisy speech'
    assert rows['dfn_parakeet'] == 'filtered speech'
    with pytest.raises(AssertionError):
        compose_candidates(item, prior, False, 'canary', None)


def test_russian_bypasses_english_candidates():
    item = {'language': 'ru', 'whisper': 'проверка', 'parakeet': None}
    prior = {'hypothesis': 'проверка', 'selected': 'whisper'}
    assert set(compose_candidates(item, prior, None, None, None).values()) == {'проверка'}


@pytest.mark.parametrize('wave', [np.zeros(399), np.array([np.nan]*500), np.zeros((500, 2))])
def test_denoiser_rejects_invalid_input_before_launch(wave):
    with pytest.raises(ValueError):
        deep_filter(wave, None)
