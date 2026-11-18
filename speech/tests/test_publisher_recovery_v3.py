import pytest

from north55_speech.core import SpeechError
from north55_speech.publisher_pairs import RECOVERY_POLICY, validate_phrase_references
from scripts.publisher_recovery_rules_v3 import (
    compatible_text,
    fresh_reasons,
    mapped_tokens,
    normalize,
    ordered_nonoverlap,
    propose_subphrases,
)


def prediction(text):
    words = [{"word": " "+word, "start_sec": .4+i*.4, "end_sec": .7+i*.4, "probability": .95}
             for i, word in enumerate(text.split())]
    return {"hypothesis": text, "error": None, "segments": [{"words": words}]}


def slot_config():
    return {"document": "checklist", "slots": [{"id": "speeds", "source_line": "T.O SPEEDS & THRUST (BOTH)",
             "pattern": "takeoff speeds? and thrust (?P<value>{NUMBER})"}]}


def test_abbreviations_preserve_original_word_ranges_and_boundaries():
    words = [{"word": w} for w in ["APU", "pwr", "as", "required", "turnoff", "lights"]]
    result = mapped_tokens(words)
    assert normalize("powerful altitude") == "powerful altitude"
    assert [t for t in result if t["a"] == 4] == [
        {"text": "turn", "a": 4, "b": 5}, {"text": "off", "a": 4, "b": 5}]


def test_numeric_slot_recovers_audio_numbers_without_inventing_publisher_values():
    text = "takeoff speed and thrust 134 135 140"
    result = propose_subphrases(prediction(text), prediction(text),
                               {"checklist": "T.O SPEEDS & THRUST (BOTH)"}, slot_config(), 4)
    p = next(p for p in result if p["publisher"]["mode"] == "numeric_slot")
    assert p["target"] == text
    assert p["publisher"]["slot_numbers"] == ["134", "135", "140"]
    assert p["publisher"]["document_confirms_value"] is False
    assert not fresh_reasons(p, prediction(text), prediction(text), 4)
    assert fresh_reasons(p, prediction(text), prediction(text.replace("135", "136")), 4)


def test_disagreeing_number_is_not_accepted_as_slot():
    a, b = "takeoff speed and thrust 134 135 140", "takeoff speed and thrust 134 136 140"
    result = propose_subphrases(prediction(a), prediction(b),
                               {"checklist": "T.O SPEEDS & THRUST (BOTH)"}, slot_config(), 4)
    assert not any(p["publisher"]["mode"] == "numeric_slot" for p in result)


def test_critical_disagreements_survive_search_normalization():
    assert not compatible_text("landing gear down and locked", "landing gear up and locked")
    assert not compatible_text("do not set flaps fifteen", "do set flaps fifteen")
    assert not compatible_text("runway turnoff lights off", "runway turnoff lights on")


def test_fresh_audio_with_extra_word_rejects_cropped_target():
    target = "landing gear down and locked"
    assert fresh_reasons({"target": target}, prediction(target+" runway"), prediction(target), 4)


def test_timestamp_disagreement_holds_candidate():
    a = prediction("landing gear down and locked")
    b = prediction("landing gear down and locked")
    b["segments"][0]["words"][0]["start_sec"] += .5
    assert not propose_subphrases(a, b, {"checklist": "landing gear down and locked"},
                                 {"document": "unused", "slots": []}, 4)


def test_order_and_overlap_do_not_duplicate_training_audio():
    def c(start, end, position):
        return {"start_sec": start, "end_sec": end, "target": str(start),
                "publisher": {"document": "d", "start_token": position}}
    result = ordered_nonoverlap([c(0, 3, 10), c(2, 4, 11), c(4, 6, 5), c(4, 7, 12)])
    assert [(r["start_sec"], r["end_sec"]) for r in result] == [(0, 3), (4, 7)]


def test_recovery_cannot_use_old_policy_or_skip_fresh_recheck():
    from types import SimpleNamespace

    p = {"method": RECOVERY_POLICY, "publisher_supported": True, "publisher_transcript": False,
         "reviewed_audio": False, "annotator": None, "automatic_training_eligible": True,
         "eligibility_reasons": [], "language_verified": False,
         "target_origin": "cached_medium_word_span_with_two_fresh_audio_rechecks",
         "recheck_passed": True, "numeric_value_human_verified": False, "parent_clip_id": "parent",
         "publisher_match": {"mode": "numeric_slot", "slot_numbers": ["134"], "document_confirms_value": False}}
    for key in ("source_sha256", "document_bundle_sha256", "selection_plan_sha256", "small_prediction_sha256",
                "medium_prediction_sha256", "fresh_medium_sha256", "fresh_large_sha256"):
        p[key] = "a"*64
    sample = SimpleNamespace(transcript_status="weak", reference_text="takeoff speed 134", primary=False,
        scope_verified=False, scope="read_cockpit", speech_origin="recorded_human", rights_confirmed=True,
        language="en", clean_control=False, split="train", decoded_audio_sha256="b"*64, annotation_provenance=p)
    config = {"reference_policy": RECOVERY_POLICY, "quality_evidence": False, "selection_allowed": False}
    validate_phrase_references([sample], [], config)
    with pytest.raises(SpeechError):
        validate_phrase_references([sample], [], {**config, "reference_policy": "publisher_phrase_consensus_v2"})
    p["recheck_passed"] = False
    with pytest.raises(SpeechError):
        validate_phrase_references([sample], [], config)


def test_same_response_can_be_repeated_without_copying_both_into_target():
    text = "windows closed closed"
    config = {"document": "checklist", "slots": [], "fixed_repeats": [
        {"id": "windows", "source_line": "WINDOWS CLOSED (BOTH)", "pattern": "windows closed(?: closed)?"}]}
    result = propose_subphrases(prediction(text), prediction(text), {"checklist": "WINDOWS CLOSED (BOTH)"}, config, 3)
    assert result[0]["target"] == text and result[0]["publisher"]["mode"] == "repeated_response"
