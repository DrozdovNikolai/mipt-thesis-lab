"""Gain-invariant audio features for a train-only synthetic-noise classifier."""
from __future__ import annotations

import numpy as np
from scipy.signal import stft

RECIPE = {'seed': 55, 'variants_per_level': 4, 'snr_db': [0, 5, 15, 25],
    'positive_snr_db': [0, 5], 'augmentation_seed_start': 950000,
    'trees': 256, 'max_depth': 12, 'min_samples_leaf': 4,
    'threshold_floor': .8, 'negative_oof_quantile': .99}


def audio_features(waveform):
    x = np.asarray(waveform, dtype='float64')
    if x.ndim != 1 or not np.isfinite(x).all() or not 400 <= len(x) <= 480000:
        raise ValueError('Expected 25 ms to 30 s of finite mono 16 kHz audio')
    scale = float(np.sqrt(np.mean(x*x)))
    if scale:
        x = x/scale
    frequencies, _, z = stft(x, fs=16000, nperseg=400, noverlap=240, nfft=512,
        boundary=None, padded=False)
    power = np.abs(z)**2
    values = [float(np.max(np.abs(x))), float(np.mean(x**4))]
    total = max(float(power.mean()), 1e-20)
    for low, high in ((0, 8001), (70, 400), (400, 2000), (2000, 4000), (4000, 8001)):
        p = power[(frequencies >= low) & (frequencies < high)]
        energy = p.mean(axis=0)
        mean = max(float(energy.mean()), 1e-20)
        quantiles = np.quantile(energy, [.1, .25, .5, .75, .9])
        values.extend(np.log10(np.maximum(quantiles/mean, 1e-12)).tolist())
        values.extend([mean/total, float(energy.std()/mean),
            float(np.abs(np.diff(energy)).mean()/mean) if len(energy) > 1 else 0.,
            float(np.mean(energy < .25*mean))])
        flatness = np.exp(np.log(np.maximum(p, 1e-20)).mean(axis=0))/np.maximum(energy, 1e-20)
        values.extend(np.quantile(flatness, [.1, .5, .9]).tolist())
    result = np.asarray(values, dtype='float64')
    if result.shape != (62,) or not np.isfinite(result).all():
        raise ValueError('Invalid feature contract')
    return result


def choose_by_noise(whisper, parakeet, language, probability, threshold):
    if language != 'en':
        return {'selected': 'whisper', 'reason': 'non_english_passthrough', 'hypothesis': whisper}
    if parakeet is None:
        raise ValueError('Missing Parakeet is not silence')
    if not parakeet.strip():
        return {'selected': 'parakeet', 'reason': 'parakeet_empty', 'hypothesis': parakeet}
    if probability is None or not np.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError('Expected a finite severe-noise probability')
    selected = 'parakeet' if probability >= threshold else 'whisper'
    return {'selected': selected, 'reason': 'predicted_severe_noise' if selected == 'parakeet' else 'keep_whisper',
        'hypothesis': parakeet if selected == 'parakeet' else whisper}
