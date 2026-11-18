"""Reject misleading before/after comparisons at the scoring boundary."""

import copy

import pytest

from scripts.publisher_training_v3 import compare_records


def example():
    item = {'id': 'held-reader', 'audio_sha256': 'a'*64, 'gain_db': 0.}
    record = {**item, 'effective_options': {'beam_size': 5, 'language': 'en'},
        'effective_waveform_sha256': 'b'*64, 'runtime_failure': None,
        'hypothesis': 'parking brake set'}
    return item, record, copy.deepcopy(record)


@pytest.mark.parametrize('key,value', [
    ('effective_options', {'beam_size': 1, 'language': 'en'}),
    ('effective_waveform_sha256', 'c'*64),
    ('gain_db', -12.),
    ('runtime_failure', 'CUDA error'),
])
def test_comparison_rejects_mismatched_evidence(key, value):
    item, baseline, candidate = example()
    candidate[key] = value
    with pytest.raises(ValueError):
        compare_records(item, 'parking brake set', baseline, candidate)


def test_comparison_keeps_word_error_and_empty_noise_semantics():
    item, baseline, candidate = example()
    candidate['hypothesis'] = 'parking brake off'
    result = compare_records(item, 'parking brake set', baseline, candidate)
    assert result['baseline']['S'] == 0
    assert result['candidate']['S'] == 1
    assert result['candidate']['N'] == 3
    result = compare_records(item, '', baseline, candidate)
    assert result['candidate']['wer'] is None
    assert result['candidate']['I'] == 3


def test_missing_reference_cannot_become_a_noise_reference():
    item, baseline, candidate = example()
    with pytest.raises(ValueError, match='missing'):
        compare_records(item, None, baseline, candidate)
