from collections import Counter

import pytest

from north55_speech.sampling import balanced_selection


def rows():
    return [{'id': f'{speaker}-{i}', 'speaker_id': speaker, 'split': 'train'}
            for speaker, total in [('a', 50), ('b', 50), ('c', 2)] for i in range(total)]


def test_balances_available_speakers_and_redistributes_exhausted_quota():
    selected = balanced_selection(rows(), 22)
    assert Counter(r['speaker_id'] for r in selected) == {'a': 10, 'b': 10, 'c': 2}
    assert len({r['id'] for r in selected}) == 22


def test_independent_of_publisher_order_and_does_not_mutate_input():
    source = rows()
    original = [r.copy() for r in source]
    assert balanced_selection(source, 22) == balanced_selection(list(reversed(source)), 22)
    assert source == original


@pytest.mark.parametrize('split', ['dev', 'test', 'unassigned'])
def test_rejects_nontraining_records(split):
    with pytest.raises(ValueError, match='train records'):
        balanced_selection([{'id': 'one', 'speaker_id': 'a', 'split': split}], 1)


def test_duplicate_ids_or_insufficient_records_fail_closed():
    with pytest.raises(ValueError, match='Duplicate'):
        balanced_selection([rows()[0], rows()[0]], 2)
    with pytest.raises(ValueError, match='Insufficient'):
        balanced_selection(rows(), 103)
