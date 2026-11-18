"""Synthetic admission cases, not quality evidence."""
import pytest

from north55_speech.core import SpeechError
from north55_speech.lora import validate_references
from tests.unit.test_publisher_training import pair

CONFIG = {"reference_policy": "mixed_sources_exploratory_v1", "quality_evidence": False,
          "selection_allowed": False, "max_steps": 120, "eval_steps": 120}


def support():
    return pair(3, "train").model_copy(update={
        "source_dataset": "google/fleurs", "source_version": "70bb2e84b976b7e960aa89f1c648e09c59f894dd",
        "language": "ru", "scope": "general_control", "license_id": "CC-BY-4.0",
        "transcript_status": "human_verified", "reference_text": "человеческий текст",
        "labels": None, "events": None, "critical_entities": None, "salient_for_review": None,
        "events_status": "missing", "entities_status": "missing", "temporal_status": "missing",
        "annotation_provenance": {"method": "publisher_supervised_corpus_import", "annotator": "google/fleurs",
            "source_split": "train", "reviewed_audio": False, "local_manual_verification": False,
            "verification_scope": "publisher_provided_human_reference_not_local_audio_audit",
            "original_audio_sha256": "a"*64, "acquisition_sha256": "b"*64,
            "speaker_partition_basis": "publisher partition"}})


def test_both_arms_keep_weak_labels_and_old_policy_budget():
    for train in ([pair(1, "train")], [pair(1, "train"), support()]):
        assert validate_references(train, [pair(2, "dev")], CONFIG) == CONFIG["reference_policy"]
        assert train[0].transcript_status == "weak"
    with pytest.raises(SpeechError, match="40 optimizer"):
        validate_references([pair(1, "train")], [pair(2, "dev")],
                            CONFIG | {"reference_policy": "publisher_weak_exploratory_v1"})


@pytest.mark.parametrize("change", [
    {"split": "test"}, {"source_version": "unverified"}, {"scope": "cockpit"},
    {"transcript_status": "machine"}, {"labels": ["CHECKLIST"]},
    {"license_id": "unknown"}, {"rights_confirmed": False},
    {"decoded_audio_sha256": None}, {"language": "mixed"}, {"clean_control": True},
    {"audio_sha256": pair(2, "dev").audio_sha256},
])
def test_support_cannot_launder_labels_or_cross_splits(change):
    with pytest.raises(SpeechError):
        validate_references([pair(1, "train"), support().model_copy(update=change)], [pair(2, "dev")], CONFIG)


@pytest.mark.parametrize("change", [{"max_steps": 121}, {"eval_steps": 40},
    {"selection_allowed": True}, {"quality_evidence": True}])
def test_no_followup_search_or_release_claim(change):
    with pytest.raises(SpeechError):
        validate_references([pair(1, "train"), support()], [pair(2, "dev")], CONFIG | change)


def test_support_does_not_make_weak_dev_human():
    with pytest.raises(SpeechError):
        validate_references([pair(1, "train"), support()],
                            [pair(2, "dev").model_copy(update={"transcript_status": "human_verified"})], CONFIG)


def test_known_speaker_overlap_is_rejected():
    with pytest.raises(SpeechError, match="speaker identities"):
        validate_references([pair(1, "train"), support().model_copy(update={"speaker_ids": ["person"]})],
                            [pair(2, "dev").model_copy(update={"speaker_ids": ["person"]})], CONFIG)
