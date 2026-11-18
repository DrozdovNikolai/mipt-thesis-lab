"""Paired, scenario-stratified analysis; incomplete plans cannot confirm H2."""
from collections import defaultdict
import math

import numpy as np


def analyze(plan, rows, *, bootstrap_samples=20000):
    planned = [x for x in plan["trials"] if x["analysis_group"] == "primary"]
    expected = {x["id"] for x in planned}
    if len(expected) != len(planned) or len({x["trial"] for x in rows}) != len(rows):
        raise ValueError("Duplicate planned or observed trial")
    indexed = {x["trial"]: x for x in rows if x["trial"] in expected}
    missing = sorted(expected - indexed.keys())
    invalid = sorted(k for k, x in indexed.items() if not x["valid"] or not x["lifecycle_complete"])
    if missing or invalid:
        return {"complete": False, "h2_confirmed": False, "missing_trials": missing,
                "invalid_trials": invalid, "reason": "Keep every planned block; do not analyze a successful subset as confirmation."}
    blocks = defaultdict(dict)
    for trial in planned:
        row = indexed[trial["id"]]
        if row["accepted"] != trial["tasks"]:
            raise ValueError("Observed accepted tasks differ from frozen admission plan")
        if not 0 <= row["on_time"] <= row["correct"] <= row["accepted"]:
            raise ValueError("Invalid result counts")
        low, high = row["cost_lower_rub"], row["cost_upper_rub"]
        if not (math.isfinite(low) and math.isfinite(high) and 0 < low <= high):
            raise ValueError("Incomplete cost accounting")
        key = (trial["scenario"], trial["block"])
        if trial["variant"] in blocks[key]:
            raise ValueError("Duplicate variant in a block")
        blocks[key][trial["variant"]] = row
    if any(set(pair) != {"count", "work"} for pair in blocks.values()):
        raise ValueError("Every primary block requires both variants")
    strata = defaultdict(list)
    for (scenario, block), pair in sorted(blocks.items()):
        strata[scenario].append(pair)
    if any(len(pairs) < 2 for pairs in strata.values()):
        raise ValueError("At least two independent blocks per scenario are required for resampling")

    def metrics(pairs):
        result = {}
        for variant in ("count", "work"):
            selected = [x[variant] for x in pairs]
            result[variant] = {field: sum(x[field] for x in selected) for field in
                ("accepted", "correct", "on_time", "cost_lower_rub", "cost_upper_rub")}
        count, work = result["count"], result["work"]
        ratio = ((work["cost_upper_rub"] / work["correct"]) /
                 (count["cost_lower_rub"] / count["correct"])) if count["correct"] and work["correct"] else math.inf
        delta = work["on_time"] / work["accepted"] - count["on_time"] / count["accepted"]
        return ratio, delta, result

    all_pairs = [pair for pairs in strata.values() for pair in pairs]
    ratio, delta, totals = metrics(all_pairs)
    per_scenario = {name: metrics(pairs)[2] for name, pairs in strata.items()}
    quality_passed = all(x["correct"] == x["accepted"] for x in totals.values())
    service_passed = all(x["on_time"] / x["accepted"] >= plan["required_on_time_rate"]
        for scenario in per_scenario.values() for x in scenario.values())
    if not quality_passed:
        return {"complete": True, "h2_confirmed": False, "quality_passed": False, "totals": totals,
                "per_scenario": per_scenario, "reason": "Incorrect or unfinished results remain in the denominator; no savings claim."}
    rng = np.random.default_rng(plan["bootstrap_seed"])
    samples = []
    for _ in range(bootstrap_samples):
        chosen = [pairs[i] for pairs in strata.values() for i in rng.integers(0, len(pairs), len(pairs))]
        samples.append(metrics(chosen)[:2])
    ci = np.quantile(np.asarray(samples), [.025, .975], axis=0)
    cost_passed = bool(ci[1, 0] < 1)
    noninferiority_passed = bool(ci[0, 1] >= -plan["on_time_noninferiority_margin"])
    return {"complete": True, "h2_confirmed": bool(quality_passed and service_passed and cost_passed and noninferiority_passed),
        "blocks": len(blocks), "blocks_per_scenario": {k: len(v) for k, v in strata.items()},
        "quality_passed": quality_passed, "service_passed": service_passed,
        "cost_passed": cost_passed, "noninferiority_passed": noninferiority_passed,
        "conservative_cost_per_correct_ratio": ratio, "cost_ratio_ci95": ci[:, 0].tolist(),
        "on_time_rate_difference": delta, "on_time_difference_ci95": ci[:, 1].tolist(),
        "totals": totals, "per_scenario": per_scenario, "bootstrap_samples": bootstrap_samples,
        "cost_basis": "Observed VM+SSD creation-to-deletion allocation estimate; not per-trial provider Billing.",
        "interval_rule": "Work upper cost bound divided by count lower cost bound; resample paired blocks within scenario.",
        "limitations": ["Small block counts do not establish rare-failure probabilities or production latency tails.",
            "Inference is conditional on the frozen synthetic workloads, CPU setup and tested provider window.",
            "A degenerate on-time bootstrap interval does not prove zero probability of future deadline violations."]}
