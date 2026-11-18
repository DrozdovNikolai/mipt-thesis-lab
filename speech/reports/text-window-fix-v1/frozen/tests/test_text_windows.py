from types import SimpleNamespace

import numpy as np
import pytest
from faster_whisper import WhisperModel

from north55_speech.core import SpeechError
from north55_speech.text_windows import TextWindowWhisperModel, verify_backend


def loop_fixture(model_type=TextWindowWhisperModel, frames=227, silence=False):
    """Exercise the real installed seek loop; replace only neural computation."""
    model = object.__new__(model_type)
    model.feature_extractor = SimpleNamespace(time_per_frame=.01, nb_max_frames=3000)
    model.frames_per_second = 100
    model.time_precision = .02
    model.input_stride = 2
    model.logger = SimpleNamespace(isEnabledFor=lambda *_: False, debug=lambda *_: None)
    model.encode = lambda _: None
    model.get_prompt = lambda *_, **__: []
    vocabulary = {1: 'gear', 2: 'down', 3: 'fifty', 4: 'not', 5: 'fifteen'}
    tokens = [1, 2, 1, 2, 3, 4, 5]
    tokenizer = SimpleNamespace(timestamp_begin=1000, decode=lambda ts: ' '.join(vocabulary[t] for t in ts))
    calls = []

    def generate(*_):
        calls.append(len(calls))
        if len(calls) > (frames + 2999) // 3000:
            raise AssertionError('Completed window decoded again')
        return SimpleNamespace(sequences_ids=[tokens], no_speech_prob=1. if silence else 0.), -2. if silence else -.1, 0., 1.

    def align(batches, *_, **__):
        for batch in batches:
            for segment in batch:
                start = segment['start']
                end = start + .8 * (segment['end'] - start)
                # Deliberately leave a tail: word times must not drive the cursor.
                segment['end'] = end
                segment['words'] = [{'word': vocabulary[t], 'start': start + (end-start)*k/len(tokens),
                                     'end': start + (end-start)*(k+1)/len(tokens), 'probability': .9}
                                    for k, t in enumerate(tokens)]
    model.generate_with_fallback = generate
    model.add_word_timestamps = align
    options = SimpleNamespace(clip_timestamps='0', initial_prompt=None, multilingual=False,
        without_timestamps=True, prefix=None, hotwords=None, no_speech_threshold=.6,
        log_prob_threshold=-1., word_timestamps=True, hallucination_silence_threshold=None,
        prepend_punctuations='', append_punctuations='', condition_on_previous_text=True,
        prompt_reset_on_temperature=.5)
    features = np.zeros((80, frames + 1), dtype=np.float32)
    return model, features, tokenizer, options, calls


def test_audited_backend_available():
    verify_backend()


def test_one_window_preserves_repeats_numbers_and_real_word_boundaries():
    model, features, tokenizer, options, calls = loop_fixture()
    result = list(model.generate_segments(features, tokenizer, options, False))
    assert len(calls) == 1
    assert result[0].text == 'gear down gear down fifty not fifteen'
    assert result[0].words[-1].end < 2.27
    assert [w.word for w in result[0].words] == result[0].text.split()


def test_regression_fixture_detects_the_old_tail_loop():
    model, features, tokenizer, options, _ = loop_fixture(WhisperModel)
    with pytest.raises(AssertionError, match='decoded again'):
        list(model.generate_segments(features, tokenizer, options, False))


def test_long_audio_advances_to_next_full_window():
    model, features, tokenizer, options, calls = loop_fixture(frames=3100)
    result = list(model.generate_segments(features, tokenizer, options, False))
    assert len(calls) == 2
    assert [s.seek for s in result] == [0, 3000]
    assert result[1].start == 30
    assert result[0].text == result[1].text  # No cross-window text deduplication.


@pytest.mark.parametrize('frames', [0, 1, 227, 3100])
def test_silence_and_empty_inputs_terminate(frames):
    model, features, tokenizer, options, calls = loop_fixture(frames=frames, silence=True)
    assert list(model.generate_segments(features, tokenizer, options, False)) == []
    assert len(calls) == (frames + 2999) // 3000


@pytest.mark.parametrize('field,value', [('without_timestamps', False), ('hallucination_silence_threshold', 2.)])
def test_unsupported_seek_changing_modes_are_rejected(field, value):
    model, features, tokenizer, options, _ = loop_fixture()
    setattr(options, field, value)
    with pytest.raises(SpeechError):
        list(model.generate_segments(features, tokenizer, options, False))


def test_unexpected_timestamp_tokens_fail_instead_of_silent_reinterpretation():
    model, _, tokenizer, _, _ = loop_fixture()
    with pytest.raises(SpeechError, match='timestamp'):
        model._split_segments_by_timestamps(tokenizer, [1001], 0., 100, 1., 0)
