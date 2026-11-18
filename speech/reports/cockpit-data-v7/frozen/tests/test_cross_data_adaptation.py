from types import SimpleNamespace

import pytest

from north55_speech.cross_data_adaptation import balanced_schedule, expand_without_overlaps


def sample(identity, a, b, source='reader', variant_of=None, method='publisher_phrase_consensus_v2'):
    return SimpleNamespace(sample_id=identity, split='train', variant_of=variant_of,
        annotation_provenance={'source_sample_id': source, 'original_start_sec': a,
        'original_end_sec': b, 'method': method})


def test_full_replacement_preserves_added_audio_and_removes_old_duplicate():
    old = [sample('short', 2, 5), sample('other', 10, 15)]
    new = [sample('long', 1, 7)]
    expanded, removed = expand_without_overlaps(old, new)
    assert [s.sample_id for s in expanded] == ['other', 'long']
    assert removed == {'short': 'long'}


def test_partial_overlap_and_orphaned_noise_are_rejected():
    with pytest.raises(ValueError, match='partly'):
        expand_without_overlaps([sample('old', 2, 8)], [sample('new', 1, 5)])
    with pytest.raises(ValueError, match='orphan'):
        expand_without_overlaps([sample('old', 2, 5), sample('noise', 2, 5, variant_of='old')], [sample('new', 1, 7)])


def test_new_overlaps_rejected_but_other_sources_and_touching_intervals_allowed():
    with pytest.raises(ValueError, match='Overlapping'):
        expand_without_overlaps([], [sample('one', 0, 5), sample('two', 4, 9)])
    rows, _ = expand_without_overlaps([sample('a', 0, 5)], [sample('b', 5, 9), sample('c', 0, 5, source='other')])
    assert len(rows) == 3


def test_matched_slots_and_exact_coverage_for_fixed_populations():
    old = [sample(f'r{i}', i, i+1) for i in range(206)]
    old += [sample(f'h{i}', i, i+1, method='cockpit_hard_teacher_consensus_v4') for i in range(25)]
    old += [sample(f'n{i}', i, i+1, variant_of=f'r{i}') for i in range(16)]
    new = old[6:]+[sample(f'x{i}', i, i+1, method='cross_family_consensus_v6') for i in range(18)]
    left, right = balanced_schedule(old), balanced_schedule(new)
    assert len(left) == len(right) == 960
    assert sum(s['augmented'] for s in left) == sum(s['augmented'] for s in right) == 420
    assert [(s['seed'], s['augmented']) for s in left] == [(s['seed'], s['augmented']) for s in right]
    assert {s['parent'] for s in left} == {s.sample_id for s in old}
    assert {s['parent'] for s in right} == {s.sample_id for s in new}
