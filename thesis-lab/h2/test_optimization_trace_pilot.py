import pytest
from h2.optimization_trace_pilot import fit_envelope


def test_upper_bound_removes_short_sample_extrapolation_without_underprediction():
    samples = [{'audio_seconds': 30, 'preprocess': .18},
               {'audio_seconds': 180, 'preprocess': .16},
               {'audio_seconds': 900, 'preprocess': .42}]
    fit = fit_envelope(samples, 'preprocess')
    predicted = lambda x: fit['fixed_seconds'] + fit['seconds_per_audio_second'] * x
    assert all(predicted(x['audio_seconds']) >= x['preprocess'] - 1e-9 for x in samples)
    assert predicted(900) == pytest.approx(.42)
    assert fit['fixed_seconds'] >= 0 and fit['seconds_per_audio_second'] >= 0


@pytest.mark.parametrize('duration,time', [(0, 1), (10, -1), (float('nan'), 1), (10, float('inf'))])
def test_invalid_calibration_does_not_create_forecast(duration, time):
    with pytest.raises(ValueError):
        fit_envelope([{'audio_seconds': duration, 'preprocess': time}], 'preprocess')
