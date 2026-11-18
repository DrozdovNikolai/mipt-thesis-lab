import pytest

from scripts.soteria_v14 import combine_intervals


def spans(*pairs):
    return [{'start':a,'end':b} for a,b in pairs]


def test_merge_short_turns_preserves_real_pause_and_offsets():
    assert combine_intervals(spans((10,40),(45,80),(100,150)),200,rate=10)==[[10,80],[100,150]]


def test_long_pause_is_not_concatenated_or_lost():
    assert combine_intervals(spans((10,40),(90,100)),200,rate=10)==[[10,40],[90,100]]


def test_maximum_duration_splits_at_existing_boundary():
    assert combine_intervals(spans((0,70),(75,210),(215,260)),300,rate=10)==[[0,210],[215,260]]


@pytest.mark.parametrize('intervals,frames',[(spans((10,20),(19,30)),100),(spans((-1,2)),100),(spans((10,101)),100),(spans((10,10)),100),(spans((0,250)),300)])
def test_invalid_or_overlapping_ranges_are_rejected(intervals,frames):
    with pytest.raises(ValueError):
        combine_intervals(intervals,frames,rate=10)


def test_empty_source_has_no_invented_speech():
    assert combine_intervals([],100,rate=10)==[]
