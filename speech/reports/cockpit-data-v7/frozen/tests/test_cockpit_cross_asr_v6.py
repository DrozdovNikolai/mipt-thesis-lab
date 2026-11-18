from scripts.cockpit_cross_asr_rules_v6 import compatible, interval_union_seconds, timestamp_reasons

POLICY = {'exact_below_words': 8, 'teacher_disagreement': .08}


def test_critical_disagreement_is_not_allowed_by_long_text_tolerance():
    base = 'Before starting engines check the aircraft parking brake hydraulic pressure and generator switch on'
    assert not compatible(base, base.replace(' on', ' off'), POLICY)
    assert not compatible(base+' 120', base+' 121', POLICY)
    assert compatible(base, base+'.', POLICY)


def test_short_commands_require_exact_words():
    assert not compatible('Engine master switch off', 'Engine master switches off', POLICY)


def test_timestamps_require_real_order_and_bounds():
    assert timestamp_reasons([{'start': 2., 'end': 3.}, {'start': 1., 'end': 2.}], 5, .25) == ['nonmonotonic_timestamps']
    assert timestamp_reasons([{'start': 0., 'end': 6.}], 5, .25) == ['invalid_timestamps']
    assert timestamp_reasons([{'start': 0., 'end': 0.}], 5, .25) == ['collapsed_timestamps']


def test_whisper_probability_is_required_but_not_fabricated_for_parakeet():
    words = [{'start': 0., 'end': 1.}]
    assert timestamp_reasons(words, 2, .25) == []
    assert timestamp_reasons(words, 2, .25, True) == ['invalid_probability']


def test_union_does_not_count_overlapping_or_nested_clips_twice():
    assert interval_union_seconds([(0, 10), (5, 15), (7, 9), (20, 25)]) == 20
