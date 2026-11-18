import numpy as np
import pytest
import soundfile as sf

from scripts.transcribe_cockpit_hybrid_v9 import load_wave


def test_float_audio_is_not_quantized_before_noise_routing(tmp_path):
    x = (np.random.default_rng(55).normal(size=16000)*.00001).astype('float32')
    path = tmp_path/'quiet.wav'
    sf.write(path, x, 16000, subtype='FLOAT')
    np.testing.assert_array_equal(load_wave(path), x)


def test_long_input_is_rejected_without_implicit_truncation(tmp_path):
    path = tmp_path/'long.wav'
    sf.write(path, np.zeros(480001), 16000, subtype='FLOAT')
    with pytest.raises(ValueError, match='no automatic trimming'):
        load_wave(path)


def test_stereo_resampling_has_explicit_mono_sample_count(tmp_path):
    path = tmp_path/'stereo.wav'
    sf.write(path, np.ones((48000, 2))*.01, 48000, subtype='FLOAT')
    result = load_wave(path)
    assert result.shape == (16000,) and result.dtype == np.float32 and np.isfinite(result).all()
