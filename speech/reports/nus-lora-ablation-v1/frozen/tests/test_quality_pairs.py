import copy

import pytest

from scripts.prepare_quality_pairs import RATE, agreement_reasons, options, pause_windows

TEXT = 'engine mode selector normal landing gear lever check down'


def response(text=TEXT):
    return {'hypothesis': text, 'error': None, 'detected_language': 'en',
            'words': [{'word': w, 'start': i*.5+.2, 'end': i*.5+.6, 'probability': .8}
                      for i, w in enumerate(text.split())]}


def test_consensus_remains_eligible_for_additional_alignment_only():
    assert agreement_reasons(response(), response(), TEXT, 8) == []


@pytest.mark.parametrize('changed', [
    TEXT.replace('down', 'up'), TEXT.replace('check down', 'not check down'),
    TEXT.replace('normal', 'fifteen'), TEXT.replace('selector', 'select'),
])
def test_word_number_and_negation_disagreements_are_never_rewritten(changed):
    original = response(changed)
    before = copy.deepcopy(original)
    assert 'lexical_disagreement' in agreement_reasons(original, response(), TEXT, 8)
    assert original == before


def test_fifty_is_not_fifteen_even_with_publisher_context():
    a = response(TEXT + ' fifty')
    b = response(TEXT + ' fifteen')
    assert 'numeric_disagreement' in agreement_reasons(a, b, a['hypothesis'], 10)


@pytest.mark.parametrize('lang', ['fr', 'ru', None])
def test_english_document_and_forced_english_do_not_override_unforced_language(lang):
    r = response()
    r['detected_language'] = lang
    assert 'large_unforced_language_not_english' in agreement_reasons(response(), r, TEXT, 8)


@pytest.mark.parametrize('score', [.1, float('nan'), float('inf'), 1.1])
def test_invalid_or_low_confidence_is_held(score):
    r = response()
    r['words'][0]['probability'] = score
    assert 'small_low_word_score' in agreement_reasons(r, response(), TEXT, 8)


def test_cut_word_or_collapsed_timing_is_held():
    r = response()
    r['words'][0]['start'] = 0
    assert 'small_word_at_clip_boundary' in agreement_reasons(r, response(), TEXT, 8)
    r['words'][0]['end'] = 0
    assert 'small_invalid_word_times' in agreement_reasons(r, response(), TEXT, 8)


def test_errors_are_not_admitted_as_empty_references():
    r = response()
    r['error'] = {'type': 'RuntimeError'}
    assert agreement_reasons(r, response(), TEXT, 8) == ['asr_failure']


def test_long_speech_without_pause_is_held_not_cut():
    windows, held = pause_windows([(RATE, 30*RATE)], 31*RATE)
    assert not windows
    assert held == [{'start_sample': RATE, 'end_sample': 30*RATE, 'reason': 'no_safe_pause_before_limit'}]


def test_padding_avoids_adjacent_speech_and_preserves_endpoints():
    intervals = [(RATE, 10*RATE), (10*RATE+1600, 20*RATE), (21*RATE, 48*RATE)]
    windows, held = pause_windows(intervals, 50*RATE)
    assert len(windows) == 2 and len(held) == 1
    assert windows[0][1] <= windows[1][0]
    for (a, b), (start, end) in zip(windows, intervals[:2], strict=True):
        assert 0 <= a <= start < end <= b <= 50*RATE
        assert start-a <= .2*RATE and b-end <= .2*RATE
    assert windows[-1][1] < held[0]['start_sample']


def test_no_prompt_or_second_pass_can_copy_publisher_text():
    for system in ('small', 'large'):
        opts = options(system)
        assert opts['initial_prompt'] is None and opts['hotwords'] is None
        assert opts['condition_on_previous_text'] is False and opts['task'] == 'transcribe'
    assert options('large')['language'] is None
