import pytest

from scripts.recover_publisher_language import LANGUAGE_REASON, assess, selected


def prediction(text):
    return {"hypothesis": text, "error": None, "segments": [{"words": [
        {"word": w, "start_sec": i * 0.2, "end_sec": i * 0.2 + 0.15, "probability": 0.9}
        for i, w in enumerate(text.split())]}]}


def test_only_language_rejected_train_can_be_recovered():
    row = {"split": "train", "annotation_provenance": {"eligibility_reasons": [LANGUAGE_REASON]}}
    assert selected(row)
    assert not selected(row | {"split": "dev"})
    assert not selected(row | {"split": "test"})
    row["annotation_provenance"]["eligibility_reasons"].append("numeric_disagreement_requires_review")
    assert not selected(row)


def test_exact_english_agreement_is_exploratory_eligible():
    text = "battery master on external power as required navigation lights on"
    assert assess(text, prediction(text), 20)["accepted"]


@pytest.mark.parametrize(("reference", "hypothesis", "reason"), [
    ("battery master on flaps fifteen external power as required navigation lights on",
     "battery master on flaps fifty external power as required navigation lights on", "numeric_disagreement"),
    ("battery master on do not set external power as required navigation lights on",
     "battery master on do set external power as required navigation lights on", "negation_disagreement"),
])
def test_critical_difference_blocks_otherwise_small_disagreement(reference, hypothesis, reason):
    decision = assess(reference, prediction(hypothesis), 20)
    assert decision["lexical_disagreement"] < 0.15
    assert not decision["accepted"]
    assert reason in decision["reasons"]


def test_runtime_failure_is_not_an_accepted_empty_result():
    assert assess("some target", {"error": "load failed"}, 20) == {
        "accepted": False, "reasons": ["runtime_failure"]}


def test_invalid_timeline_and_low_confidence_remain_rejected():
    text = "battery master on external power as required navigation lights on"
    response = prediction(text)
    for word in response["segments"][0]["words"]:
        word["probability"] = 0.1
    response["segments"][0]["words"][0]["end_sec"] = float("nan")
    decision = assess(text, response, 20)
    assert not decision["accepted"]
    assert set(decision["reasons"]) == {"low_second_model_score", "invalid_word_timeline"}
