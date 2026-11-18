from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import create_model

from north55_speech.core import SpeechError, StrictModel, file_hash, read_yaml

ACCEPTANCE_SHA256 = "32d35b1e80b64f38e6adcc9895515b37f224a9e51dcf5ff95389e1f9ecc45071"
STATUSES = {"PASS", "FAIL", "INCONCLUSIVE", "NEEDS_MORE_DATA", "BLOCKED", "NOT_RUN"}
EXIT_CODES = {
    "PASS": 0,
    "FAIL": 3,
    "INCONCLUSIVE": 4,
    "NEEDS_MORE_DATA": 4,
    "BLOCKED": 5,
    "NOT_RUN": 5,
}


def contract_model(value: dict, name="Acceptance"):
    fields: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            fields[key] = (contract_model(item, name + "_" + key), ...)
        elif isinstance(item, list):
            fields[key] = (list[str] if all(isinstance(x, str) for x in item) else list[Any], ...)
        else:
            fields[key] = (Literal[item], ...)
    return create_model(name, __base__=StrictModel, **fields)


def load_acceptance(path: Path) -> dict:
    if file_hash(path) != ACCEPTANCE_SHA256:
        raise SpeechError(
            "ACCEPTANCE_CHANGED", "Normative acceptance bytes differ; thresholds cannot be relaxed"
        )
    data = read_yaml(path)
    contract_model(data).model_validate(data)
    return data


def acceptance_schema(path: Path) -> dict:
    return contract_model(load_acceptance(path)).model_json_schema()


def gate(status: str, reasons: list[str], **metrics) -> dict:
    if status not in STATUSES:
        raise ValueError(status)
    return {"status": status, "reasons": reasons, **metrics}


def _number_errors(
    values: dict,
    rules: dict[str, tuple[float | None, float | None, bool]],
    prefix: str = "",
) -> list[str]:
    """Missing values remain missing. Corrupt values must not bypass comparisons."""
    errors = []
    for name, (lower, upper, integer) in rules.items():
        value = values.get(name)
        if value is None:
            continue
        try:
            finite = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            errors.append("invalid_numeric_metric:" + prefix + name)
        elif ((lower is not None and value < lower) or (upper is not None and value > upper)
              or (integer and value != int(value))):
            errors.append("out_of_range_metric:" + prefix + name)
    return errors


def _ci_gate(report: dict, cfg: dict, gain: float) -> dict:
    ci = report.get("delta_ci") or {}
    if not isinstance(ci, dict):
        return gate("FAIL", ["invalid_bootstrap_interval"])
    errors = _number_errors(ci, {
        "lower": (None, None, False), "upper": (None, None, False),
        "resamples": (1, None, True), "valid_resamples": (0, None, True),
        "independent_groups": (1, None, True), "seed": (0, None, True),
        "confidence_level": (0, 1, False),
    }, "delta_ci.")
    if errors:
        return gate("FAIL", errors)
    uncertainty = cfg["uncertainty"]
    expected = {key: uncertainty[key] for key in ("method", "resamples", "seed", "confidence_level", "delta_definition")}
    expected["independent_groups"] = report["evidence"]["independent_groups"]
    if any(ci.get(key) is None for key in {*expected, "lower", "upper", "valid_resamples"}):
        return gate("INCONCLUSIVE", ["missing_bootstrap_protocol_or_interval"], relative_wer_reduction=gain)
    errors = ["bootstrap_protocol_mismatch:" + key for key, value in expected.items() if ci[key] != value]
    if ci["lower"] > ci["upper"]:
        errors.append("inverted_bootstrap_interval")
    if ci["valid_resamples"] > ci["resamples"]:
        errors.append("invalid_bootstrap_resample_count")
    if errors:
        return gate("FAIL", errors)
    if ci["valid_resamples"] < ci["resamples"]:
        return gate("INCONCLUSIVE", ["insufficient_valid_bootstrap_resamples"], relative_wer_reduction=gain)
    if ci["upper"] >= uncertainty["required_delta_ci_upper_strictly_less_than"]:
        return gate("INCONCLUSIVE", ["paired_cluster_ci_does_not_confirm_improvement"], relative_wer_reduction=gain)
    return gate("PASS", [], relative_wer_reduction=gain)


def asr_gate(report: dict, acceptance: dict) -> dict:
    cfg = acceptance["asr_quality_gate"]
    if report.get("integrity_errors"):
        return gate("FAIL", report["integrity_errors"])
    if report.get("blocked"):
        return gate("BLOCKED", report["blocked"])
    evidence = report.get("evidence", {})
    if not isinstance(evidence, dict):
        return gate("FAIL", ["invalid_evidence"])
    errors = _number_errors(evidence, {
        name: (0, None, name != "non_speech_control_minutes") for name in cfg["minimum_evidence"]
    }, "evidence.")
    errors += _number_errors(report, {
        "baseline_wer": (0, None, False), "candidate_wer": (0, None, False),
        "critical_entity_f1_delta": (-1, 1, False),
        "critical_entity_error_rate_delta": (None, None, False),
        "clean_wer_increase": (None, None, False),
        "non_speech_inserted_words_per_minute_delta": (None, None, False),
        "unhandled_runtime_failures": (0, None, True),
        **{f"language_{language}_wer_increase": (None, None, False)
           for language in acceptance["scope"]["primary_language_scope"]},
    })
    if errors:
        return gate("FAIL", errors)
    missing = [
        f"{name}: {evidence.get(name, 0)} < {minimum}"
        for name, minimum in cfg["minimum_evidence"].items()
        if (evidence.get(name) or 0) < minimum
    ]
    missing.extend(report.get("missing_annotations", []))
    if missing:
        return gate("NEEDS_MORE_DATA", missing)
    if report.get("executed") is not True:
        return gate("NOT_RUN", ["inference_not_executed"])
    baseline, candidate = report.get("baseline_wer"), report.get("candidate_wer")
    if baseline is None or candidate is None:
        return gate("NEEDS_MORE_DATA", ["wer_not_measured"])
    if baseline == 0:
        return gate("INCONCLUSIVE", ["baseline_zero_wer"])
    guardrails = cfg["guardrails"]
    required = {
        "critical_entity_f1_delta": (guardrails["minimum_critical_entity_f1_delta"], "min"),
        "critical_entity_error_rate_delta": (
            guardrails["maximum_critical_entity_error_rate_delta"],
            "max",
        ),
        "clean_wer_increase": (guardrails["maximum_clean_wer_absolute_increase"], "max"),
        "non_speech_inserted_words_per_minute_delta": (
            guardrails["maximum_non_speech_inserted_words_per_minute_delta"],
            "max",
        ),
        "unhandled_runtime_failures": (guardrails["maximum_unhandled_runtime_failures"], "max"),
    }
    for language in acceptance["scope"]["primary_language_scope"]:
        required[f"language_{language}_wer_increase"] = (
            guardrails["maximum_validated_language_wer_absolute_increase"],
            "max",
        )
    missing_guardrails = [key for key in required if report.get(key) is None]
    if missing_guardrails:
        return gate("NEEDS_MORE_DATA", ["missing_guardrail:" + key for key in missing_guardrails])
    failed = [
        key
        for key, (limit, op) in required.items()
        if (report[key] < limit if op == "min" else report[key] > limit)
    ]
    gain = (baseline - candidate) / baseline
    if gain + 1e-12 < cfg["minimum_relative_wer_reduction"]:
        failed.append("minimum_relative_wer_reduction")
    if failed:
        return gate("FAIL", failed, relative_wer_reduction=gain)
    return _ci_gate(report, cfg, gain)


def nlp_gate(report: dict, acceptance: dict) -> dict:
    cfg = acceptance["nlp_quality_gate"]
    if report.get("integrity_errors"):
        return gate("FAIL", report["integrity_errors"])
    evidence = report.get("evidence", {})
    salience = report.get("end_to_end_salience") or {}
    if not isinstance(evidence, dict) or not isinstance(salience, dict):
        return gate("FAIL", ["invalid_nlp_report_structure"])
    positives = evidence.get("positives_per_label") or {}
    if not isinstance(positives, dict):
        return gate("FAIL", ["invalid_positive_support"])
    errors = _number_errors(evidence, {
        key: (0, None, True) for key in cfg["minimum_evidence"] if key != "positives_per_claimed_label"
    }, "evidence.")
    errors += _number_errors(positives, {label: (0, None, True) for label in cfg["claimed_labels"]}, "positives_per_label.")
    errors += _number_errors(report, {key: (0, 1, False) for key in ("candidate_macro_f1", "rules_macro_f1")})
    errors += _number_errors(salience, {key: (0, 1, False) for key in ("precision", "recall")}, "end_to_end_salience.")
    if errors:
        return gate("FAIL", errors)
    missing = []
    for key, value in cfg["minimum_evidence"].items():
        if key == "positives_per_claimed_label":
            missing += [
                f"insufficient_positive_support:{label}"
                for label in cfg["claimed_labels"]
                if (positives.get(label) or 0) < value
            ]
        elif (evidence.get(key) or 0) < value:
            missing.append("insufficient_evidence:" + key)
    if missing or report.get("human_verified_labels") is not True:
        return gate(
            "NEEDS_MORE_DATA",
            missing
            + ([] if report.get("human_verified_labels") is True else ["missing_human_event_labels"]),
        )
    if report.get("executed") is not True:
        return gate("NOT_RUN", ["trained_classifier_not_evaluated"])
    candidate, baseline = report.get("candidate_macro_f1"), report.get("rules_macro_f1")
    if any(
        v is None for v in [candidate, baseline, salience.get("precision"), salience.get("recall")]
    ):
        return gate("NEEDS_MORE_DATA", ["required_nlp_metrics_missing"])
    assert candidate is not None and baseline is not None
    failures = []
    if candidate < cfg["text_level_comparison"]["minimum_macro_f1"]:
        failures.append("minimum_macro_f1")
    if candidate - baseline < cfg["text_level_comparison"]["minimum_macro_f1_absolute_gain"]:
        failures.append("minimum_macro_f1_absolute_gain")
    for key in ("precision", "recall"):
        if salience[key] < cfg["end_to_end_salience"]["minimum_" + key]:
            failures.append("end_to_end_salience_" + key)
    return gate("FAIL" if failures else "PASS", failures)


def engineering_gate(checks: dict, acceptance: dict) -> dict:
    required = [
        key
        for key, enabled in acceptance["engineering_gate"].items()
        if key.startswith("require_") and enabled
    ]
    failed = [key for key in required if checks.get(key) == "FAIL"]
    missing = [key for key in required if checks.get(key) != "PASS"]
    return gate("FAIL" if failed else "BLOCKED" if missing else "PASS", failed or missing)


def temporal_gate(report: dict, acceptance: dict) -> dict:
    if report.get("integrity_errors"):
        return gate("FAIL", report["integrity_errors"])
    metrics = report.get("metrics") or {}
    if not isinstance(metrics, dict):
        return gate("FAIL", ["invalid_temporal_metrics"])
    errors = _number_errors(metrics, {"support": (0, None, True), "precision": (0, 1, False), "recall": (0, 1, False)}, "metrics.")
    if errors:
        return gate("FAIL", errors)
    if report.get("human_verified_time_intervals") is not True or report.get("continuous_recordings") is not True:
        return gate(
            "NEEDS_MORE_DATA", ["missing_human_temporal_annotations_on_continuous_recordings"]
        )
    if report.get("executed") is not True:
        return gate("NOT_RUN", ["temporal_inference_not_executed"])
    if not metrics.get("support") or any(metrics.get(key) is None for key in ("precision", "recall")):
        return gate("NEEDS_MORE_DATA", ["missing_salient_temporal_event_support"])
    cfg = acceptance["temporal_event_gate"]
    failed = [
        key
        for key in ("precision", "recall")
        if metrics.get(key, 0) < cfg["minimum_salient_event_" + key]
    ]
    return gate("FAIL" if failed else "PASS", failed, metrics=metrics)


def promote(run: Path, release: Path, current_hashes: dict) -> dict:
    from north55_speech.core import atomic_json

    report = json.loads((run / "gate.json").read_text(encoding="utf-8"))
    for key in ("engineering_gate", "asr_quality_gate", "nlp_quality_gate"):
        if report.get(key, {}).get("status") != "PASS":
            raise SpeechError("PROMOTION_DENIED", f"Required gate lacks PASS: {key}")
    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
    required = {"code", "data", "config", "model", "scorer", "acceptance"}
    if set(current_hashes) != required or manifest.get("hashes") != current_hashes:
        raise SpeechError(
            "PROMOTION_HASH_MISMATCH", "Code/data/config/model/scorer/acceptance hashes must match"
        )
    pointer = {
        "run_id": run.name,
        "hashes": current_hashes,
        "validated_scope": report.get("validated_scope", []),
    }
    selection = json.loads((run / "selection.lock.json").read_text())
    pointer["pipeline"] = selection["candidate"]
    if not pointer["validated_scope"]:
        raise SpeechError(
            "PROMOTION_SCOPE_MISSING", "Passing release requires an explicit validated scope"
        )
    atomic_json(release, pointer)
    return pointer
