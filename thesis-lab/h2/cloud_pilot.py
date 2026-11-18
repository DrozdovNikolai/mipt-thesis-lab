"""Cloud calibration before H2's confirmatory matrix is frozen.

Runs real Firefly ASR, repeatability checks, cold-start probes and one observed
automatic node retirement. These measurements are pilot data, not H2 confirmation.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import time

from h2.cloud_ops import Cloud, save, stamp
from h2.cloud_trial import Trial


def calibration(snapshot):
    events = snapshot["events"]
    rows = []
    for task in snapshot["tasks"]:
        payload = json.loads(task["payload"])
        if not payload["fixture"].startswith("pilot-") or task["state"] != "done" or task["attempts"] != 1:
            continue
        claimed = [e for e in events if e["task"] == task["id"] and e["kind"] == "claimed"]
        stage = [e for e in events if e["task"] == task["id"] and e["kind"] == "stage"]
        if len(claimed) != 1 or len(stage) != 1:
            raise ValueError("Ambiguous stage timing in pilot")
        rows.append({"task": task["id"], "audio_seconds": payload["audio_seconds"],
            "preprocess": stage[0]["at"] - claimed[0]["at"],
            "asr": task["completed_at"] - stage[0]["at"]})
    if len(rows) < 6 or {x["audio_seconds"] for x in rows} != {30, 180, 900}:
        raise ValueError("Insufficient pilot-only samples for stage calibration")
    # An upper envelope of measured elapsed stage durations. No ML model is trained.
    # Keeping the floor small avoids an intercept equal to the shortest whole task.
    costs = {}
    for stage in ("preprocess", "asr"):
        fixed = min(x[stage] for x in rows) * 0.5
        slope = max((x[stage] - fixed) / x["audio_seconds"] for x in rows)
        costs[stage] = {"fixed_seconds": fixed, "seconds_per_audio_second": slope}
    return {"costs": costs, "samples": rows, "method": "upper envelope of pilot elapsed stage times",
            "excluded": "main fixture timings; reference generation is not confirmatory performance data"}


def enough_time(cloud, seconds):
    from datetime import datetime, UTC
    remaining = (datetime.fromisoformat(cloud.state["deadline"]) - datetime.now(UTC)).total_seconds()
    if remaining < seconds + 300:
        raise RuntimeError("Insufficient guarded time for another pilot phase")


def run(cloud, *, trial_class=Trial, capacity_workers=0):
    if capacity_workers not in (0, 3):
        raise ValueError("The optional capacity probe uses exactly three workers")
    if not cloud.state.get("setup_at"):
        raise ValueError("Provision and install the immutable image, KEDA and stop guard first")
    result_dir = cloud.run / "pilot"
    result_dir.mkdir(exist_ok=False)
    cfg = {"variant": "fixed", "max_workers": 3, "fixed_workers": 1, "target_queue": 1,
           "cold_start_seconds": 180, "safety_factor": 1.2,
           "costs": {"preprocess": {"fixed_seconds": 0.2, "seconds_per_audio_second": 0.01},
                     "asr": {"fixed_seconds": 1, "seconds_per_audio_second": 0.1}}}
    enough_time(cloud, 1800)
    trial = trial_class(cloud, "pilot-reference", cfg)
    references = {}
    try:
        fixtures = trial.setup(fixed_nodes=1)
        for fixture in fixtures["fixtures"]:
            item = trial.admit(fixture)
            snap = trial.wait_completed(len(trial.submitted), timeout=600)
            task = next(t for t in snap["tasks"] if t["id"] == item["id"])
            references[fixture] = {"sha256": task["result_sha"], "result": json.loads(task["result"])}
            save(result_dir / "references.json", references)
            print(json.dumps({"phase": "reference", "fixture": fixture, "completed": len(trial.submitted)}), flush=True)
        for fixture in fixtures["fixtures"]:
            item = trial.admit(fixture, expected_sha=references[fixture]["sha256"])
            snap = trial.wait_completed(len(trial.submitted), timeout=600)
            task = next(t for t in snap["tasks"] if t["id"] == item["id"])
            if task["result_sha"] != task["expected_sha"]:
                raise ValueError("Cloud ASR repeat differs from sequential reference")
        fit = calibration(snap)
        save(result_dir / "stage-calibration.json", fit)
        trial.retire()
    except BaseException as exc:
        save(trial.output / "failure.json", {"at": stamp(), "error": str(exc)})
        try:
            trial.backup()
        except Exception as backup_error:
            save(trial.output / "backup-error.json", {"error": str(backup_error)})
        trial.close()
        raise
    if capacity_workers:
        enough_time(cloud, 2400)
        capacity_cfg = {**cfg, "fixed_workers": capacity_workers, "costs": fit["costs"]}
        trial = trial_class(cloud, "pilot-capacity", capacity_cfg)
        try:
            trial.setup(fixed_nodes=capacity_workers)
            # Warm all three workers before simultaneous admission. This phase
            # checks quota, placement and result parity, not cold-start latency.
            cloud.kube("-n", trial.ns, "wait", "deployment/worker",
                       "--for=jsonpath={.status.readyReplicas}=" + str(capacity_workers),
                       "--timeout=600s", timeout=610)
            pods = json.loads(cloud.kube("-n", trial.ns, "get", "pods", "-l", "app=worker", "-o", "json"))
            node_names = {p["spec"].get("nodeName") for p in pods["items"]}
            if len(pods["items"]) != capacity_workers or len(node_names) != capacity_workers or None in node_names:
                raise ValueError("Capacity probe did not place one worker on each of three nodes")
            save(trial.output / "capacity-ready-pods.json", pods)
            for _ in range(2 * capacity_workers):
                trial.admit("pilot-900", expected_sha=references["pilot-900"]["sha256"])
            snap = trial.wait_completed(2 * capacity_workers, timeout=1200)
            tasks = snap["tasks"]
            if any(t["result_sha"] != t["expected_sha"] or t["attempts"] != 1 for t in tasks):
                raise ValueError("Capacity probe parity or single-attempt execution failed")
            if len({t["worker"] for t in tasks}) != capacity_workers:
                raise ValueError("Capacity probe did not execute on all three workers")
            save(result_dir / "capacity.json", {"at": stamp(), "workers": capacity_workers,
                "tasks": len(tasks), "distinct_nodes": sorted(node_names), "parity": True,
                "pilot_only": True, "stage_calibration_unchanged": True})
            trial.retire()
            print(json.dumps({"phase": "capacity", "workers": capacity_workers, "tasks": len(tasks), "parity": True}), flush=True)
        except BaseException as exc:
            save(trial.output / "failure.json", {"at": stamp(), "error": str(exc)})
            try:
                trial.backup()
            except Exception as backup_error:
                save(trial.output / "backup-error.json", {"error": str(backup_error)})
            trial.close()
            raise
    cold = []
    for index in range(3):
        enough_time(cloud, 1800 if index == 0 else 900)
        cfg = {**cfg, "variant": "count", "costs": fit["costs"]}
        trial = trial_class(cloud, "pilot-cold-" + str(index), cfg)
        try:
            trial.setup()
            item = trial.admit("pilot-180", expected_sha=references["pilot-180"]["sha256"])
            snap = trial.wait_completed(1, timeout=900)
            task = snap["tasks"][0]
            if task["expected_sha"] != task["result_sha"]:
                raise ValueError("Cold ASR output differs from reference")
            observation = {"trial": trial.id, "start_latency_seconds": task["first_started_at"] - task["accepted_at"],
                "processing_seconds": task["completed_at"] - task["accepted_at"],
                "automatic_zero_observed": False}
            if index == 0:
                end = time.monotonic() + 1500
                while time.monotonic() < end:
                    point = trial.last_point
                    if (point and point["at"] > task["completed_at"] and not point["instances"]
                            and not point["disks"] and not point["pods"] and point["desired_pods"] == 0):
                        observation.update(automatic_zero_observed=True, automatic_zero_at=point["at"],
                            idle_tail_seconds=point["at"] - task["completed_at"])
                        break
                    time.sleep(5)
                if not observation["automatic_zero_observed"]:
                    raise TimeoutError("Automatic VM/disk scale-to-zero not observed in pilot")
            cold.append(observation)
            save(result_dir / "cold-starts.json", cold)
            trial.retire()
            print(json.dumps({"phase": "cold-start", **observation}), flush=True)
        except BaseException as exc:
            save(trial.output / "failure.json", {"at": stamp(), "error": str(exc)})
            try:
                trial.backup()
            except Exception as backup_error:
                save(trial.output / "backup-error.json", {"error": str(backup_error)})
            trial.close()
            raise
    config = {**cfg, "variant": "work", "cold_start_seconds": math.ceil(1.2 * max(x["start_latency_seconds"] for x in cold))}
    save(result_dir / "calibrated-controller.json", config)
    save(result_dir / "summary.json", {"at": stamp(), "references": 6, "reference_repeats": 6,
        "cold_start_probes": 3, "capacity_workers": capacity_workers,
        "automatic_node_retirement_observed": cold[0]["automatic_zero_observed"],
        "pilot_only": True, "next": "Tune queue-count baseline, then freeze the main matrix and numerical criteria."})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    cloud = Cloud(args.run)
    try:
        run(cloud)
    except BaseException:
        cloud.stop()
        raise
