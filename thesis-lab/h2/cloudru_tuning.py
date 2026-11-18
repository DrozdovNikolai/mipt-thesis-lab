"""Choose the count baseline using real pilot VM/disk costs and deadlines."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import time

from h2.cloud_costs import task_summary
from h2.cloud_pilot import enough_time
from h2.cloud_tuning import prepare, workloads
from h2.cloudru_ops import Cloud, save, stamp
from h2.cloudru_trial import Trial


def select_actual(results, thresholds):
    rankings = []
    for threshold in thresholds:
        rows = [x for x in results if x["target_queue"] == threshold]
        complete = len(rows) == 3 and {x["scenario"] for x in rows} == set(workloads())
        passed = complete and all(x["correct"] == x["accepted"] == 24 and x["on_time_rate"] >= .95
                                  and x["lifecycle_complete"] for x in rows)
        rankings.append({"target_queue": threshold, "complete": complete, "eligible": passed,
                         "cost_upper_rub": sum(x["cost_upper_rub"] for x in rows)})
    eligible = [x for x in rankings if x["eligible"]]
    chosen = min(eligible, key=lambda x: (x["cost_upper_rub"], -x["target_queue"])) if eligible else None
    return chosen, rankings


def run(cloud):
    selected = prepare(cloud.run)
    out = cloud.run / "tuning"
    refs = json.loads((cloud.run / "pilot/references.json").read_text())
    phases = [(threshold, scenario) for threshold in selected["actual_cloud_thresholds"] for scenario in workloads()]
    random.Random(20261005).shuffle(phases)
    sources = ("h2/cloudru_tuning.py", "h2/cloudru_trial.py", "h2/cloud_trial.py", "h2/cloudru_manifests.py")
    for name in sources:
        (out / Path(name).name).write_bytes(Path(name).read_bytes())
    save(out / "validation-plan.json", {"at": stamp(), "pilot_only": True, **selected,
        "image": cloud.state["published_image"], "phases": phases, "workloads": workloads(),
        "required_on_time_rate": .95, "required_result_parity_rate": 1,
        "sources_sha256": {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in sources},
        "observation_horizon_seconds": 1800, "randomization_seed": 20261005,
        "cost_use": "Actual VM+SSD creation-to-deletion estimate, including excess nodes and the common 30-minute horizon.",
        "screening_note": "Retain the largest eligible threshold per initial concurrency (4 and 8 initially request three). Bounded tuning search, not global optimality.",
        "change_reason": "The first corrected cold probe created two VMs for one pod; nominal worker-count costs are insufficient."})
    results = []
    trial = None
    try:
        for threshold, scenario in phases:
            enough_time(cloud, 2100)
            trial_id = f"pilot-tune-q{threshold}-{scenario}"
            cfg = {**selected["config"], "variant": "count", "target_queue": threshold}
            trial = Trial(cloud, trial_id, cfg, phase="tuning")
            trial.setup()
            if not trial.api("/metrics")["capacity_observation"]["fresh"]:
                raise ValueError("Capacity reader unavailable before tuning admission")
            for fixture in workloads()[scenario]:
                trial.admit(fixture, expected_sha=refs[fixture]["sha256"], deadline_seconds=selected["slo_seconds"])
            end = min(x["accepted_at"] for x in trial.submitted) + 1800
            while (horizon_remaining := trial.seconds_until(end)) > 0:
                if getattr(trial, "fatal_observation_error", None):
                    raise ValueError(trial.fatal_observation_error)
                if trial.forward.poll() is not None:
                    raise RuntimeError("Lost coordinator connection during baseline tuning")
                time.sleep(min(2, horizon_remaining))
            snapshot = trial.api("/snapshot")
            save(trial.output / "horizon-snapshot.json", snapshot)
            summary = task_summary(snapshot)
            trial.retire()
            cost = json.loads((trial.output / "cost-summary.json").read_text())
            row = {"at": stamp(), "trial": trial_id, "variant": "count", "scenario": scenario,
                   "target_queue": threshold, **summary, "lifecycle_complete": cost["lifecycle_complete"],
                   "cost_lower_rub": cost["estimated_rub_lower"], "cost_upper_rub": cost["estimated_rub_upper"]}
            results.append(row)
            save(out / "validations.json", results)
            trial = None
            print(json.dumps({"phase": "count-pilot-retired", **row}), flush=True)
        chosen, rankings = select_actual(results, selected["actual_cloud_thresholds"])
        if chosen:
            selected.update(target_queue=chosen["target_queue"], requires_cloud_validation=False)
            selected["config"]["target_queue"] = chosen["target_queue"]
        save(out / "summary.json", {"at": stamp(), "pilot_only": True, "passed": chosen is not None,
            "selected": selected, "rankings": rankings, "results": results,
            "next": "Freeze main matrix if a complete baseline candidate meets the predeclared criteria."})
    except BaseException as error:
        failure = {"at": stamp(), "trial": trial.id if trial else None, "error": str(error), "pilot_only": True}
        save(out / "failure.json", failure)
        if trial:
            save(trial.output / "failure.json", failure)
            try:
                trial.backup()
            except Exception as backup_error:
                save(trial.output / "backup-error.json", {"error": str(backup_error)})
            trial.close()
        cloud.stop()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    run(Cloud(parser.parse_args().run))
