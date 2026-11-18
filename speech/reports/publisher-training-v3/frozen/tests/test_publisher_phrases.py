from types import SimpleNamespace

import pytest

from north55_speech.core import SpeechError
from north55_speech.publisher_pairs import PHRASE_POLICY, validate_phrase_references
from scripts.prepare_publisher_documents_v2 import clean_line, layout_metadata
from scripts.publisher_phrase_support import assess, search_normalize, support


def model_result(text, medium=False):
    words = [{"word": w, "start": i*.2, "end": i*.2+.1, "probability": .95}
             for i, w in enumerate(text.split())]
    result = {"hypothesis": text, "words": words, "error": None}
    if medium:
        result["segments"] = [{"words": [{"word": w["word"], "start_sec": w["start"],
                                         "end_sec": w["end"], "probability": w["probability"]} for w in words]}]
    return result


def test_list_number_removal_preserves_operational_values():
    assert clean_line("3 - TRQ . . . . Check max 100 %") == "TRQ Check max 100 %"
    assert clean_line("1.5 bar") == "1.5 bar"
    assert clean_line("1000 C maximum") == "1000 C maximum"
    assert clean_line("14. Oxygen OFF / 100% / OFF") == "Oxygen OFF / 100% / OFF"


def test_revision_header_is_not_a_flight_value():
    assert layout_metadata("Rev.: MAY - 2022")
    assert not layout_metadata("Below 10000 feet max 250 knots")


def test_abbreviations_are_only_search_equivalents():
    assert search_normalize("RWY turn off lights") == "runway turn off lights"
    assert search_normalize("E C A M memo") == "ecam memo"
    assert search_normalize("flaps fifteen") != search_normalize("flaps fifty")


def test_short_agreed_callout_survives_timestamp_at_zero():
    text = "gear up"
    d = {"script": {"lines": [{"text": "landing gear up"}]}}
    result = assess(model_result(text), model_result(text, True), d, 2)
    assert result["accepted"] and result["target"] == text


def test_short_callout_cannot_match_distant_words():
    assert support("gear down", "gear up taxi lights down")["coverage"] == 0


@pytest.mark.parametrize(("small", "medium", "reason"), [
    ("flaps fifteen", "flaps fifty", "numeric_disagreement"),
    ("gear up", "gear down", "state_or_negation_disagreement"),
    ("do not set flaps", "do set flaps", "state_or_negation_disagreement"),
])
def test_critical_model_disagreement_is_rejected(small, medium, reason):
    result = assess(model_result(small), model_result(medium, True),
                    {"script": {"lines": [{"text": medium}]}}, 5)
    assert not result["accepted"] and reason in result["reasons"]


def test_omitted_note_is_not_copied_into_training_target():
    text = "battery master on external power as required navigation lights on"
    script = "battery master on revision MAY 2022 external power as required navigation lights on"
    result = assess(model_result(text), model_result(text, True), {"script": {"lines": [{"text": script}]}}, 10)
    assert result["accepted"] and result["target"] == text
    assert "2022" not in result["target"]


def test_unpublished_numeric_value_is_rejected_despite_model_agreement():
    text = "set flaps fifteen and check all external lights are on"
    result = assess(model_result(text), model_result(text, True),
                    {"script": {"lines": [{"text": text.replace("fifteen", "fifty")}]}}, 10)
    assert not result["accepted"]
    assert "critical_token_not_supported_by_publisher" in result["reasons"]


def sample():
    p = {"method": PHRASE_POLICY, "publisher_supported": True, "publisher_transcript": False,
         "reviewed_audio": False, "annotator": None, "automatic_training_eligible": True,
         "eligibility_reasons": [], "language_verified": False, "target_origin": "unprompted_medium_en_prediction"}
    for key in ("source_sha256", "document_bundle_sha256", "selection_plan_sha256", "small_prediction_sha256", "medium_prediction_sha256"):
        p[key] = "a" * 64
    return SimpleNamespace(transcript_status="weak", reference_text="gear up", primary=False, scope_verified=False,
        scope="read_cockpit", speech_origin="recorded_human", rights_confirmed=True, language="en", clean_control=False,
        split="train", decoded_audio_sha256="b"*64, annotation_provenance=p)


def test_training_admission_remains_separate_from_human_gold():
    s = sample()
    config = {"quality_evidence": False, "selection_allowed": False}
    validate_phrase_references([s], [], config)
    s.transcript_status = "human_verified"
    with pytest.raises(SpeechError):
        validate_phrase_references([s], [], config)
    with pytest.raises(SpeechError):
        validate_phrase_references([sample()], [], {"quality_evidence": True, "selection_allowed": False})
