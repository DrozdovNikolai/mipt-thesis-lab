"""Pilot-only replay for choosing a queue-count threshold, never cloud evidence.

The closed batches have no new arrivals after admission. Their count policy
cannot exceed its initial ceil(queue/target), and the shared in-flight floor
keeps busy workers. A simple FIFO replay therefore screens thresholds before
the mandatory real cold-start validation. Startup skew, HPA delays, contention
and provider billing are not simulated and must be measured separately.
"""
import argparse
import hashlib
import heapq
import json
import math
from pathlib import Path
import random

from h2.cloudru_ops import save, stamp


def workloads(seed=20261005, *, group="pilot"):
    mixed = [30, 180, 900] * 8
    random.Random(seed).shuffle(mixed)
    return {"short": [group + "-30"] * 24, "long": [group + "-900"] * 24,
            "mixed": [group + "-" + str(x) for x in mixed]}


def replay(fixtures, *, runtime_by_fixture, cold_seconds, target_queue, idle_tail_seconds):
    if not fixtures or cold_seconds < 0 or idle_tail_seconds < 0 or target_queue <= 0:
        raise ValueError("Invalid bounded replay inputs")
    workers = min(3, math.ceil(len(fixtures) / target_queue))
    available = [(cold_seconds, i) for i in range(workers)]
    finishes = []
    for fixture in fixtures:
        at, worker = heapq.heappop(available)
        duration = runtime_by_fixture[fixture]
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Invalid pilot runtime")
        finish = at + duration
        heapq.heappush(available, (finish, worker))
        finishes.append(finish)
    return {"workers": workers, "processing_seconds": finishes,
            "proxy_node_seconds": sum(at + idle_tail_seconds for at, _ in available),
            "basis": "replay_proxy_not_observed_resource_time_or_billing"}


def prepare(run):
    run = Path(run)
    out = run / "tuning"
    out.mkdir(exist_ok=False)
    cold = json.loads((run / "pilot-v2/cold-starts.json").read_text())
    cfg = json.loads((run / "pilot-v2/calibrated-controller.json").read_text())
    fit = json.loads((run / "pilot/stage-calibration.json").read_text())
    if len(cold) != 3 or not cold[0]["automatic_zero_observed"]:
        raise ValueError("Complete all three cold probes and automatic zero before tuning")
    samples = {"pilot-" + str(d): [x["preprocess"] + x["asr"] for x in fit["samples"] if x["audio_seconds"] == d]
               for d in (30, 180, 900)}
    if any(len(rows) != 2 for rows in samples.values()):
        raise ValueError("Expected the two independent pilot passes, without main timings")
    # Original 600s was a draft. Freeze the smallest five-minute target >=600s
    # supported by calibrated startup plus measured worst 24-long/3-worker work.
    # This rule does not inspect candidate-vs-baseline savings or main outcomes.
    feasible_bound = cfg["cold_start_seconds"] + 8 * max(samples["pilot-900"])
    slo = max(600, math.ceil(feasible_bound / 300) * 300)
    candidate_rows = []
    for threshold in (4, 8, 12, 24):
        cases = []
        for case_name, fixtures in workloads().items():
            for cold_index, probe in enumerate(cold):
                for pass_index in range(2):
                    result = replay(fixtures, runtime_by_fixture={k: v[pass_index] for k, v in samples.items()},
                        cold_seconds=probe["start_latency_seconds"], target_queue=threshold,
                        idle_tail_seconds=cold[0]["idle_tail_seconds"])
                    cases.append({"scenario": case_name, "cold_probe": cold_index, "pilot_pass": pass_index,
                        **result, "on_time_rate": sum(t <= slo for t in result["processing_seconds"]) / len(fixtures)})
        candidate_rows.append({"target_queue": threshold, "cases": cases,
            "eligible": all(x["on_time_rate"] >= .95 for x in cases),
            "mean_proxy_node_seconds": sum(x["proxy_node_seconds"] for x in cases) / len(cases)})
    eligible = [x for x in candidate_rows if x["eligible"]]
    if not eligible:
        raise ValueError("No baseline threshold meets the pilot replay requirement")
    selected = min(eligible, key=lambda x: (x["mean_proxy_node_seconds"], -x["target_queue"]))
    source = Path(__file__)
    save(out / "replay.json", {"at": stamp(), "pilot_only": True, "not_measured_cloud_performance": True,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "inputs": {"cold": cold, "runtime_samples": samples, "workloads": workloads()},
        "slo_seconds": slo, "slo_rule": "max(600, ceil((calibrated_cold + 8 * max_observed_pilot_900_runtime) / 300) * 300)",
        "feasibility_bound_seconds": feasible_bound, "required_on_time_rate": .95,
        "selection": "Minimum mean replay node-seconds among thresholds meeting 95% in every pilot case; tie: larger threshold.",
        "selected_target_queue": selected["target_queue"], "candidates": candidate_rows,
        "limitations": ["Three cold starts and two runtime passes are calibration samples, not a latency distribution.",
            "No contention, image-download concurrency, scheduling jitter or HPA timing is simulated.",
            "Proxy node-seconds include pre-VM waiting and are not measured cost.",
            "Real 24-long-job cold validation is mandatory before any main workload.",
            "Main fixture processing times and candidate savings are not tuning inputs."]})
    (out / "cloud_tuning.py").write_bytes(source.read_bytes())
    # Replay screens feasibility; excess cloud VMs require actual cost tuning.
    representatives = {}
    for candidate in eligible:
        concurrency = min(3, math.ceil(24 / candidate["target_queue"]))
        representatives[concurrency] = max(representatives.get(concurrency, 0), candidate["target_queue"])
    return {"slo_seconds": slo, "target_queue": selected["target_queue"], "config": {**cfg,
        "target_queue": selected["target_queue"]}, "requires_cloud_validation": True,
        "actual_cloud_thresholds": sorted(representatives.values()),
        "final_selection": "Actual resource-time upper cost among thresholds meeting 95% on-time and exact parity in all three pilot scenarios."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    print(json.dumps(prepare(parser.parse_args().run)))
