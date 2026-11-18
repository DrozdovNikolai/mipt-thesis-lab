import numpy as np
import pytest

from north55_speech.robust_adaptation import augment_waveform, mask_features, negative_waveform


def test_augmentation_reproducible_snr_length_no_clipping_and_source_preserved():
    t = np.arange(32000)/16000
    source = (.1*np.sin(2*np.pi*320*t)).astype('float32')
    original = source.copy()
    a, meta = augment_waveform(source, 73, snr_db=10)
    b, same = augment_waveform(source, 73, snr_db=10)
    c, _ = augment_waveform(source, 74, snr_db=10)
    assert np.array_equal(source, original) and np.array_equal(a, b)
    assert meta == same and not np.array_equal(a, c)
    assert a.shape == source.shape and a.dtype == np.float32 and np.isfinite(a).all()
    assert np.abs(a).max() <= .97 and meta['measured_snr_db'] == pytest.approx(10)


@pytest.mark.parametrize('source', [np.zeros(16000), np.array([]), np.full(16000, np.nan)])
def test_empty_or_nonfinite_speech_is_not_labeled_as_a_valid_augmentation(source):
    with pytest.raises(ValueError):
        augment_waveform(source, 1)


def test_synthetic_negatives_have_no_source_speech_and_disjoint_seeds_change_waveform():
    silence, meta = negative_waveform(650000, 0)
    assert not np.any(silence) and meta['reference_text'] == ''
    a, meta = negative_waveform(650001, 1)
    b, _ = negative_waveform(750001, 1)
    assert np.isfinite(a).all() and np.any(a) and np.abs(a).max() <= .97
    assert meta['reference_text'] == '' and not np.array_equal(a, b)


def test_specaugment_leaves_padding_and_original_unchanged():
    import torch
    source = torch.ones(1, 80, 3000)
    result, meta = mask_features(source, 32000, 55)
    assert torch.all(source == 1) and torch.all(result[..., 200:] == 1)
    assert torch.any(result[..., :200] == 0)
    assert meta['active_frames'] == 200
