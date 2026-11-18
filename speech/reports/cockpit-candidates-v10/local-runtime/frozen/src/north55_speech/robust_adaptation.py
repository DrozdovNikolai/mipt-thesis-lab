"""Deterministic train-only acoustic variants, schedules and silence targets."""
from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

ARMS = {
    'uniform': {'encoder_lora': False, 'negative_weight': 0.0, 'balanced': False},
    'balanced': {'encoder_lora': False, 'negative_weight': 0.0, 'balanced': True},
    'balanced-silence': {'encoder_lora': False, 'negative_weight': 0.1, 'balanced': True},
}
TRAINING = {'updates': 240, 'accumulation': 4, 'learning_rate': 2e-5, 'rank': 8,
    'alpha': 16, 'dropout': .05, 'seed': 55, 'precision': 'bfloat16', 'arms': ARMS,
    'checkpoint_selection': 'fixed_final', 'fixed_candidate': 'balanced-silence',
    'negative_target': 'SOT -> nocaptions -> EOT', 'negative_weight': .1,
    'noise_snr_db': [5, 10, 15, 20], 'gain_db_range': [-12, 0],
    'specaugment': {'time_masks': 2, 'time_width': 5, 'frequency_width': 4}}


def synthetic_noise(n, seed, family):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    if family in ('colored', 'engine'):
        x = lfilter([1.], [1., -.97], x)
    if family == 'engine':
        t = np.arange(n) / 16000
        f = rng.uniform(70, 180)
        x += 2 * np.sin(2*np.pi*f*t) + np.sin(2*np.pi*2*f*t)
    if family == 'band':
        x = lfilter([1., -1.], [1., -.4], x)
    if family not in ('white', 'colored', 'engine', 'band'):
        raise ValueError('Unknown synthetic family')
    x -= np.mean(x)
    return (x / max(float(np.sqrt(np.mean(x*x))), 1e-12)).astype('float32')


def augment_waveform(waveform, seed, snr_db=None):
    x = np.array(waveform, dtype='float32', copy=True)
    if x.ndim != 1 or not 0 < len(x) <= 480000 or not np.isfinite(x).all() or not np.any(x):
        raise ValueError('Require finite, nonempty original speech')
    rng = np.random.default_rng(seed)
    delay = int(rng.integers(320, 1281))
    strength = float(rng.uniform(.1, .3))
    reflected = x.copy()
    if delay < len(x):
        reflected[delay:] += strength*x[:-delay]
    if 2*delay < len(x):
        reflected[2*delay:] += strength*.4*x[:-2*delay]
    padded = np.pad(reflected, (0, (-len(x)) % 320))
    energy = np.sqrt(np.mean(padded.reshape(-1, 320).astype('float64')**2, axis=1))
    active = np.repeat(energy >= max(float(energy.max())*.1, 1e-9), 320)[:len(x)]
    if not active.any():
        raise ValueError('No energetic speech frames')
    family = ['white', 'colored', 'engine', 'band'][int(rng.integers(4))]
    noise = synthetic_noise(len(x), seed + 17, family)
    snr = float(rng.choice(TRAINING['noise_snr_db'])) if snr_db is None else float(snr_db)
    signal_rms = float(np.sqrt(np.mean(reflected[active].astype('float64')**2)))
    noise_rms = float(np.sqrt(np.mean(noise[active].astype('float64')**2)))
    alpha = signal_rms / (noise_rms * 10**(snr/20))
    mixed = reflected + alpha*noise
    gain_db = float(rng.uniform(-12, 0))
    scale = min(1., .97/max(float(np.abs(mixed).max()), 1e-12)) * 10**(gain_db/20)
    result = (mixed * scale).astype('float32')
    measured = float(20*np.log10(signal_rms/(alpha*noise_rms)))
    return result, {'seed': seed, 'noise_family': family, 'snr_db': snr, 'measured_snr_db': measured,
        'gain_db': gain_db, 'scale': scale, 'delay_samples': delay, 'reflection_gain': strength,
        'active_samples': int(active.sum()), 'synthetic': True, 'text_unchanged': True}


def negative_waveform(seed, index):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(4*16000, 15*16000))
    family = 'silence' if index % 8 == 0 else ['white', 'colored', 'engine', 'band'][index % 4]
    if family == 'silence':
        return np.zeros(n, dtype='float32'), {'seed': seed, 'family': family, 'reference_text': ''}
    x = synthetic_noise(n, seed + 19, family)
    level_db = float(rng.uniform(-45, -15))
    x *= min(10**(level_db/20), .97/max(float(np.abs(x).max()), 1e-12))
    return x, {'seed': seed, 'family': family, 'level_db': level_db, 'reference_text': ''}


def mask_features(features, audio_samples, seed):
    """Mask only actual audio frames, leaving padding and source tensor unchanged."""
    result = features.clone()
    rng = np.random.default_rng(seed)
    frames = min(result.shape[-1], (audio_samples + 159)//160)
    if frames < 20:
        raise ValueError('Too little audio for masked training')
    spans = []
    for _ in range(2):
        start = int(rng.integers(0, frames-5+1))
        result[..., start:start+5] = 0
        spans.append([start, start+5])
    band = int(rng.integers(0, result.shape[-2]-4+1))
    result[..., band:band+4, :frames] = 0
    return result, {'time_spans': spans, 'frequency_span': [band, band+4], 'active_frames': frames}


def schedules(samples):
    rng = np.random.default_rng(55)
    buckets = {'retained': [], 'hard': [], 'paired': []}
    for s in samples:
        key = ('paired' if s.variant_of else 'hard' if
               s.annotation_provenance['method'] == 'cockpit_hard_teacher_consensus_v4' else 'retained')
        buckets[key].append(s.sample_id)
    if {k: len(v) for k, v in buckets.items()} != {'retained': 206, 'hard': 25, 'paired': 16}:
        raise ValueError('Require the frozen 247-pair population')
    positions = {k: 0 for k in buckets}
    for values in buckets.values():
        rng.shuffle(values)

    def take(key):
        values = buckets[key]
        pos = positions[key]
        if pos and pos % len(values) == 0:
            rng.shuffle(values)
        value = values[pos % len(values)]
        positions[key] += 1
        return value

    balanced = []
    for u in range(240):
        rows = [(take('retained'), False), (take('hard'), False),
                (take('hard' if u % 2 else 'retained'), True),
                (take('paired'), False) if u % 4 == 0 else (take('hard' if u % 2 else 'retained'), True)]
        for parent, augmented in rows:
            balanced.append({'parent': parent, 'augmented': augmented, 'seed': 550000 + len(balanced)})
    # Torch randperm reproduces the former uniform schedule exactly.
    import torch
    g = torch.Generator().manual_seed(55)
    uniform = []
    while len(uniform) < 960:
        uniform.extend({'parent': samples[int(i)].sample_id, 'augmented': False, 'seed': 0}
                       for i in torch.randperm(len(samples), generator=g))
    return {'uniform': uniform[:960], 'balanced': balanced,
            'negative': [{'seed': 650000+i, 'index': i} for i in range(240)]}
