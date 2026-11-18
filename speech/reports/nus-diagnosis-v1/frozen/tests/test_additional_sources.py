import pytest

from scripts.additional_asr_experiment import inference_regions
from scripts.cvr_context_experiment import contextual_texts
from scripts.prepare_cvr_native import eligibility, partition


@pytest.mark.parametrize('trial', ['vad_segments', 'vad_gate', 'vad_span', 'vad_gate_denoise'])
def test_noise_gate_does_not_call_asr_without_detected_speech(trial):
    assert inference_regions(320000, [], trial) == []
    assert inference_regions(320000, [], 'baseline') == [(0, 320000)]


def test_span_preserves_pause_and_original_timeline():
    regions = [(32000, 64000), (160000, 240000)]
    assert inference_regions(320000, regions, 'vad_span') == [(25600, 246400)]
    assert inference_regions(320000, regions, 'vad_gate') == [(0, 320000)]
    assert inference_regions(320000, regions, 'vad_segments') == regions
    assert inference_regions(320000, [(100, 319999)], 'vad_span') == [(0, 320000)]


def base_row():
    return {'analysis_data': '1', 'coding_row_type': '1', 'cvr_audio_source': 'CVR',
            'cvr_speaker_source': 'CAM-2', 'cvr_turn_speaker_raw': 'First Officer',
            'cvr_addressee': '[None provided]', 'coding_safety_voice': '1', 'cvr_message': 'Engine failure.'}


@pytest.mark.parametrize('change', [
    {'cvr_audio_source': 'ATC'}, {'cvr_speaker_source': 'RDO-2'},
    {'cvr_speaker_source': 'Pilot'}, {'cvr_turn_speaker_raw': 'ATC'},
    {'cvr_addressee': 'TOWER:'}, {'coding_safety_voice': ''},
    {'coding_row_type': '2'}, {'cvr_message': ' '},
])
def test_radio_unknown_scope_or_missing_labels_are_not_admitted(change):
    assert eligibility(base_row()) is None
    assert eligibility(base_row() | change) is not None


def test_source_negative_label_remains_explicit_and_split_ignores_text():
    assert eligibility(base_row() | {'coding_safety_voice': '0', 'cvr_message': 'All set.'}) is None
    assert partition('example-case') == partition('example-case')
    assert partition('example-case') in {'train', 'dev', 'test'}


def test_context_does_not_include_labels_future_cases_or_excluded_turns():
    rows = [
        {'id': 'noort-a-1', 'group_id': 'a', 'text': 'first', 'label': 'SECRET'},
        {'id': 'noort-a-2', 'group_id': 'a', 'text': 'second', 'label': 'SECRET'},
        {'id': 'noort-b-3', 'group_id': 'b', 'text': 'other case', 'label': 'SECRET'},
        {'id': 'noort-a-4', 'group_id': 'a', 'text': 'after excluded radio', 'label': 'SECRET'},
    ]
    result = contextual_texts(rows)
    assert result == ['CURRENT first', 'CURRENT second PREVIOUS first', 'CURRENT other case', 'CURRENT after excluded radio']
    rows[1]['text'] = 'future changed'
    assert contextual_texts(rows)[0] == result[0]
