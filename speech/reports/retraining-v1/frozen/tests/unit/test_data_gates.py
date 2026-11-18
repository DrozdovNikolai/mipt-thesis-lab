"""Synthetic acceptance fixtures verify refusal, not measured product quality."""

import copy
from pathlib import Path

import pytest

from north55_speech.core import SpeechError
from north55_speech.datasets import Sample, inference_projection, validate_groups
from north55_speech.gates import asr_gate, engineering_gate, load_acceptance, nlp_gate, promote


def sample(i, **changes):
    fields = dict(
        sample_id=f"sample{i}",
        audio_path=f"opaque/{i}",
        audio_sha256=str(i) * 64,
        source_dataset="synthetic-code-fixture",
        source_version="v1",
        recording_id=f"rec{i}",
        session_id=f"session{i}",
        original_utterance_id=f"u{i}",
        language="ru",
        input_language="auto",
        scope="simulator",
        speech_origin="synthetic",
        duration_sec=1,
        license_id="test",
        provenance="unit-test",
        rights_confirmed=True,
    )
    return Sample.model_validate(fields | changes)


def test_transitive_speaker_session_variant_group():
    samples = [
        sample(1, speaker_ids=["a"]),
        sample(2, speaker_ids=["a", "b"]),
        sample(3, speaker_ids=["b"]),
        sample(4, variant_of="sample3", original_utterance_id="u3"),
    ]
    assert validate_groups(samples, assign=True)["independent_groups"] == 1
    assert len({s.split for s in samples}) == 1


def test_clean_noisy_cross_split_rejected():
    with pytest.raises(SpeechError, match="crosses splits"):
        validate_groups([sample(1, split="train"), sample(2, split="test", variant_of="sample1")])


def test_decoded_duplicate_rejected():
    with pytest.raises(SpeechError):
        validate_groups(
            [
                sample(1, split="train", decoded_audio_sha256="f" * 64),
                sample(2, split="test", decoded_audio_sha256="f" * 64),
            ]
        )


def test_no_data_preflight_does_not_claim_executed_inference():
    acceptance = load_acceptance(Path("configs/acceptance.yaml"))
    assert asr_gate({"executed": False, "evidence": {}}, acceptance)["status"] == "NEEDS_MORE_DATA"


def test_projection_no_reference_or_gold_auto_language():
    request = inference_projection(
        sample(1, reference_text="private gold", transcript_status="machine")
    )
    assert request.language == "auto"
    assert "private gold" not in request.model_dump_json()
    assert "reference_text" not in request.model_dump()


@pytest.fixture
def acceptance():
    return load_acceptance(Path("configs/acceptance.yaml"))


def passing_fixture(acceptance):
    report = {
        "executed": True,
        "evidence": copy.deepcopy(acceptance["asr_quality_gate"]["minimum_evidence"]),
        "baseline_wer": 0.3,
        "candidate_wer": 0.25,
        "delta_ci": {"lower": -0.1, "upper": -0.01, "method": "paired_cluster_bootstrap",
                     "resamples": 2000, "valid_resamples": 2000, "seed": 55,
                     "confidence_level": 0.95, "independent_groups": 20,
                     "delta_definition": "candidate - baseline"},
        "critical_entity_f1_delta": 0,
        "critical_entity_error_rate_delta": 0,
        "clean_wer_increase": 0,
        "non_speech_inserted_words_per_minute_delta": 0,
        "unhandled_runtime_failures": 0,
        "language_en_wer_increase": 0,
    }
    return report


def test_gate_all_statuses(acceptance):
    r = passing_fixture(acceptance)
    assert asr_gate(r, acceptance)["status"] == "PASS"
    assert asr_gate(r | {"candidate_wer": 0.29}, acceptance)["status"] == "FAIL"
    assert asr_gate(r | {"delta_ci": {"upper": 0}}, acceptance)["status"] == "INCONCLUSIVE"
    assert asr_gate(r | {"evidence": {}}, acceptance)["status"] == "NEEDS_MORE_DATA"
    assert asr_gate(r | {"blocked": ["weights"]}, acceptance)["status"] == "BLOCKED"
    assert asr_gate(r | {"executed": False}, acceptance)["status"] == "NOT_RUN"
    assert asr_gate(r | {"baseline_wer": 0}, acceptance)["status"] == "INCONCLUSIVE"


def test_missing_guardrail_and_runtime_failure(acceptance):
    r = passing_fixture(acceptance)
    assert asr_gate(r | {"clean_wer_increase": None}, acceptance)["status"] == "NEEDS_MORE_DATA"
    assert asr_gate(r | {"unhandled_runtime_failures": 1}, acceptance)["status"] == "FAIL"
    assert asr_gate(r | {"critical_entity_f1_delta": -0.001}, acceptance)["status"] == "FAIL"


def test_acceptance_tampering_rejected(tmp_path):
    altered = tmp_path / "acceptance.yaml"
    altered.write_text(
        Path("configs/acceptance.yaml")
        .read_text()
        .replace("minimum_relative_wer_reduction: 0.10", "minimum_relative_wer_reduction: 0.01")
    )
    with pytest.raises(SpeechError):
        load_acceptance(altered)


def test_skips_not_engineering_pass(acceptance):
    assert engineering_gate({}, acceptance)["status"] == "BLOCKED"
    assert nlp_gate({}, acceptance)["status"] == "NEEDS_MORE_DATA"


def test_cannot_promote_without_gates(tmp_path):
    (tmp_path / "gate.json").write_text("{}")
    with pytest.raises(SpeechError):
        promote(tmp_path, tmp_path / "release.json", {})
    assert not (tmp_path / "release.json").exists()
