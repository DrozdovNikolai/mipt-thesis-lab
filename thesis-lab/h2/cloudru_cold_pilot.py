"""Explicit continuation after the archived v1 zero-template failure."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

from h2.cloud_pilot import enough_time
from h2.cloudru_ops import Cloud, save, stamp
from h2.cloudru_trial import Trial


def run(cloud):
    out = cloud.run / "pilot-v2"
    out.mkdir(exist_ok=False)
    references = json.loads((cloud.run / "pilot/references.json").read_text())
    fit = json.loads((cloud.run / "pilot/stage-calibration.json").read_text())
    cfg = {"variant": "count", "max_workers": 3, "fixed_workers": 1, "target_queue": 1,
           "cold_start_seconds": 600, "safety_factor": 1.2, "costs": fit["costs"]}
    sources = [Path(x) for x in ("h2/cloudru_cold_pilot.py", "h2/cloudru_trial.py", "h2/cloud_trial.py",
        "h2/cloudru_manifests.py", "h2/manifests.py", "h2/cloudru_observer.py", "h2/cloudru_ops.py",
        "h2/capacity.py", "h2/coordinator.py", "h2/cloud_costs.py",
        "worktrees/h2-autoscaling/firefly-backend/app/modules/speech/workload_scaling.py")]
    directory = out / "source"
    for path in sources:
        target = directory / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    save(out / "plan.json", {"at": stamp(), "pilot_only": True, "image": cloud.state["published_image"],
        "config": cfg, "cold_probes": 3, "deadline_seconds": 600, "completion_timeout_seconds": 900,
        "first_probe_automatic_zero_timeout_seconds": 1500,
        "prior_failed_probe": "trials/pilot-cold-0/failure.json", "prior_failure_excluded_from_calibration_not_from_report": True,
        "sources_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "changes": ["Exclude fixed system node pool; audit actual worker node ownership.",
                    "Observe pending worker age through namespace-scoped read-only Kubernetes RBAC.",
                    "Cap requested workers by useful indivisible task concurrency."],
        "reference_policy": "Existing cloud references and pilot-only stage calibration retained; ASR layers unchanged.",
        "cold_calibration": "ceil(1.2 * max(start latency of these three successful probes)); main matrix remains unfrozen"})
    cold = []
    trial = None
    try:
        for index in range(3):
            enough_time(cloud, 2400 if index == 0 else 1200)
            trial = Trial(cloud, "pilot-cold-v2-" + str(index), cfg)
            trial.setup()
            permissions = {}
            for verb, resource in (("list", "pods"), ("get", "secrets"), ("delete", "pods")):
                # A denied kubectl can-i returns status 1; use authorization API
                # for an auditable read-only check of all three permissions.
                request = {"apiVersion": "authorization.k8s.io/v1", "kind": "SubjectAccessReview", "spec": {
                    "user": "system:serviceaccount:" + trial.ns + ":h2-capacity-reader",
                    "resourceAttributes": {"namespace": trial.ns, "verb": verb, "resource": resource}}}
                result = json.loads(cloud.kube("create", "-f", "-", "-o", "json", data=request))
                permissions[verb + " " + resource] = result["status"]["allowed"]
            if permissions != {"list pods": True, "get secrets": False, "delete pods": False}:
                raise ValueError("Unexpected coordinator RBAC permissions")
            metrics = trial.api("/metrics")
            if not metrics["capacity_observation"]["fresh"]:
                raise ValueError("In-cluster capacity observation is unavailable")
            save(trial.output / "capacity-reader-preflight.json", {"at": stamp(), "permissions": permissions,
                "capacity_observation": metrics["capacity_observation"]})
            trial.admit("pilot-180", expected_sha=references["pilot-180"]["sha256"], deadline_seconds=600)
            snapshot = trial.wait_completed(1, timeout=900)
            task = snapshot["tasks"][0]
            if task["expected_sha"] != task["result_sha"] or task["attempts"] != 1:
                raise ValueError("Cold ASR output or attempts differ from the reference requirement")
            trial.backup()
            observation = {"trial": trial.id, "start_latency_seconds": task["first_started_at"] - task["accepted_at"],
                "processing_seconds": task["completed_at"] - task["accepted_at"],
                "on_time": task["completed_at"] <= task["deadline_at"], "parity": True,
                "automatic_zero_observed": False, "image": cloud.state["published_image"]}
            save(trial.output / "completion.json", {"at": stamp(), **observation})
            print(json.dumps({"phase": "cold-completed", **observation}), flush=True)
            if index == 0:
                end = time.monotonic() + 1500
                while time.monotonic() < end:
                    if getattr(trial, "fatal_observation_error", None):
                        raise ValueError(trial.fatal_observation_error)
                    point = trial.last_point
                    if (point and point["at"] > task["completed_at"] and not point["instances"]
                            and not point["disks"] and not point["pods"] and point["desired_pods"] == 0):
                        observation.update(automatic_zero_observed=True, automatic_zero_at=point["at"],
                            idle_tail_seconds=point["at"] - task["completed_at"])
                        break
                    time.sleep(5)
                if not observation["automatic_zero_observed"]:
                    raise TimeoutError("Automatic VM/disk scale-to-zero not observed in 25 minutes")
            cold.append(observation)
            save(out / "cold-starts.json", cold)
            trial.retire()
            print(json.dumps({"phase": "cold-retired", **observation}), flush=True)
            trial = None
        config = {**cfg, "variant": "work", "cold_start_seconds": math.ceil(1.2 * max(x["start_latency_seconds"] for x in cold))}
        save(out / "calibrated-controller.json", config)
        save(out / "summary.json", {"at": stamp(), "pilot_only": True, "cold_probes": len(cold),
            "automatic_zero_observed": cold[0]["automatic_zero_observed"],
            "previous_failed_cold_probes": 1, "next": "Tune queue-count baseline independently, then freeze main matrix."})
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
