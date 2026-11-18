import copy

import pytest

from north55_speech.core import SpeechError
from scripts.assemble_quality_pairs import checked_groups
from tests.unit.test_publisher_training import pair


def test_derived_clip_groups_do_not_rewrite_frozen_development_metadata():
    train, dev = pair(1, 'train'), pair(2, 'dev')
    train.group_id, dev.group_id = 'original-population-train', 'original-population-dev'
    before = copy.deepcopy(dev.model_dump())
    report = checked_groups([train], [dev])
    assert train.group_id != 'original-population-train'
    assert dev.model_dump() == before
    assert report['split_groups'] == {'train': 1, 'dev': 1, 'test': 0}


def test_derived_groups_still_reject_shared_speaker_across_splits():
    train, dev = pair(1, 'train'), pair(2, 'dev')
    train.speaker_ids = ['shared-test-speaker']
    dev.speaker_ids = ['shared-test-speaker']
    with pytest.raises(SpeechError, match='crosses splits'):
        checked_groups([train], [dev])
