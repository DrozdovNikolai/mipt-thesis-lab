"""Metadata fixtures test claim boundaries; no real human labels are fabricated."""

from pathlib import Path

import pytest

from north55_speech.benchmark import annotation_cohort
from north55_speech.gates import load_acceptance
from tests.unit.test_data_gates import sample


def annotated_fixture(**changes):
    return sample(1, **{
        "language": "en", "speech_origin": "recorded_human", "scope": "simulator", "scope_verified": True,
        "reference_text": "unit fixture", "transcript_status": "human_verified", "labels": ["OTHER"],
        "events_status": "human_verified", "salient_for_review": False, "temporal_status": "human_verified",
        "events": [], "continuous_recording": True, "annotation_provenance": {"annotator": "unit fixture", "reviewed_audio": True},
        **changes,
    })


@pytest.mark.parametrize("task", ["events", "temporal"])
@pytest.mark.parametrize("change", [
    {"language": "fr"}, {"language": "ru"}, {"scope": "atc"}, {"scope_verified": False},
    {"speech_origin": "synthetic"}, {"annotation_provenance": {}},
    {"annotation_provenance": {"annotator": "fixture", "reviewed_audio": "false"}},
])
def test_other_languages_atc_synthetic_or_missing_review_cannot_support_en_claim(task, change):
    acceptance = load_acceptance(Path("configs/acceptance.yaml"))
    included, excluded = annotation_cohort([annotated_fixture(**change)], acceptance, task)
    assert included == [] and excluded[0]["reasons"]


def test_separate_event_and_temporal_requirements():
    acceptance = load_acceptance(Path("configs/acceptance.yaml"))
    assert annotation_cohort([annotated_fixture()], acceptance, "events")[0]
    assert annotation_cohort([annotated_fixture()], acceptance, "temporal")[0]
    assert not annotation_cohort([annotated_fixture(transcript_status="machine")], acceptance, "events")[0]
    assert not annotation_cohort([annotated_fixture(salient_for_review=None)], acceptance, "events")[0]
    assert not annotation_cohort([annotated_fixture(continuous_recording=False)], acceptance, "temporal")[0]


def test_verified_non_speech_controls_are_retained_for_temporal_false_positives():
    acceptance = load_acceptance(Path("configs/acceptance.yaml"))
    control = annotated_fixture(scope="non_speech", speech_origin="noise", language="unknown", reference_text="", events=[])
    assert annotation_cohort([control], acceptance, "temporal")[0] == [control]
    control.transcript_status = "machine"
    assert annotation_cohort([control], acceptance, "temporal")[0] == []
