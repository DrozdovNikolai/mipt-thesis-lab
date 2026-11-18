from types import SimpleNamespace

import numpy as np
import pytest

from north55_speech.audio import RATE
from north55_speech.schemas import PipelineConfig
from scripts.decoding_diagnostics import VAD, select_inputs, transcribe_windows, validate_intervals


def test_diagnostic_vad_does_not_weaken_the_baseline_schema_guard():
    with pytest.raises(ValueError, match='baseline cannot'):
        PipelineConfig(name='baseline', vad=VAD)
    assert PipelineConfig(name='diagnostic-vad', vad=VAD).vad.enabled


def item(name, cohort, duration=20, eligible=True):
    return {'id': name, 'cohort': cohort, 'audio_sha256': name, 'duration_sec': duration,
            'reference_eligible': eligible, 'group_id': 'same-original-group'}


def test_selection_is_metadata_only_and_keeps_quiet_siblings_in_original_group():
    inputs = [item('human', 'partial_human_dev'), item('short', 'general_clean', 2),
              item('weak', 'publisher_weak_dev'), item('unaligned', 'publisher_weak_dev', eligible=False),
              item('test', 'unlisted_test'), item('noise1', 'noise_only', 300),
              item('noise2', 'bleriot_b_noise', 300)]
    selected = select_inputs(inputs)
    assert {i['id'] for i in selected} == {'human', 'short', 'weak', 'noise1', 'noise2', 'human--quiet12', 'short--quiet12'}
    assert all(i['group_id'] == 'same-original-group' for i in selected)
    assert all(i['reference_id'] == i['id'].removesuffix('--quiet12') for i in selected)
    assert inputs[0].get('gain_db') is None


@pytest.mark.parametrize('intervals', [[(-1, 2)], [(0, 11)], [(3, 2)], [(1, 5), (4, 8)]])
def test_invalid_or_overlapping_intervals_are_rejected(intervals):
    with pytest.raises(ValueError):
        validate_intervals(intervals, 10)


def test_speech_offsets_survive_pauses_and_repeated_commands_are_preserved():
    calls = []
    class Provider:
        def options(self, language):
            return {'language': language}

        def transcribe(self, audio, offset, language, prefix, checkpoint):
            calls.append((len(audio), offset, prefix))
            word = SimpleNamespace(start_sec=offset / RATE, end_sec=(offset + len(audio)) / RATE)
            return [SimpleNamespace(start_sec=word.start_sec, end_sec=word.end_sec, words=[word], raw_asr_text='gear down')]
    waveform = np.zeros(10 * RATE, dtype='float32')
    segments, windows = transcribe_windows(Provider(), waveform, [(RATE, 2 * RATE), (8 * RATE, 9 * RATE)], 'en', 'sample')
    assert [s.start_sec for s in segments] == [1, 8]
    assert [s.raw_asr_text for s in segments] == ['gear down', 'gear down']
    assert calls[0][1] == RATE and calls[1][1] == 8 * RATE
    assert len(windows) == 2 and calls[0][2] != calls[1][2]


def test_no_speech_skips_asr():
    class Provider:
        def transcribe(self, *args):
            raise AssertionError('ASR must not run on absent speech')
    assert transcribe_windows(Provider(), np.zeros(RATE), [], 'en', 'silent') == ([], [])


def test_alignment_outside_original_window_fails():
    class Provider:
        def transcribe(self, *args):
            return [SimpleNamespace(start_sec=0, end_sec=1, words=[])]
    with pytest.raises(ValueError, match='Alignment'):
        transcribe_windows(Provider(), np.zeros(3 * RATE), [(RATE, 2 * RATE)], 'en', 'sample')
