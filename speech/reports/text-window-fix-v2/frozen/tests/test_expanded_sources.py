import numpy as np
import pytest

from scripts.expand_publisher_pairs import family_for, windows
from scripts.prepare_voici_diagnostics import mix_at_snr


def test_expansion_covers_full_windows_without_overlapping_or_padding_tails():
    assert windows(59.99) == [(0, 20), (20, 20)]
    assert windows(60) == [(0, 20), (20, 20), (40, 20)]
    assert windows(19.99) == []


def test_tbm940_is_included_but_radio_unknown_and_french_families_are_not():
    assert family_for('bleriot-a:DGA_checklist-TBM940_sp102') == 'DGA_checklist-TBM940'
    assert family_for('bleriot-c:CVR_DGA_checklist-TBM940_sp102') == 'DGA_checklist-TBM940'
    for source in ['BEA_CVR_sp001', 'DGA_CVR1', 'DGA_checklist-Puma-1_sp105', 'DGA_checklist-unknown_sp102']:
        assert family_for(source) is None


@pytest.mark.parametrize('snr', [0., 10.])
def test_noise_mixture_preserves_active_snr_without_clipping(snr):
    rng = np.random.default_rng(55)
    speech, noise = rng.normal(size=(2, 1000)).astype(np.float32)
    active = np.arange(1000) >= 200
    mixture, report = mix_at_snr(speech, noise, active, snr)
    actual_speech = speech * report['mixture_gain']
    actual_noise = mixture - actual_speech
    measured = 20 * np.log10(np.sqrt(np.mean(actual_speech[active] ** 2)) / np.sqrt(np.mean(actual_noise[active] ** 2)))
    assert abs(measured - snr) < .00001
    assert np.max(np.abs(mixture)) <= .980001
    assert mixture.shape == speech.shape


def test_silent_or_unaligned_mixture_is_rejected():
    audio = np.ones(100, dtype=np.float32)
    with pytest.raises(ValueError, match='nonempty'):
        mix_at_snr(audio, audio, np.zeros(100, dtype=bool), 10)
    with pytest.raises(ValueError, match='silent'):
        mix_at_snr(audio, audio * 0, np.ones(100, dtype=bool), 10)
