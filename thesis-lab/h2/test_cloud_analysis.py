import pytest

from h2.cloud_analysis import analyze


def experiment():
    trials, rows = [], []
    for scenario in ("short", "mixed", "long"):
        for block in range(4):
            for variant in ("count", "work"):
                name = f"{scenario}-{block}-{variant}"
                trials.append({"id": name, "scenario": scenario, "block": block,
                    "variant": variant, "tasks": 24, "analysis_group": "primary"})
                rows.append({"trial": name, "accepted": 24, "correct": 24, "on_time": 24,
                    "valid": True, "lifecycle_complete": True,
                    "cost_lower_rub": 2 if variant == "count" else 1,
                    "cost_upper_rub": 2.02 if variant == "count" else 1.02})
    return {"trials": trials, "bootstrap_seed": 20261005, "required_on_time_rate": .95,
            "on_time_noninferiority_margin": .02}, rows


def test_missing_or_unobserved_lifecycles_cannot_be_dropped_from_a_successful_subset():
    plan, rows = experiment()
    result = analyze(plan, rows[:-1])
    assert not result["complete"] and not result["h2_confirmed"]
    rows[-1]["lifecycle_complete"] = False
    assert not analyze(plan, rows)["complete"]


def test_incorrect_or_unfinished_work_is_not_economical_success():
    plan, rows = experiment()
    rows[-1].update(correct=23, on_time=23)
    result = analyze(plan, rows)
    assert result["complete"] and not result["h2_confirmed"]
    assert not result["quality_passed"]


def test_cost_interval_is_conservative_and_pair_count_is_not_task_count():
    plan, rows = experiment()
    result = analyze(plan, rows, bootstrap_samples=100)
    assert result["h2_confirmed"]
    assert result["blocks"] == 12
    assert result["cost_ratio_ci95"] == pytest.approx([1.02 / 2, 1.02 / 2])
    assert result["totals"]["work"]["accepted"] == 288


def test_cheap_but_late_candidate_does_not_confirm_hypothesis():
    plan, rows = experiment()
    for row in rows:
        if row["trial"].endswith("work"):
            row["on_time"] = 20
    result = analyze(plan, rows, bootstrap_samples=100)
    assert result["cost_passed"] and not result["service_passed"]
    assert not result["noninferiority_passed"] and not result["h2_confirmed"]


def test_equal_costs_are_a_valid_negative_result():
    plan, rows = experiment()
    for row in rows:
        row.update(cost_lower_rub=2, cost_upper_rub=2.02)
    result = analyze(plan, rows, bootstrap_samples=100)
    assert result["complete"] and result["service_passed"]
    assert not result["cost_passed"] and not result["h2_confirmed"]
