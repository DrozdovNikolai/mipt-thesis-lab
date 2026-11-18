"""Reconcile one interrupted secondary control after all primary pairs finished.

No workload replay, admission into an existing queue, horizon reset, or deadline
extension. Frozen measurement code is imported unchanged. The interrupted
control stays descriptive with an explicit observation-gap flag.
"""
import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import urllib.error

from h2.cloud_analysis import analyze
from h2.cloud_costs import Ledger, Rates, task_summary, verify_resource_coverage
from h2.cloudru_autopilot import phase, process_is
from h2.cloudru_continuation import combine
from h2.cloudru_main import budget_check, check_frozen, execution_trials, inject_fault
from h2.cloudru_ops import Cloud, save, stamp
from h2.cloudru_trial import Trial


def read(path):
    return json.loads(Path(path).read_text())


def resume_scope(plan, rows, directories):
    expected = execution_trials(plan)
    primary = [x for x in expected if x["analysis_group"] == "primary"]
    if [x["trial"] for x in rows] != [x["id"] for x in primary]:
        raise ValueError("Only a completed primary suffix is eligible")
    if any(not x["valid"] or not x["lifecycle_complete"] for x in rows):
        raise ValueError("Completed primary evidence is required")
    remaining = expected[len(rows):]
    first = remaining[0]
    if first["id"] != "main-short-fixed" or first["variant"] != "fixed" or first["fault"]:
        raise ValueError("Only the recorded first fixed control can be reconciled")
    if set(directories) != {x["trial"] for x in rows} | {first["id"]}:
        raise ValueError("Unexpected admitted or prepared trial; never silently replay")
    return remaining


def replay_ledger(points, rates):
    ledger = Ledger(Rates.from_dict(rates))
    if not points:
        raise ValueError("Prior observations are required")
    for point in points:
        if point["clock"]["basis"] != "coordinator_utc":
            raise ValueError("Cannot splice local and coordinator clocks")
        ledger.observe(point["at"], observed_from=point["clock"]["inventory_started_at"],
                       instances=point["instances"], disks=point["disks"])
        if ledger.report() != point["cost"]:
            raise ValueError("Replayed accounting differs from retained observations")
    return ledger


def attach(cloud, spec, plan):
    output = cloud.run / "trials" / spec["id"]
    previous = cloud.run / "reboot-recovery" / "before-control"
    shutil.copytree(output, previous)
    cfg = read(output / "config.json")["controller"]
    if cfg != {**plan["config"], "variant": "fixed", "fixed_workers": 3}:
        raise ValueError("Interrupted control configuration changed")
    trial = Trial.__new__(Trial)
    trial.cloud, trial.id, trial.config = cloud, spec["id"], cfg
    trial.output, trial.ns = output, "ff-h2-" + spec["id"]
    trial.token = (cloud.runtime / "api-token").read_text()
    trial.port, trial.phase, trial.started = 18084, "main", None
    trial.submitted = read(output / "submitted.json")
    if len(trial.submitted) != spec["tasks"] or any("accepted_at" not in x for x in trial.submitted):
        raise ValueError("Do not resume partial or ambiguous task admission")
    points = [json.loads(line) for line in (output / "timeline.jsonl").read_text().splitlines()]
    trial.ledger = replay_ledger(points, cloud.plan["rates_rub_per_hour"])
    identities = read(output / "resource-identities.json")
    trial.known_instances, trial.known_disks = set(identities["vm_ids"]), set(identities["disk_ids"])
    trial.known_nodes = {p["node"] for point in points for p in point["pods"] if p["node"]}
    trial.last_point, trial.sample_error, trial.sample_thread = points[-1], None, None
    trial.stop_sampling, trial.observation_lock = threading.Event(), threading.Lock()
    cloud.refresh_kubeconfig()
    trial.forward_log = (output / "port-forward-after-reboot.log").open("w")
    trial.forward = subprocess.Popen(["kubectl", "--kubeconfig", str(cloud.runtime / "kubeconfig"),
        "-n", trial.ns, "port-forward", "service/coordinator", str(trial.port) + ":8080"],
        stdout=trial.forward_log, stderr=subprocess.STDOUT)
    try:
        for _ in range(30):
            try:
                trial.api("/health", timeout=2)
                break
            except (OSError, urllib.error.URLError):
                if trial.forward.poll() is not None:
                    raise RuntimeError("Restored port forward exited")
                time.sleep(1)
        else:
            raise TimeoutError("Restored coordinator access unavailable")
        snapshot = trial.api("/snapshot")
        save(output / "post-reboot-snapshot.json", snapshot)
        trial.backup()
        current = trial.observe()
        end = min(x["accepted_at"] for x in trial.submitted) + plan["observation_horizon_seconds"]
        if trial.seconds_until(end) > 0:
            raise ValueError("This reconciliation expects an already elapsed control horizon")
        note = {"at": stamp(), "trial": trial.id, "primary_analysis_affected": False,
            "last_retained_observation": points[-1]["at"], "first_recovered_observation": current["at"],
            "observation_gap_seconds": current["at"] - points[-1]["at"],
            "original_horizon_end": end, "new_admissions": 0, "workload_replayed": False,
            "all_tasks_completed_before_original_horizon": all(
                t["state"] == "done" and t["completed_at"] <= end for t in snapshot["tasks"]),
            "continuous_control_observation": False,
            "cost_note": "Includes extra idle resources while the local driver was unavailable; not a normal 1800-second fixed comparison."}
        save(output / "reboot-reconciliation.json", note)
        trial.start_sampling()
        return trial, snapshot
    except BaseException:
        trial.close()
        raise


def finish_trial(trial, spec, plan, snapshot, *, interrupted=False, faulted=False):
    summary = task_summary(snapshot)
    trial.retire()
    cost = read(trial.output / "cost-summary.json")
    verify_resource_coverage(read(trial.output / "resource-identities.json"), cost)
    return {"trial": spec["id"], "at": stamp(), "valid": not interrupted,
        "lifecycle_complete": cost["lifecycle_complete"], **summary,
        "cost_lower_rub": cost["estimated_rub_lower"], "cost_upper_rub": cost["estimated_rub_upper"],
        "fault_requested": faulted, "fault_required": spec["fault"],
        "observation_horizon_seconds": plan["observation_horizon_seconds"],
        **({"observation_interrupted": True,
            "exclusion_reason": "Computer reboot interrupted the secondary fixed-control observation and delayed retirement; preserved separately from primary inference."}
           if interrupted else {})}


def record_row(cloud, plan, rows, row):
    rows.append(row)
    save(cloud.run / "main/rows.json", rows)
    save(cloud.run / "main/analysis.json", analyze(plan, rows, bootstrap_samples=plan["bootstrap_samples"]))
    print(json.dumps({"phase": "recovered-main-trial-retired", **row}), flush=True)


def annotate_report(run):
    path = run / "main/RESULTS.md"
    if not path.exists():
        return
    text = path.read_text()
    text = text.replace("| Короткие записи | fixed |", "| Короткие записи | fixed † |")
    note = ("\n\n† Перезагрузка компьютера произошла после завершения всех основных пар, "
        "во время дополнительного short-fixed. Его 24 задачи завершились до перезагрузки; "
        "в наблюдениях есть разрыв, а затраты включают лишний простой до восстановления управления. "
        "Эта строка сохранена как прерванный контроль, не считается обычным 30-минутным "
        "контрольным прогоном и не входит в основной статистический вывод. "
        "Основные пары не повторялись и не менялись.\n")
    analysis = read(run / "main/analysis.json")
    if analysis.get("complete") and "cost_ratio_ci95" in analysis:
        lo, hi = analysis["cost_ratio_ci95"]
        note += f"\nТочные границы 95% CI отношения стоимости: [{lo:.9f}; {hi:.9f}]. Критерий верхней границы строго ниже 1 не изменялся.\n"
    path.write_text(text + note)


def plot_interrupted_control(run):
    import matplotlib.pyplot as plt
    import numpy as np
    from h2.cloudru_report import finish

    directory = run / "trials/main-short-fixed"
    note = read(directory / "reboot-reconciliation.json")
    points = [json.loads(line) for line in (directory / "timeline.jsonl").read_text().splitlines()]
    origin = min(x["accepted_at"] for x in read(directory / "submitted.json"))
    gap = [(note[k] - origin) / 60 for k in ("last_retained_observation", "first_recovered_observation")]
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True, constrained_layout=True)
    fig.suptitle("Short fixed · дополнительный контроль с прерыванием наблюдения", fontsize=14)
    for axis, field, label in zip(axes, ("instances", "completed", "cost"),
                                 ("Рабочие ВМ", "Завершённые задачи", "ВМ + SSD, расчётные ₽")):
        times, values = [], []
        for point in points:
            at = (point["at"] - origin) / 60
            if times and times[-1] <= gap[0] and at >= gap[1]:
                times.append(np.nan)
                values.append(np.nan)
            times.append(at)
            values.append(len(point["instances"]) if field == "instances" else
                          point["metrics"]["completed"] if field == "completed" else
                          point["cost"]["estimated_rub_upper"])
        axis.plot(times, values, color="#2563eb", marker=".", markersize=2)
        axis.axvspan(*gap, color="#94a3b8", alpha=.25, label="Нет локальных наблюдений")
        axis.axvline(30, color="#64748b", linestyle="--", label="Плановый конец окна")
        axis.set_ylabel(label)
        axis.set_ylim(bottom=0)
        axis.grid(alpha=.2)
    axes[0].legend()
    axes[-1].set_xlabel("Минуты после первого приёма; затраты включают задержанную очистку")
    finish(fig, run / "figures/main-short-fixed-timeline")
    save(run / "figures/main-short-fixed-recovery-source.json", {"at": stamp(),
        "sources": ["trials/main-short-fixed/timeline.jsonl", "trials/main-short-fixed/reboot-reconciliation.json"],
        "gap_not_interpolated": True, "secondary_interrupted_control": True})


def run(path):
    directory = Path(path).resolve()
    recovery = directory / "reboot-recovery"
    cloud, trial, error = Cloud(directory), None, None
    try:
        plan = check_frozen(cloud)
        if not read(recovery / "primary-audit.json")["primary_complete"]:
            raise ValueError("Verify the complete primary matrix before recovery")
        rows = read(directory / "main/rows.json")
        remaining = resume_scope(plan, rows, [p.name for p in (directory / "trials").glob("main-*")])
        if cloud.state["deadline"] != plan["deadline"]:
            raise ValueError("The original deadline must remain unchanged")
        source = Path(__file__)
        shutil.copy2(source, recovery / source.name)
        save(recovery / "plan.json", {"at": stamp(), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "primary_trials_replayed": 0, "interrupted_control": remaining[0]["id"],
            "new_trials_in_original_order": [x["id"] for x in remaining[1:]],
            "deadline": plan["deadline"], "method": "Reconcile existing tasks and full resource cost; flag interrupted control; execute only untouched original secondary suffix."})
        save(directory / "autopilot-status.json", {"at": stamp(), "status": "running_secondary_recovery",
            "pid": os.getpid(), "primary_complete": True})
        trial, snapshot = attach(cloud, remaining[0], plan)
        row = finish_trial(trial, remaining[0], plan, snapshot, interrupted=True)
        trial = None
        record_row(cloud, plan, rows, row)
        refs, optional_allowed = read(directory / "main/references.json"), None
        for spec in remaining[1:]:
            check_frozen(cloud)
            seconds_left = (datetime.fromisoformat(plan["deadline"]) - datetime.now(UTC)).total_seconds()
            if spec["analysis_group"] == "optional_fault_demonstration":
                if optional_allowed is None:
                    optional_allowed = seconds_left >= 5400
                if not optional_allowed:
                    save(directory / "main/optional-fault-skipped.json", {"at": stamp(),
                        "reason": "Less than 90 guarded minutes for the whole optional pair"})
                    continue
            if spec["analysis_group"] == "primary" or seconds_left < 2700 + (600 if spec["variant"] == "fixed" else 0):
                raise RuntimeError("Only untouched secondary trials fitting the original guarded window may start")
            budget_check(cloud, spec["id"])
            cfg = {**plan["config"], "variant": spec["variant"], "fixed_workers": 3}
            trial = Trial(cloud, spec["id"], cfg, phase="main")
            trial.setup(fixed_nodes=3 if spec["variant"] == "fixed" else None)
            if spec["variant"] == "fixed":
                cloud.kube("-n", trial.ns, "wait", "deployment/worker", "--for=jsonpath={.status.readyReplicas}=3", "--timeout=600s", timeout=610)
            if not trial.api("/metrics")["capacity_observation"]["fresh"]:
                raise ValueError("Capacity observation unavailable before admission")
            for fixture in plan["workloads"][spec["scenario"]]:
                trial.admit(fixture, expected_sha=refs[fixture]["sha256"], deadline_seconds=plan["slo_seconds"])
            end = min(x["accepted_at"] for x in trial.submitted) + plan["observation_horizon_seconds"]
            faulted = False
            while (seconds_left := trial.seconds_until(end)) > 0:
                if getattr(trial, "fatal_observation_error", None):
                    raise ValueError(trial.fatal_observation_error)
                if trial.forward.poll() is not None:
                    raise RuntimeError("Lost coordinator connection during the observation horizon")
                if spec["fault"] and not faulted:
                    faulted = inject_fault(trial)
                time.sleep(min(2, seconds_left))
            snapshot = trial.api("/snapshot")
            save(trial.output / "horizon-snapshot.json", snapshot)
            row = finish_trial(trial, spec, plan, snapshot, faulted=faulted)
            trial = None
            record_row(cloud, plan, rows, row)
        save(directory / "main/summary.json", {"at": stamp(), "completed_trials_in_session": len(rows),
            "primary_complete_combined": True, "interrupted_secondary_controls": ["main-short-fixed"],
            "cost_basis": "resource_time_estimate_not_billing"})
    except BaseException as exc:
        error = str(exc)
        save(recovery / "failure.json", {"at": stamp(), "trial": trial.id if trial else None, "error": error})
        if trial:
            try:
                trial.backup()
            except Exception as backup_error:
                save(trial.output / "backup-error.json", {"error": str(backup_error)})
            trial.close()
    try:
        phase(directory, "h2.cloudru_finish", "finish")
        phase(directory, "h2.cloudru_report")
        phase(directory, "h2.cloudru_main_report")
        combine(directory)
        annotate_report(directory)
        annotate_report(directory / "combined")
        plot_interrupted_control(directory)
    except Exception as exc:
        error = (error + "; " if error else "") + str(exc)
        save(recovery / "finalization-failure.json", {"at": stamp(), "error": str(exc)})
    status = {"at": stamp(), "status": "failed_with_evidence" if error else "completed_with_interrupted_secondary_control",
        "error": error, "primary_complete": True, "interrupted_control": "main-short-fixed"}
    save(directory / "autopilot-status.json", status)
    with Path("H2_CLOUDRU_RESTART_20261016.md").open("a") as stream:
        stream.write("\n\nЗавершение восстановления " + stamp() + ": `" + status["status"] + "`. "
            "[Объединённые результаты](results/" + directory.name + "/combined/main/RESULTS.md).\n")
    proof = directory / "cleanup-inventory-verified.json"
    if proof.exists() and read(proof)["complete"]:
        watchdog = read(directory / "watchdog.json")["pid"]
        end = time.monotonic() + 60
        while process_is(watchdog, "h2.cloudru_ops") and time.monotonic() < end:
            time.sleep(5)
        phase(directory, "h2.cloudru_finish", "seal")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    run(parser.parse_args().run)
