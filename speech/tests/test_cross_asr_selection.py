import math

import pytest

from north55_speech.cross_asr_selection import select_scores, shortcut, token_log_mean


def test_selection_uses_log_probabilities_and_requires_fixed_margin():
    assert token_log_mean([.25, 1.]) == pytest.approx(math.log(.5))
    assert select_scores({'whisper': -1., 'parakeet': -.91})['selected'] == 'whisper'
    assert select_scores({'whisper': -1., 'parakeet': -.89})['selected'] == 'parakeet'
    assert select_scores({'whisper': -1., 'parakeet': -1.})['selected'] == 'whisper'


def test_empty_response_is_required_not_missing_or_silent_fallback():
    assert shortcut('made up words', '', 'en')['reason'] == 'parakeet_empty'
    with pytest.raises(ValueError):
        shortcut('valid speech', None, 'en')
    assert shortcut('русский текст', None, 'ru')['selected'] == 'whisper'
    assert shortcut('', 'real words', 'en')['reason'] == 'whisper_empty'


def test_normalization_does_not_merge_critical_changes():
    assert shortcut('No amber or red.', 'NO AMBER OR RED', 'en')['reason'] == 'same_normalized_text'
    assert shortcut('No amber or red', 'amber or red', 'en') is None
    assert shortcut('heading 150', 'heading 160', 'en') is None
    assert shortcut('flaps up', 'flaps down', 'en') is None


def test_invalid_probabilities_and_unscoreable_candidates_are_explicit():
    for values in ([], [float('nan')], [1.01], [-.1]):
        with pytest.raises(ValueError):
            token_log_mean(values)
    assert math.isfinite(token_log_mean([0.]))
    assert select_scores({'whisper': None, 'parakeet': -.5})['reason'] == 'only_scoreable_candidate'
    with pytest.raises(ValueError):
        select_scores({'whisper': None, 'parakeet': None})
    with pytest.raises(ValueError):
        select_scores({'whisper': float('nan'), 'parakeet': -.5})
