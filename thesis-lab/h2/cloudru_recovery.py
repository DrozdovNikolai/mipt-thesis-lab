"""One explicitly recorded replacement series after an instrument failure.

The sealed incomplete series remains incomplete. It is never resumed, merged
with new primary rows, or used to tune the controller after seeing outcomes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from h2.cloudru_autopilot import observed_phase, phase, process_is, promote_dashboard, update_index
from h2.cloud_budget import policy as budget_policy
from h2.cloudru_finish import billing
from h2.cloudru_monitoring import create_dashboard
from h2.cloudru_ops import Cloud, save, stamp
from h2.cloudru_trial import Trial

INDEX = Path("H2_CLOUDRU_RECOVERY_20261015.md")


def prepare(cloud, source):
    source = Path(source).resolve()
    sealed = json.loads((source / "sealed.json").read_text())
    manifest = source / "SHA256SUMS"
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != sealed["sha256_manifest"]:
        raise ValueError("Source archive seal differs")
    for line in manifest.read_text().splitlines():
        expected, name = line.split("  ", 1)
        path = source / name
        if not path.resolve().is_relative_to(source):
            raise ValueError("Source manifest points outside its archive")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("Sealed source file changed: " + name)
    cleanup = json.loads((source / "cleanup-inventory-verified.json").read_text())
    old = json.loads((source / "state.json").read_text())
    prior_plan = json.loads((source / "main/plan.json").read_text())
    tuning = json.loads((source / "tuning/summary.json").read_text())
    if not cleanup["complete"] or not tuning["passed"]:
        raise ValueError("Reconcile the prior cleanup and independent calibration first")
    if old["project_id"] != cloud.state["project_id"]:
        raise ValueError("Recovery project differs")
    if prior_plan["config"] != tuning["selected"]["config"] or prior_plan["slo_seconds"] != tuning["selected"]["slo_seconds"]:
        raise ValueError("Keep the original pre-main policy and SLO")
    identity = json.loads((source / "pending-v2-published.json").read_text())
    cloud.plan.update(source_image=identity["local_image"], calibration_run=str(source),
        prior_incomplete_series=str(source), pilot_only=False,
        recovery_note="One full new matrix after local wall-clock instrument failure; no original primary rows reused.")
    cloud.state["budget_started_at"] = old.get("budget_started_at", old["created_at"])
    cloud.record()
    save(cloud.run / "plan.json", cloud.plan)
    save(cloud.run / "recovery.json", {"at": stamp(), "source_run": str(source), "source_seal": sealed,
        "original_main_plan_sha256": json.loads((source / "main/frozen.json").read_text())["plan_sha256"],
        "source_image_id": identity["local_image"], "original_primary_rows_reused": 0,
        "unchanged": ["ASR image contents", "model and input files", "policy parameters", "count threshold 12",
                      "SLO 900 seconds", "12 paired blocks", "seed and order", "decision rule"],
        "changed": ["Coordinator UTC brackets inventory observations", "Observation horizon uses admission clock",
                    "Cost bounds include the inventory request interval"],
        "budget_policy": budget_policy(cloud), "automatic_further_restarts": False})
    # Freeze creates main/ only after validation. Keep this budget check outside it.
    before = billing(cloud, "before-recovery")
    reserve = cloud.plan["estimated_six_hour_total_before_variable_usage"] / 6 * 2 + 50
    ceiling = budget_policy(cloud)["spending_ceiling_rub"]
    if ceiling is not None and before["preliminary_rub_before_grant"] + reserve >= ceiling:
        raise RuntimeError("Recovery cannot fit the existing admission budget reserve")
    return before


def validate(cloud):
    (cloud.run / "recheck").mkdir(exist_ok=False)
    source = Path(cloud.plan["calibration_run"])
    tuning = json.loads((source / "tuning/summary.json").read_text())
    refs = json.loads((source / "pilot/references.json").read_text())
    trial = Trial(cloud, "pilot-clock-recheck", {**tuning["selected"]["config"],
                  "variant": "fixed", "fixed_workers": 1}, phase="recheck")
    try:
        trial.setup(fixed_nodes=1)
        cloud.kube("-n", trial.ns, "wait", "deployment/worker", "--for=jsonpath={.status.readyReplicas}=1",
                   "--timeout=600s", timeout=610)
        for fixture in sorted(refs):
            trial.admit(fixture, expected_sha=refs[fixture]["sha256"], deadline_seconds=900)
        snapshot = trial.wait_completed(len(refs), timeout=600)
        if any(t["result_sha"] != t["expected_sha"] for t in snapshot["tasks"]):
            raise ValueError("Existing cloud references do not match the replacement environment")
        trial.retire()
        points = [json.loads(line) for line in (trial.output / "timeline.jsonl").read_text().splitlines()]
        if not points or any(p.get("clock", {}).get("basis") != "coordinator_utc" for p in points):
            raise ValueError("Remote measurement clock was not observed")
        save(cloud.run / "recheck/summary.json", {"at": stamp(), "passed": True, "correct": len(refs),
             "clock_samples": len(points), "new_calibration": False,
             "note": "Readiness/parity check only; stage estimates, SLO and baseline remain frozen from the first pilot."})
    except BaseException:
        save(cloud.run / "recheck/failure.json", {"at": stamp(), "passed": False})
        if trial.submitted:
            try:
                trial.backup()
            except Exception as error:
                save(trial.output / "backup-error.json", {"error": str(error)})
        trial.close()
        raise


def run(path, source):
    run_dir = Path(path).resolve()
    save(run_dir / "autopilot-status.json", {"at": stamp(), "status": "running", "pid": os.getpid(), "kind": "instrument-recovery"})
    error = None
    try:
        cloud = Cloud(run_dir)
        prepare(cloud, source)
        phase(run_dir, "h2.cloudru_ops", "provision")
        phase(run_dir, "h2.cloudru_setup")
        phase(run_dir, "h2.cloudru_system")
        observed_phase(run_dir, "recheck", "h2.cloudru_recovery", "validate")
        phase(run_dir, "h2.cloudru_main", "freeze")
        phase(run_dir, "h2.cloudru_main", "open-window")
        plan_md = run_dir / "main/PLAN.md"
        with plan_md.open("a") as stream:
            stream.write("\n## Повтор после сбоя измерительного инструмента\n\n"
                "Первая серия 14–15 октября сохранена отдельно и остаётся неполной; её основные данные не входят в эту выборку. "
                "Исправлены только источник времени наблюдений и границы их стоимости. Облачные эталоны, калибровка, "
                "порог count, SLO, модель, политика и порядок прогонов перенесены без настройки по первым основным результатам. "
                "Время опроса ограничено двумя отметками UTC координатора; локальные часы сохраняются только для диагностики. "
                "Все расходы предыдущей попытки включены в общий плановый бюджет 500 ₽.\n")
        try:
            cloud = Cloud(run_dir)
            create_dashboard(cloud)
            promote_dashboard(cloud, "Firefly H2 · повтор Cloud.ru · 15–16.10.2026")
        except Exception as optional_error:
            save(run_dir / "dashboard-error.json", {"at": stamp(), "error": str(optional_error)})
        observed_phase(run_dir, "main", "h2.cloudru_main", "run")
    except Exception as exc:
        error = str(exc)
        save(run_dir / "autopilot-failure.json", {"at": stamp(), "error": error})
    try:
        cloud = Cloud(run_dir)
        if cloud.state.get("cluster"):
            phase(run_dir, "h2.cloudru_finish", "finish")
            phase(run_dir, "h2.cloudru_report")
            if (run_dir / "main/rows.json").exists():
                phase(run_dir, "h2.cloudru_main_report")
        else:
            cloud.cleanup()
    except Exception as exc:
        error = (error + "; " if error else "") + str(exc)
        save(run_dir / "autopilot-cleanup-or-report-failure.json", {"at": stamp(), "error": error})
        try:
            Cloud(run_dir).stop()
        except Exception:
            pass
    status = {"at": stamp(), "status": "failed_with_evidence" if error else "completed", "error": error, "pid": os.getpid()}
    save(run_dir / "autopilot-status.json", status)
    update_index(run_dir, status, INDEX)
    clean = run_dir / "cleanup-inventory-verified.json"
    if clean.exists() and json.loads(clean.read_text())["complete"]:
        watchdog = json.loads((run_dir / "watchdog.json").read_text())["pid"]
        end = time.monotonic() + 60
        while process_is(watchdog, "h2.cloudru_ops") and time.monotonic() < end:
            time.sleep(5)
        print(json.dumps({"at": stamp(), "sealing": True, "status": status["status"]}), flush=True)
        subprocess.run([sys.executable, "-m", "h2.cloudru_finish", "seal", str(run_dir)], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run", "validate"])
    parser.add_argument("run", type=Path)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    if args.action == "run":
        if not args.source:
            parser.error("run requires --source")
        run(args.run, args.source)
    else:
        validate(Cloud(args.run))
