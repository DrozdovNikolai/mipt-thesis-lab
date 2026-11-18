import numpy as np
import pytest

from north55_speech.acoustic_noise_router import audio_features, choose_by_noise


def test_features_are_gain_invariant_and_temporally_informative():
    rng = np.random.default_rng(55)
    noise = rng.normal(size=32000).astype('float32')
    envelope = np.tile(np.concatenate([np.zeros(4000), np.ones(4000)]), 4)
    speech_like = noise*envelope
    f = audio_features(speech_like)
    assert f.shape == (62,) and np.isfinite(f).all()
    np.testing.assert_allclose(audio_features(speech_like*.001), f, atol=1e-10, rtol=1e-10)
    assert not np.allclose(audio_features(noise), f)
    assert np.isfinite(audio_features(np.zeros(16000))).all()


def test_invalid_audio_is_not_silently_trimmed_or_imputed():
    for x in (np.zeros(2), np.zeros(480001), np.zeros((16000, 2)), np.full(16000, np.nan)):
        with pytest.raises(ValueError):
            audio_features(x)


def test_routing_uses_acoustic_probability_and_explicit_empty_response():
    assert choose_by_noise('first', 'second', 'en', .9, .8)['hypothesis'] == 'second'
    assert choose_by_noise('first', 'second', 'en', .7, .8)['hypothesis'] == 'first'
    assert choose_by_noise('hallucination', '', 'en', None, .8)['hypothesis'] == ''
    assert choose_by_noise('русский', None, 'ru', None, .8)['hypothesis'] == 'русский'
    with pytest.raises(ValueError):
        choose_by_noise('first', None, 'en', None, .8)
    with pytest.raises(ValueError):
        choose_by_noise('first', 'second', 'en', float('nan'), .8)
