"""Synthetic code fixtures: these tests are not ML quality evidence."""

import json

import pytest
from pydantic import ValidationError

from north55_speech.core import SpeechError, confined
from north55_speech.journal import csv_safe, export_result
from north55_speech.nlp import EntityExtractor, EventClassifier, TextNormalizer, parse_number
from north55_speech.schemas import InferenceRequest, PipelineConfig, Review, Segment, UploadMetadata


def segment(text):
    return Segment(segment_id="fixture", start_sec=5, end_sec=10, raw_asr_text=text)


@pytest.mark.parametrize(
    "text",
    [
        "Flaps fifty, not fifteen.",
        "tree",
        "не выпускай шасси",
        "speed 160",
        "above, not below",
        "3.5 feet",
    ],
)
def test_no_unsafe_correction(text):
    sample = TextNormalizer().normalize(segment(text))
    assert sample.raw_asr_text == text
    assert sample.display_text == text


@pytest.mark.parametrize(
    "surface,value",
    [
        ("fifteen", 15),
        ("fifty", 50),
        ("one six zero", 160),
        ("пятнадцать", 15),
        ("пятьдесят", 50),
        ("сто шестьдесят", 160),
        ("1,5", 1.5),
    ],
)
def test_number_values(surface, value):
    assert parse_number(surface)[0] == value


def test_ambiguous_number_preserved():
    assert parse_number("one sixty") == (None, [160, 61])
    assert parse_number("tree")[0] is None
    assert parse_number("пятнадцати")[0] == 15
    assert parse_number("пятидесяти")[0] == 50


def test_entity_source_and_no_telemetry():
    sample = segment("Не выпускай шасси. flaps fifty; speed one six zero")
    found = EntityExtractor().extract(sample)
    assert [(e.type, e.canonical_value) for e in found] == [
        ("flaps_setting", 50),
        ("speed_mention", 160),
    ]
    for entity in found:
        assert sample.raw_asr_text[slice(*entity.source_span)] == entity.surface
        assert entity.evidence_kind == "speech"
        assert entity.unit is None
        assert entity.start_sec >= sample.start_sec
    unicode_sample = segment("Straße İ flaps fifteen")
    entity = EntityExtractor().extract(unicode_sample)[0]
    assert unicode_sample.raw_asr_text[slice(*entity.source_span)] == "fifteen"


@pytest.mark.parametrize(
    "text,value,unit",
    [
        ("flaps fifteen", 15, None),
        ("закрылки пятьдесят", 50, None),
        ("speed 160 knots", 160, "knots"),
        ("высота 1200 метров", 1200, "m"),
        ("heading 090 degrees", 90, "degrees"),
    ],
)
def test_entities(text, value, unit):
    entity = EntityExtractor().extract(segment(text))[0]
    assert (entity.canonical_value, entity.unit) == (value, unit)


def test_negation():
    assert EntityExtractor().extract(segment("not gear down"))[0].polarity == "negated"


def test_no_instructor_from_voice_or_unknown_role():
    assert EventClassifier().predict("try again")["labels"] == ["OTHER"]
    assert EventClassifier().predict("try again", role="instructor")["labels"] == [
        "INSTRUCTOR_FEEDBACK"
    ]
    assert EventClassifier().predict("checklist")["salient_for_review"] == "unknown"


@pytest.mark.parametrize(
    "extra",
    ["reference_text", "labels", "critical_entities", "initial_prompt", "ground_truth_language"],
)
def test_asr_contract_rejects_reference_fields(extra):
    with pytest.raises(ValidationError):
        InferenceRequest.model_validate(
            {
                "sample_id": "opaque",
                "audio_locator": "opaque/file",
                "audio_sha256": "a" * 64,
                extra: "gold",
            }
        )


def test_no_translation_and_no_degraded_baseline():
    with pytest.raises(ValidationError):
        PipelineConfig(task="translate")
    with pytest.raises(ValidationError):
        PipelineConfig(name="baseline", vad={"enabled": True})
    with pytest.raises(ValidationError):
        PipelineConfig(name="candidate", hotwords="fifteen")


@pytest.mark.parametrize("value", ["=HYPERLINK(x)", "+cmd", "-1+2", "@SUM(A1)", "  =1"])
def test_csv_formula_safety(value):
    assert csv_safe(value).startswith("'")


def test_exports_preserve_unicode_and_original():
    result = {
        "segments": [
            segment("шасси").model_dump() | {"display_text": "шасси", "reviewed_text": "Шасси."}
        ],
        "events": [],
    }
    vtt, _ = export_result(result, "vtt")
    assert "00:00:05.000 --> 00:00:10.000" in vtt and "Шасси." in vtt
    encoded, _ = export_result(result, "json")
    assert json.loads(encoded)["segments"][0]["raw_asr_text"] == "шасси"


def test_path_traversal_and_symlink_escape(tmp_path):
    with pytest.raises(SpeechError):
        confined(tmp_path, "../outside", False)
    outside = tmp_path.parent / "outside-test"
    outside.write_text("private")
    (tmp_path / "link").symlink_to(outside)
    with pytest.raises(SpeechError):
        confined(tmp_path, "link")


def test_rights_and_explicit_mapping():
    with pytest.raises(ValidationError):
        UploadMetadata(rights_confirmed=False, provenance="owner")
    with pytest.raises(ValidationError):
        UploadMetadata(rights_confirmed=True, provenance="owner", channel_mode="explicit_mapping")
    with pytest.raises(ValidationError):
        Review(
            expected_revision=0, author="a", reason="r", event_id="e", labels=["OTHER", "CHECKLIST"]
        )
