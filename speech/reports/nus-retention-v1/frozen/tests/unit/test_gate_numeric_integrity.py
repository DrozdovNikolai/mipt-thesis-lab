"""Corrupted score fixtures must never produce a research PASS."""

import copy
from pathlib import Path

import pytest

from north55_speech.gates import asr_gate, load_acceptance, nlp_gate, temporal_gate
from tests.unit.test_data_gates import passing_fixture


@pytest.fixture
def acceptance():
    return load_acceptance(Path("configs/acceptance.yaml"))


def nlp_fixture(acceptance):
    minimum = acceptance["nlp_quality_gate"]["minimum_evidence"]
    evidence = {key: value for key, value in minimum.items() if key != "positives_per_claimed_label"}
    evidence["positives_per_label"] = {label: minimum["positives_per_claimed_label"]
                                      for label in acceptance["nlp_quality_gate"]["claimed_labels"]}
    return {"executed": True, "human_verified_labels": True, "evidence": evidence,
            "candidate_macro_f1": 0.9, "rules_macro_f1": 0.6,
            "end_to_end_salience": {"precision": 0.95, "recall": 0.95}}


def temporal_fixture():
    return {"executed": True, "human_verified_time_intervals": True, "continuous_recordings": True,
            "metrics": {"support": 100, "precision": 0.95, "recall": 0.95}}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), True, "0.25"])
@pytest.mark.parametrize("metric", ["baseline_wer", "candidate_wer", "clean_wer_increase", "critical_entity_f1_delta",
                                    "critical_entity_error_rate_delta", "language_en_wer_increase",
                                    "non_speech_inserted_words_per_minute_delta", "unhandled_runtime_failures"])
def test_asr_gate_rejects_invalid_numeric_metrics(acceptance, metric, value):
    report = passing_fixture(acceptance)
    report[metric] = value
    assert asr_gate(report, acceptance)["status"] == "FAIL"


@pytest.mark.parametrize("metric", ["candidate_macro_f1", "rules_macro_f1", "precision", "recall"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1, True, "0.9"])
def test_nlp_gate_rejects_invalid_scores(acceptance, metric, value):
    report = nlp_fixture(acceptance)
    (report["end_to_end_salience"] if metric in {"precision", "recall"} else report)[metric] = value
    assert nlp_gate(report, acceptance)["status"] == "FAIL"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1, True])
@pytest.mark.parametrize("metric", ["precision", "recall"])
def test_temporal_gate_rejects_invalid_scores(acceptance, metric, value):
    report = temporal_fixture()
    report["metrics"][metric] = value
    assert temporal_gate(report, acceptance)["status"] == "FAIL"


@pytest.mark.parametrize("gate_fn,builder,evidence_key", [
    (asr_gate, passing_fixture, "independent_groups"),
    (nlp_gate, nlp_fixture, "salience_positives"),
])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 20.5, True])
def test_invalid_evidence_counts_are_not_support(acceptance, gate_fn, builder, evidence_key, value):
    report = builder(acceptance)
    report["evidence"][evidence_key] = value
    assert gate_fn(report, acceptance)["status"] == "FAIL"


@pytest.mark.parametrize("change", [
    {"upper": float("nan")}, {"lower": float("inf")}, {"lower": 0.1, "upper": -0.1},
    {"method": "unpaired_bootstrap"}, {"resamples": 1}, {"seed": 56},
    {"confidence_level": 0.8}, {"independent_groups": 1}, {"delta_definition": "baseline - candidate"},
])
def test_asr_gate_rejects_wrong_or_corrupt_ci_protocol(acceptance, change):
    report = passing_fixture(acceptance)
    report["delta_ci"] = full_ci(acceptance) | change
    assert asr_gate(report, acceptance)["status"] == "FAIL"


def full_ci(acceptance):
    cfg = acceptance["asr_quality_gate"]["uncertainty"]
    return {"lower": -0.1, "upper": -0.01, "method": cfg["method"], "resamples": cfg["resamples"],
            "valid_resamples": cfg["resamples"], "seed": cfg["seed"], "confidence_level": cfg["confidence_level"],
            "independent_groups": acceptance["asr_quality_gate"]["minimum_evidence"]["independent_groups"],
            "delta_definition": cfg["delta_definition"]}


def test_missing_and_incomplete_ci_cannot_pass(acceptance):
    report = passing_fixture(acceptance)
    report["delta_ci"] = {"upper": -0.01}
    assert asr_gate(report, acceptance)["status"] == "INCONCLUSIVE"
    report["delta_ci"] = full_ci(acceptance) | {"valid_resamples": 1900}
    assert asr_gate(report, acceptance)["status"] == "INCONCLUSIVE"


def test_valid_scores_and_wer_above_one_remain_legal(acceptance):
    report = passing_fixture(acceptance) | {"baseline_wer": 1.4, "candidate_wer": 1.2,
                                           "delta_ci": full_ci(acceptance)}
    assert asr_gate(report, acceptance)["status"] == "PASS"
    assert nlp_gate(nlp_fixture(acceptance), acceptance)["status"] == "PASS"
    assert temporal_gate(temporal_fixture(), acceptance)["status"] == "PASS"


def test_missing_metrics_remain_missing_instead_of_zero(acceptance):
    report = nlp_fixture(acceptance)
    report["candidate_macro_f1"] = None
    assert nlp_gate(report, acceptance)["status"] == "NEEDS_MORE_DATA"
    temporal = copy.deepcopy(temporal_fixture())
    temporal["metrics"]["precision"] = None
    assert temporal_gate(temporal, acceptance)["status"] == "NEEDS_MORE_DATA"


@pytest.mark.parametrize("flag", ["executed", "human_verified_labels"])
def test_truthy_strings_do_not_attest_execution_or_human_review(acceptance, flag):
    report = nlp_fixture(acceptance)
    report[flag] = "false"
    assert nlp_gate(report, acceptance)["status"] != "PASS"
