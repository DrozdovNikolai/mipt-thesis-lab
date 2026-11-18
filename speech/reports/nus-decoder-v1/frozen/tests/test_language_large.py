import copy
import hashlib

import pytest

from scripts.acquire_large_v3 import validate_file
from scripts.language_large_experiment import declared_language


def reviewed():
    return {'split': 'dev', 'scope_verified': True, 'scope': 'read_cockpit',
        'language': 'en', 'transcript_status': 'human_verified',
        'annotation_provenance': {'reviewed_audio': True}, 'reference_text': 'hidden from policy'}


@pytest.mark.parametrize('change', [
    {'split': 'test'}, {'split': 'train'}, {'scope_verified': False},
    {'scope': 'atc'}, {'scope': 'unknown'}, {'language': 'fr'}, {'language': 'mixed'},
    {'transcript_status': 'weak'}, {'annotation_provenance': {'reviewed_audio': False}},
])
def test_unverified_or_non_english_metadata_cannot_force_english(change):
    item = {'id': 'reviewed-a', 'input_language': 'auto'}
    assert declared_language(item, {item['id']: reviewed() | change}) == 'auto'


def test_language_policy_uses_metadata_only_and_preserves_source():
    item = {'id': 'reviewed-a', 'input_language': 'auto'}
    review = reviewed()
    original = copy.deepcopy(review)
    assert declared_language(item, {item['id']: review}) == 'en'
    assert review == original and item['input_language'] == 'auto'
    review['reference_text'] = 'a different number fifty, negation, and script'
    assert declared_language(item, {item['id']: review}) == 'en'
    assert declared_language({'id': 'other', 'input_language': 'mixed'}, {item['id']: review}) == 'mixed'
    assert declared_language({'id': 'ru-control', 'input_language': 'ru'}, {}) == 'ru'


@pytest.mark.parametrize('lfs', [False, True])
def test_publisher_model_checksums_reject_changed_bytes(tmp_path, lfs):
    path = tmp_path / 'file'
    path.write_bytes(b'original')
    entry = {'size': 8, 'blobId': hashlib.sha1(b'blob 8\0original', usedforsecurity=False).hexdigest()}
    if lfs:
        entry['lfs'] = {'sha256': hashlib.sha256(b'original').hexdigest()}
    validate_file(path, entry)
    path.write_bytes(b'changed!')
    with pytest.raises(ValueError, match='checksum'):
        validate_file(path, entry)
    assert path.read_bytes() == b'changed!'
