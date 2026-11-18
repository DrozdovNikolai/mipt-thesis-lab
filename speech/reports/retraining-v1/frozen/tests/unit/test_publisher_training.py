"""Admission tests with synthetic metadata; never human annotation evidence."""

import pytest

from north55_speech.core import SpeechError
from north55_speech.lora import validate_references
from scripts.publisher_alignment import locate, number_tokens, tidy_line
from tests.unit.test_data_gates import sample


def pair(index, split):
    return sample(
        index,
        split=split,
        scope="read_cockpit",
        scope_verified=False,
        primary=False,
        transcript_status="weak",
        reference_text="flaps fifty",
        language="en",
        speech_origin="recorded_human",
        decoded_audio_sha256=str(index) * 64,
        annotation_provenance={
            "method": "publisher_columns_and_whisper_dtw_v1",
            "publisher_transcript": True,
            "automatic_training_eligible": True,
            "reviewed_audio": False,
            "annotator": None,
            "source_sha256": "a" * 64,
            "alignment_sha256": "b" * 64,
            "preparation_plan_sha256": "c" * 64,
            "eligibility_reasons": [],
        },
    )


POLICY = {
    "reference_policy": "publisher_weak_exploratory_v1",
    "quality_evidence": False,
    "selection_allowed": False,
    "max_steps": 40,
}


def test_supervised_path_still_rejects_machine_alignment():
    with pytest.raises(SpeechError, match="verified transcripts"):
        validate_references([pair(1, "train")], [pair(2, "dev")], {})


def test_explicit_weak_path_is_separate_and_keeps_status():
    train, dev = pair(1, "train"), pair(2, "dev")
    assert validate_references([train], [dev], POLICY) == "publisher_weak_exploratory_v1"
    assert train.transcript_status == dev.transcript_status == "weak"
    assert not train.primary and not train.annotation_provenance["reviewed_audio"]


@pytest.mark.parametrize(
    "change",
    [
        {"primary": True},
        {"scope_verified": True},
        {"transcript_status": "human_verified"},
        {"scope": "atc"},
        {"language": "fr"},
        {"clean_control": True},
        {"speech_origin": "synthetic"},
    ],
)
def test_weak_route_rejects_false_provenance_or_scope(change):
    invalid = pair(1, "train").model_copy(update=change)
    with pytest.raises(SpeechError, match="publisher-aligned"):
        validate_references([invalid], [pair(2, "dev")], POLICY)


@pytest.mark.parametrize(
    "change", [{"selection_allowed": True}, {"quality_evidence": True}, {"max_steps": 41}]
)
def test_experiment_budget_and_claim_limits(change):
    with pytest.raises(SpeechError):
        validate_references([pair(1, "train")], [pair(2, "dev")], POLICY | change)


def test_test_split_is_never_training_or_validation():
    with pytest.raises(SpeechError, match="partitions"):
        validate_references([pair(1, "train")], [pair(2, "test")], POLICY)


def test_typographical_cleaning_never_repairs_numbers():
    assert tidy_line("3. Flaps ........ fifty") == "flaps fifty"
    assert number_tokens("fifty") != number_tokens("fifteen")
    assert number_tokens("fifty") == number_tokens("50")
    document = {"blocks": [{"text": "engine mode normal flaps fifty gear down"}]}
    target = locate("engine mode normal flaps fifteen gear down", document)
    assert "fifty" in target["text"] and "fifteen" not in target["text"]
