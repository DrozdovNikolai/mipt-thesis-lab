"""Overlap-free admission and matched acoustic schedules for v7 weak data."""
from __future__ import annotations

import numpy as np

ARMS = {'control': {'encoder_lora': False}, 'expanded': {'encoder_lora': False}}
TRAINING = {'updates': 240, 'accumulation': 4, 'learning_rate': 2e-5, 'rank': 8,
    'alpha': 16, 'dropout': .05, 'seed': 55, 'precision': 'bfloat16',
    'arms': ARMS, 'fixed_candidate': 'expanded', 'checkpoint_selection': 'fixed_final',
    'negative_weight': 0., 'bucket_presentations': {'retained': 420, 'hard': 480, 'paired': 60},
    'acoustic_variants_each': 420}


def span(sample):
    p = sample.annotation_provenance
    return p['source_sample_id'], p['original_start_sec'], p['original_end_sec']


def expand_without_overlaps(original, supplemental):
    """Replace fully contained originals; reject ambiguous partial overlaps."""
    removed = {}
    for row in supplemental:
        source, a, b = span(row)
        if row.variant_of or row.split != 'train' or not 0 <= a < b:
            raise ValueError('Invalid supplemental source interval')
        for old in original:
            if old.variant_of:
                continue
            osource, oa, ob = span(old)
            if source != osource or min(b, ob)-max(a, oa) <= 1/16000:
                continue
            if a > oa+1/16000 or b < ob-1/16000:
                raise ValueError('Cannot silently discard partly overlapped old audio')
            if old.sample_id in removed:
                raise ValueError('More than one replacement for an old interval')
            removed[old.sample_id] = row.sample_id
    if any(s.variant_of in removed for s in original):
        raise ValueError('Cannot orphan a paired noisy copy')
    expanded = [s for s in original if s.sample_id not in removed]+list(supplemental)
    clean = [s for s in expanded if not s.variant_of]
    for i, left in enumerate(clean):
        source, a, b = span(left)
        for right in clean[i+1:]:
            rsource, ra, rb = span(right)
            if source == rsource and min(b, rb)-max(a, ra) > 1/16000:
                raise ValueError('Overlapping clean training intervals')
    return expanded, removed


def balanced_schedule(samples):
    """Same slot types and seed stream as v5; membership depends only on provenance."""
    rng = np.random.default_rng(55)
    buckets = {'retained': [], 'hard': [], 'paired': []}
    for sample in samples:
        method = sample.annotation_provenance['method']
        bucket = 'paired' if sample.variant_of else ('hard' if method in
            ('cockpit_hard_teacher_consensus_v4', 'cross_family_consensus_v6') else 'retained')
        buckets[bucket].append(sample.sample_id)
    if any(not values for values in buckets.values()):
        raise ValueError('Every fixed bucket must be populated')
    positions = dict.fromkeys(buckets, 0)
    for values in buckets.values():
        rng.shuffle(values)

    def take(key):
        values, position = buckets[key], positions[key]
        if position and position % len(values) == 0:
            rng.shuffle(values)
        positions[key] += 1
        return values[position % len(values)]

    schedule = []
    for update in range(240):
        entries = [(take('retained'), False), (take('hard'), False),
            (take('hard' if update % 2 else 'retained'), True),
            (take('paired'), False) if update % 4 == 0 else (take('hard' if update % 2 else 'retained'), True)]
        for parent, augmented in entries:
            schedule.append({'parent': parent, 'augmented': augmented, 'seed': 550000+len(schedule)})
    return schedule
