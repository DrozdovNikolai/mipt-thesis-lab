"""The instrumentation must never mutate inference or leak hooks after failure."""

from types import SimpleNamespace

import pytest

from scripts.nus_failure_diagnosis import trace_decoder


class FakeModel:
    def get_prompt(self, tokenizer, previous_tokens, **kwargs):
        return [1] + previous_tokens

    def generate_with_fallback(self, encoder_output, prompt, tokenizer, options):
        return SimpleNamespace(sequences_ids=[[4, 5]], no_speech_prob=.1), -.2, 0., 1.1

    def _split_segments_by_timestamps(self, tokenizer, tokens, time_offset, segment_size, segment_duration, seek):
        return [{'start': time_offset, 'end': time_offset + segment_duration, 'tokens': tokens}], seek + segment_size, True

    def add_word_timestamps(self, segments, tokenizer, encoder_output, num_frames, prepend_punctuations, append_punctuations):
        segments[0][0]['words'] = [{'word': 'five', 'start': 0., 'end': 1., 'probability': .8}]


def test_instrumented_call_returns_original_values_and_records_seek():
    model = FakeModel()
    tokenizer = SimpleNamespace(decode=lambda tokens: 'five five')
    with trace_decoder(model) as trace:
        assert model.get_prompt(tokenizer, [2, 3]) == [1, 2, 3]
        result = model.generate_with_fallback(None, [1, 2, 3], tokenizer, None)
        assert result[0].sequences_ids == [[4, 5]]
        segments, seek, ending = model._split_segments_by_timestamps(tokenizer, [4, 5], 0., 2000, 20., 0)
        assert (seek, ending) == (2000, True)
        model.add_word_timestamps([segments], tokenizer, None, 2000, '', '')
    assert len(trace) == 1
    assert trace[0]['previous_token_count'] == 2
    assert trace[0]['input_seek_frames'] == 0
    assert trace[0]['seek_after_split_frames'] == 2000
    assert trace[0]['decoded_text'] == 'five five'
    assert trace[0]['aligned_segments'][0]['words'][0]['word'] == 'five'


@pytest.mark.parametrize('failure', [False, True])
def test_hooks_restored_even_on_failure(failure):
    model = FakeModel()
    names = ('get_prompt', 'generate_with_fallback', '_split_segments_by_timestamps', 'add_word_timestamps')
    originals = {name: getattr(model, name) for name in names}
    try:
        with trace_decoder(model):
            if failure:
                raise RuntimeError('decoder failed')
    except RuntimeError:
        pass
    assert all(getattr(model, name) == callback for name, callback in originals.items())


def test_sequential_requests_do_not_share_trace():
    model = FakeModel()
    tokenizer = SimpleNamespace(decode=lambda tokens: 'five five')
    with trace_decoder(model) as first:
        model.get_prompt(tokenizer, [99])
        model.generate_with_fallback(None, [1, 99], tokenizer, None)
    with trace_decoder(model) as second:
        model.get_prompt(tokenizer, [])
        model.generate_with_fallback(None, [1], tokenizer, None)
    assert first[0]['previous_token_count'] == 1
    assert second[0]['previous_token_count'] == 0
