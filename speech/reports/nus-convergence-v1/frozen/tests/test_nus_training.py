import hashlib

import pytest

from north55_speech.core import SpeechError
from north55_speech.lora import validate_references
from north55_speech.nus_training import GROUP, REVISION, RIGHTS, SOURCE, select_nus_rows
from tests.test_retraining import support
from tests.unit.test_publisher_training import pair

CONFIG = {'reference_policy': 'nus_sources_exploratory_v1', 'quality_evidence': False,
          'selection_allowed': False, 'max_steps': 240, 'eval_steps': 240,
          'permission_evidence_sha256': 'a'*64}


def nus():
    return pair(9, 'train').model_copy(update={
        'source_dataset': SOURCE, 'source_version': REVISION, 'license_id': RIGHTS,
        'scope': 'unknown', 'session_id': GROUP, 'recording_id': GROUP, 'speaker_ids': [],
        'reference_text': 'speed fifty', 'labels': None, 'events': None, 'critical_entities': None,
        'salient_for_review': None,
        'annotation_provenance': {'method': 'nus_source_reference_import_v1',
            'permission_evidence_sha256': 'a'*64, 'rights_basis': 'explicit_user_confirmation',
            'public_license_found': False, 'reviewed_audio': False, 'source_interval_known': False,
            'source_start_sec': None, 'source_end_sec': None,
            'source_reference_conflict': False, 'radio_text_indicator': False,
            'acquisition_sha256': 'b'*64, 'private_index_sha256': 'c'*64,
            'source_parquet_sha256': 'd'*64}})


def test_explicit_permission_preserves_weak_unknown_scope_status():
    row = nus()
    assert validate_references([row, support()], [pair(2, 'dev')], CONFIG) == CONFIG['reference_policy']
    assert row.transcript_status == 'weak' and row.scope == 'unknown'


@pytest.mark.parametrize('change', [
    {'transcript_status': 'human_verified'}, {'primary': True}, {'scope_verified': True},
    {'license_id': 'MIT'}, {'rights_confirmed': False}, {'split': 'test'},
    {'session_id': 'fabricated-independent-speaker'}, {'labels': ['CHECKLIST']},
    {'reference_text': 'Busan Tower Singapore 616'}, {'speaker_ids': ['guessed-pilot']},
])
def test_nus_cannot_launder_gold_rights_scope_or_test(change):
    with pytest.raises(SpeechError):
        validate_references([nus().model_copy(update=change), support()], [pair(2, 'dev')], CONFIG)


@pytest.mark.parametrize('change', [{'quality_evidence': True}, {'selection_allowed': True},
                                  {'max_steps': 500}, {'permission_evidence_sha256': ''}])
def test_no_unbounded_search_or_implicit_permission(change):
    with pytest.raises(SpeechError):
        validate_references([nus(), support()], [pair(2, 'dev')], CONFIG | change)


def test_duplicate_conflicts_and_radio_are_excluded_without_number_rewriting():
    def row(index, pcm, text):
        return {'row_id': str(index), 'pcm_sha256': pcm, 'source_reference_text': text,
                'normalized_text_sha256': hashlib.sha256(text.encode()).hexdigest(),
                'duration_sec': 2, 'sample_rate': 16000, 'channels': 1, 'peak': 0.2}
    rows = [row(0, 'a', 'speed fifty'), row(1, 'a', 'speed fifteen'),
            row(2, 'b', 'Busan Tower Singapore 616'), row(3, 'c', 'flaps fifteen'),
            row(4, 'c', 'flaps fifteen')]
    selected, excluded = select_nus_rows(rows)
    assert len(selected) == 1 and selected[0]['source_reference_text'] == 'flaps fifteen'
    assert len(excluded) == 2
