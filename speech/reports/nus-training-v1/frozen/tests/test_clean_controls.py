"""Controls must not silently select easy answers or drop failed runs."""

import pytest

from scripts.evaluate_clean_controls import (
    choose_ids,
    clean_guardrail,
    member_id,
    validate_record,
)


def test_sampling_is_input_order_independent_and_excludes_previous_reader():
    ids = [f"{speaker}-10-{utterance:04}" for speaker in (1, 2, 3, 2277) for utterance in range(5)]
    chosen = choose_ids(ids, 8)
    assert chosen == choose_ids(list(reversed(ids)), 8)
    assert len(set(chosen)) == 8
    assert {s.split("-")[0] for s in chosen[:3]} == {"1", "2", "3"}
    assert not any(s.startswith("2277-") for s in chosen)


def test_sampling_fails_instead_of_duplicating_or_substituting():
    with pytest.raises(ValueError, match="Duplicate"):
        choose_ids(["1-1-1", "1-1-1"], 2)
    with pytest.raises(ValueError, match="Insufficient"):
        choose_ids(["2277-1-1", "1-1-1"], 2)


@pytest.mark.parametrize("name", [
    "../../1-2-3.flac", "LibriSpeech/dev-clean/1/2/9-2-3.flac",
    "LibriSpeech/test-clean/1/2/1-2-3.flac", "LibriSpeech/dev-clean/1/2/1-2-3.flac/evil",
])
def test_archive_audio_path_rejects_traversal_test_data_and_mismatched_identity(name):
    with pytest.raises(ValueError, match="Unsafe or inconsistent"):
        member_id(name)
    assert member_id("LibriSpeech/dev-clean/1/2/1-2-0003.flac") == "1-2-0003"


def test_clean_tolerance_does_not_hide_failures_or_missing_samples():
    guard = {"minimum_utterances": 50, "maximum_runtime_failures": 0, "maximum_clean_wer_absolute_increase": .01}
    assert clean_guardrail(.02, .0299, 50, 0, guard) == "PASS"
    assert clean_guardrail(.02, .0301, 50, 0, guard) == "FAIL"
    assert clean_guardrail(.02, .01, 50, 1, guard) == "FAIL"
    assert clean_guardrail(.02, .01, 49, 0, guard) == "NEEDS_MORE_DATA"
    assert clean_guardrail(None, None, 50, 0, guard) == "NEEDS_MORE_DATA"


def test_resume_rejects_changed_audio_model_plan_and_nonempty_failed_hypothesis():
    item = {"id": "1-2-3", "audio_sha256": "audio"}
    record = {**item, "system": "parent", "model": "frozen-model", "plan_sha256": "plan", "runtime_failure": None, "hypothesis": "real output"}
    validate_record(record, item, "parent", "frozen-model", "plan")
    for key in ("audio_sha256", "model", "plan_sha256"):
        with pytest.raises(ValueError, match="different frozen"):
            validate_record({**record, key: "changed"}, item, "parent", "frozen-model", "plan")
    with pytest.raises(ValueError, match="empty hypothesis"):
        validate_record({**record, "runtime_failure": {"type": "RuntimeError"}}, item, "parent", "frozen-model", "plan")
