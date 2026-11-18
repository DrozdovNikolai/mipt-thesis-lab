"""Detached bounded continuation: calibrate, compare, report and clean up."""
import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from h2.cloudru_finish import billing
from h2.cloudru_monitoring import dashboard_request
from h2.cloudru_ops import Cloud, save, stamp
from h2.cloudru_window import change_window


def process_is(pid, module):
    try:
        return module.encode() in Path("/proc", str(pid), "cmdline").read_bytes().split(b"\0")
    except FileNotFoundError:
        return False


def phase(run, module, *arguments):
    print(json.dumps({"at": stamp(), "phase_started": module, "arguments": list(arguments)}), flush=True)
    subprocess.run([sys.executable, "-u", "-m", module, *map(str, arguments), str(run)], check=True)
    print(json.dumps({"at": stamp(), "phase_finished": module}), flush=True)


def observed_phase(run, phase_name, module, *arguments):
    with (run / (phase_name + "-observer.log")).open("w") as log:
        observer = subprocess.Popen([sys.executable, "-u", "-m", "h2.cloudru_observer", str(run), "--phase", phase_name],
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        save(run / (phase_name + "-observer-process.json"), {"at": stamp(), "pid": observer.pid, "read_only": True})
        try:
            phase(run, module, *arguments)
        finally:
            try:
                observer.wait(timeout=60)
            except subprocess.TimeoutExpired:
                observer.terminate()
                observer.wait(timeout=30)


def promote_dashboard(cloud, title="Firefly H2 · Cloud.ru · эксперимент 14–15.10.2026"):
    identity = json.loads((cloud.run / "dashboard-created.json").read_text())
    path = "/api/monaas-dashboards/v1/projects/" + cloud.client.project_id + "/dashboards/" + identity["dashboardId"]
    body = dashboard_request(cloud.state["cluster"]["id"])
    body["title"] = title
    body["description"] = "Нативные метрики пилотных и основных прогонов; стоимость ВМ/SSD и Billing учитываются отдельно."
    body["panels"][0]["title"] = "Firefly H2 · основная облачная серия"
    body["panels"][0]["properties"]["content"] = (
        "CPU ASR, KEDA и 0–3 рабочих узла. Пилотные и основные прогоны различаются namespace. "
        "Количество pod не равно количеству оплачиваемых ВМ. Экономический вывод определяется "
        "полной парной серией, соблюдением SLO и отдельным учётом VM/SSD; Billing сверяет весь кластер.")
    for panel in body["panels"]:
        for query in panel.get("properties", {}).get("queries", []):
            query["query"] = query["query"].replace('namespace=~"ff-h2-pilot-.*"', 'namespace=~"ff-h2-(pilot|main)-.*"')
    out = cloud.run / "dashboard-revisions"
    save(out / "v3-request.json", body)
    cloud.mutate("monitoring", path, body=body, label="native-dashboard-main-series")
    actual = cloud.client.request("monitoring", path)
    if actual["title"] != body["title"] or len(actual["panels"]) != len(body["panels"]):
        raise ValueError("Main dashboard readback differs")
    save(out / "v3-readback.json", actual)


def update_index(run, status, index=Path("H2_CLOUDRU_PILOT_20261014.md")):
    body = index.read_text()
    heading = "## Завершение автоматической серии"
    if heading in body:
        body = body.split(heading)[0]
    summary = run / "main/analysis.json"
    analysis = json.loads(summary.read_text()) if summary.exists() else {}
    result = ("Основная серия полная; H2 подтверждена по её критериям." if analysis.get("h2_confirmed")
              else "Основная серия полная; H2 не подтверждена по её критериям." if analysis.get("complete")
              else "Основная серия неполная; подтверждение H2 не заявляется.")
    body = "\n".join(("Статус после автоматического завершения: **" + result + "**")
                     if line.startswith("Статус на ") else line for line in body.split("\n"))
    final_bill = run / "billing-after-cleanup.json"
    charge = json.loads(final_bill.read_text())["preliminary_rub_before_grant"] if final_bill.exists() else None
    links = "[Результаты основной серии](results/" + run.name + "/main/RESULTS.md)." if (run / "main/RESULTS.md").exists() else ""
    body += f"\n{heading}\n\nОбновлено {stamp()}. {result} {links}\n\n"
    body += "Состояние процесса: `" + status["status"] + "`. "
    clean = run / "cleanup-inventory-verified.json"
    if clean.exists() and json.loads(clean.read_text())["complete"]:
        body += "Вычислительные ресурсы запуска удалены; отсутствие принадлежащих ему ВМ и SSD проверено. "
        body += "Дашборд сохранён.\n\n" if json.loads(clean.read_text())["dashboard_retained"] else "Дашборд этого запуска не создавался.\n\n"
    if charge is not None:
        body += f"Последняя предварительная сумма Billing до применения гранта: **{charge:.2f} ₽**. Это ещё не окончательный счёт.\n"
    index.write_text(body)


def run(path, cold_pid):
    run_dir = Path(path).resolve()
    while process_is(cold_pid, "h2.cloudru_cold_pilot"):
        time.sleep(10)
    status = {"at": stamp(), "status": "running", "pid": os.getpid()}
    save(run_dir / "autopilot-status.json", status)
    error = None
    try:
        cold = json.loads((run_dir / "pilot-v2/summary.json").read_text())
        if cold["cold_probes"] != 3 or not cold["automatic_zero_observed"]:
            raise ValueError("Cold calibration did not complete")
        cloud = Cloud(run_dir)
        before = billing(cloud, "before-tuning")
        if before["preliminary_rub_before_grant"] + 150 >= 500:
            raise RuntimeError("Insufficient budget reserve for baseline tuning")
        save(run_dir / "tuning-window-plan.json", {"at": stamp(), "purpose": "Independent count threshold tuning",
            "maximum_trials": 6, "horizon_seconds_each": 1800, "maximum_hours": 4, "total_budget_rub": 500,
            "native_preliminary_before_phase": before["preliminary_rub_before_grant"]})
        change_window(cloud, deadline=(datetime.now(UTC) + timedelta(hours=4)).isoformat(), phase="tuning")
        observed_phase(run_dir, "tuning", "h2.cloudru_tuning")
        tuning = json.loads((run_dir / "tuning/summary.json").read_text())
        if not tuning["passed"]:
            raise RuntimeError("No baseline candidate met the frozen pilot requirements")
        phase(run_dir, "h2.cloudru_main", "freeze")
        phase(run_dir, "h2.cloudru_main", "open-window")
        try:
            promote_dashboard(Cloud(run_dir))
        except Exception as dashboard_error:
            save(run_dir / "dashboard-main-update-error.json", {"at": stamp(), "error": str(dashboard_error)})
        observed_phase(run_dir, "main", "h2.cloudru_main", "run")
    except Exception as exc:
        error = str(exc)
        save(run_dir / "autopilot-failure.json", {"at": stamp(), "error": error})
    try:
        phase(run_dir, "h2.cloudru_finish", "finish")
        phase(run_dir, "h2.cloudru_report")
        if (run_dir / "main/rows.json").exists():
            phase(run_dir, "h2.cloudru_main_report")
    except Exception as exc:
        error = (error + "; " if error else "") + str(exc)
        save(run_dir / "autopilot-cleanup-or-report-failure.json", {"at": stamp(), "error": error})
        # Stop compute if evidence auditing or cleanup failed; the original
        # watchdog remains available to reconcile owned deletions at deadline.
        try:
            Cloud(run_dir).stop()
        except Exception:
            pass
    status = {"at": stamp(), "status": "failed_with_evidence" if error else "completed",
              "error": error, "pid": os.getpid()}
    save(run_dir / "autopilot-status.json", status)
    update_index(run_dir, status)
    # No writes after sealing, including to the captured parent log. Auxiliary
    # observers have stopped; the watchdog exits after reading successful cleanup.
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
    parser.add_argument("run", type=Path)
    parser.add_argument("--cold-pid", type=int, required=True)
    args = parser.parse_args()
    run(args.run, args.cold_pid)
