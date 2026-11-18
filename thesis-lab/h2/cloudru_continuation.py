"""Finish only the unstarted suffix after an inter-block Billing outage.

The sealed parent remains incomplete. A separate combined report discloses the
new cluster and observation window; it cannot claim an uninterrupted,
preregistered confirmatory series. No completed or failed trial is replayed.
"""
import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from h2.cloud_analysis import analyze
from h2.cloud_budget import policy as budget_policy
from h2.cloud_costs import task_summary, verify_resource_coverage
from h2.cloud_trial import verify_backup
from h2.cloudru_autopilot import observed_phase, phase, process_is, promote_dashboard
from h2.cloudru_finish import billing, optional_evidence
from h2.cloudru_main import SOURCES, budget_check, execution_trials
from h2.cloudru_main_report import report
from h2.cloudru_monitoring import create_dashboard
from h2.cloudru_ops import Cloud, save, stamp
from h2.cloudru_setup import refresh_access_after_resume, resume_after_guard
from h2.cloudru_pair_policy import POLICY as PAIR_POLICY, verify_pair_source, session_summary

INDEX = Path("H2_CLOUDRU_CONTINUATION_20261015.md")
ADMINISTRATIVE_CHANGES = {"h2/cloudru_main.py"}
DISCLOSURE = (
    "Серия C прервалась между полными парными блоками из-за недоступности Billing API. "
    "В продолжении выполняется только оставшаяся часть исходного порядка. Кластер и календарное окно изменены; "
    "это раскрытое отклонение от исходного протокола. Исходная серия C остаётся неполной. "
    "Объединённые результаты показывают все заранее выбранные блоки, но не выдаются за "
    "непрерывный подтверждающий эксперимент по исходному протоколу."
)


def read(path):
    return json.loads(Path(path).read_text())


def verify_archive(source):
    source = Path(source).resolve()
    seal = read(source / "sealed.json")
    manifest = source / "SHA256SUMS"
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != seal["sha256_manifest"]:
        raise ValueError("Parent archive manifest changed")
    checked = 0
    for line in manifest.read_text().splitlines():
        expected, name = line.split("  ", 1)
        path = source / name
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("Parent manifest points outside its archive")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("Parent archive changed: " + name)
        checked += 1
    if checked != seal["files"]:
        raise ValueError("Parent archive file count differs")
    return seal


def parent_evidence(source):
    source = Path(source).resolve()
    seal = verify_archive(source)
    plan = read(source / "main/plan.json")
    frozen = read(source / "main/frozen.json")
    if hashlib.sha256((source / "main/plan.json").read_bytes()).hexdigest() != frozen["plan_sha256"]:
        raise ValueError("Parent frozen plan differs")
    failure = read(source / "main/failure.json")
    if failure.get("trial") is not None or failure.get("error") != "organization: HTTP None":
        raise ValueError("Only the recorded Billing outage between trials is eligible")
    if not read(source / "cleanup-inventory-verified.json")["complete"]:
        raise ValueError("Reconcile parent resources before continuation")
    rows = read(source / "main/rows.json")
    check_plan = {**plan, "confirmatory": False,
        "continuation": {"completed_trial_ids": [x["trial"] for x in rows]}}
    execution_trials(check_plan)
    directories = {p.name for p in (source / "trials").glob("main-*") if p.is_dir()}
    if directories != {x["trial"] for x in rows}:
        raise ValueError("Parent has an unaccounted started trial; never replay it")
    for row, spec in zip(rows, plan["trials"]):
        directory = source / "trials" / row["trial"]
        cost = read(directory / "cost-summary.json")
        verify_resource_coverage(read(directory / "resource-identities.json"), cost)
        if not row["valid"] or not row["lifecycle_complete"] or not cost["lifecycle_complete"]:
            raise ValueError("Parent row lacks complete measurement evidence")
        if row["accepted"] != spec["tasks"] or any(row[k] != v for k, v in task_summary(read(directory / "horizon-snapshot.json")).items()):
            raise ValueError("Parent row does not match its retained horizon snapshot")
        if (row["cost_lower_rub"], row["cost_upper_rub"]) != (cost["estimated_rub_lower"], cost["estimated_rub_upper"]):
            raise ValueError("Parent row cost does not match its retained ledger")
        audit = verify_backup(directory / "queue.sqlite", snapshot=read(directory / "snapshot.json"),
            expected_ids=[x["id"] for x in read(directory / "submitted.json")])
        if audit["sha256"] != read(directory / "backup-verified.json")["sha256"]:
            raise ValueError("Parent backup changed")
    return plan, rows, seal


def prepare(cloud, source, *, repeat_pair_from=None):
    source = Path(source).resolve()
    parent, rows, seal = parent_evidence(source)
    pair_policy = verify_pair_source(repeat_pair_from, parent, rows) if repeat_pair_from else None
    previous = read(source / "state.json")
    if previous["project_id"] != cloud.state["project_id"]:
        raise ValueError("Continuation project differs")
    differences = []
    for name, expected in parent["sources_sha256"].items():
        current = hashlib.sha256(Path(name).read_bytes()).hexdigest()
        if current != expected:
            differences.append(name)
            allowed = ADMINISTRATIVE_CHANGES | ({"h2/cloudru_ops.py"} if pair_policy else set())
            if name not in allowed:
                raise ValueError("Scientific source differs from parent: " + name)
    if hashlib.sha256((source / "main/references.json").read_bytes()).hexdigest() != parent["references_sha256"]:
        raise ValueError("Parent cloud references differ")
    cloud.plan.update(read(source / "plan.json"))
    cloud.plan.update(continuation_parent=str(source), pilot_only=False,
        recovery_note=DISCLOSURE, continuation_main_window_hours=9.25)
    if pair_policy:
        cloud.plan.update(pair_restart=pair_policy, recovery_note=pair_policy["disclosure"])
    cloud.state["budget_started_at"] = previous.get("budget_started_at", previous["created_at"])
    cloud.record()
    save(cloud.run / "plan.json", cloud.plan)
    policy = read(source / "budget-policy.json")
    policy.pop("deadline_and_resource_caps_unchanged", None)
    save(cloud.run / "budget-policy.json", {**policy, "at": stamp(), "inherited_from": str(source / "budget-policy.json"),
        "resource_caps_unchanged": True,
        "deadline_policy": "Separate disclosed continuation window: 9h15 after readiness, fixed before new main admissions.",
        "authorized_scope": ("Original remaining pairs, including one explicitly authorized whole-pair restart; no further automatic workload restarts."
            if pair_policy else "Only unstarted original trials; no replay, extra trials or automatic restart.")})
    save(cloud.run / "continuation.json", {"at": stamp(), "source": str(source), "source_seal": seal,
        "source_plan_sha256": read(source / "main/frozen.json")["plan_sha256"],
        "completed_trial_ids": [x["trial"] for x in rows],
        "remaining_trial_ids": [x["id"] for x in parent["trials"][len(rows):]],
        "changed_parent_sources": differences, "disclosure": pair_policy["disclosure"] if pair_policy else DISCLOSURE,
        "pair_restart": pair_policy, "failed_or_completed_trials_replayed": 1 if pair_policy else 0,
        "automatic_further_restarts": False})
    before = optional_evidence(cloud, "billing-before-continuation", lambda: billing(cloud, "before-continuation"))
    ceiling = budget_policy(cloud)["spending_ceiling_rub"]
    reserve = cloud.plan["estimated_six_hour_total_before_variable_usage"] / 6 * 2 + 50
    if ceiling is not None and (before is None or before["preliminary_rub_before_grant"] + reserve >= ceiling):
        raise RuntimeError("Continuation cannot verify the explicit monetary ceiling")


def freeze(cloud):
    source = Path(cloud.plan["continuation_parent"])
    parent, rows, seal = parent_evidence(source)
    if not read(cloud.run / "recheck/summary.json")["passed"]:
        raise ValueError("Validate the new cluster against the unchanged cloud references first")
    if read(cloud.run / "image-source.json")["id"] != read(source / "image-source.json")["id"]:
        raise ValueError("Container contents differ from parent")
    if cloud.state["published_image"].split("@")[-1] != parent["image"].split("@")[-1]:
        raise ValueError("Published image digest differs from parent")
    out = cloud.run / "main"
    out.mkdir(exist_ok=False)
    policy = budget_policy(cloud)
    before = budget_check(cloud, "continuation-window")
    source_names = tuple(dict.fromkeys((*SOURCES, "h2/cloudru_continuation.py", "h2/cloudru_finish.py", "h2/cloudru_main_report.py", "h2/cloudru_setup.py",
        "h2/cloudru_pool_recovery.py", "h2/cloudru_pair_policy.py")))
    continuation = read(cloud.run / "continuation.json")
    if continuation.get("pair_restart"):
        verified_pair = verify_pair_source(continuation["pair_restart"]["prior_session"], parent, rows)
        if verified_pair != continuation["pair_restart"]:
            raise ValueError("Pair restart evidence changed before main freeze")
    disclosure = continuation["disclosure"]
    plan = {**parent, "at": stamp(), "confirmatory": False, "image": cloud.state["published_image"],
        "deadline": (datetime.now(UTC) + timedelta(hours=9, minutes=15)).isoformat(),
        "continuation": continuation, "protocol_deviations": [disclosure],
        "budget_policy": policy, "total_run_budget_rub": policy["spending_ceiling_rub"],
        "pre_main_preliminary_billing_rub": before["preliminary_rub"],
        "maximum_remaining_base_spend_rub": cloud.plan["estimated_six_hour_total_before_variable_usage"] / 6 * 9.25,
        "sources_sha256": {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in source_names}}
    remaining = execution_trials(plan)
    required = sum(plan["observation_horizon_seconds"] + 90 + (600 if x["variant"] == "fixed" else 0)
                   for x in remaining if x["analysis_group"] != "optional_fault_demonstration") + 600
    if required >= 9.25 * 3600:
        raise ValueError("The fixed continuation window cannot fit all remaining required trials")
    save(out / "plan.json", plan)
    for name in source_names:
        target = out / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(name).read_bytes())
    for name in ("references.json", "calibration-summary.json"):
        shutil.copyfile(source / "main" / name, out / name)
    digest = hashlib.sha256((out / "plan.json").read_bytes()).hexdigest()
    save(out / "frozen.json", {"at": stamp(), "plan_sha256": digest, "before_any_main_admission_in_this_segment": True,
        "source_plan_sha256": read(source / "main/frozen.json")["plan_sha256"]})
    (out / "PLAN.md").write_text("# H2: оставшаяся часть парной серии\n\n" + disclosure +
        "\n\nСохранены все параметры исходного сравнения: 12 парных блоков, count=12, SLO=900 с, "
        "окно 1800 с, исходные аудио, образ, калибровка и порядок. Первые 12 прогонов остаются в архиве C; "
        "здесь выполняются только следующие 12 основных прогонов и 3 fixed-контроля. "
        "Последняя необязательная пара со сбоем — только при остатке 90 минут.\n\n"
        "Сбой Billing при отсутствии денежного предела сохраняется как недоступное значение, "
        "не заменяется нулём и не останавливает обработку. Лимиты узлов и времени сохранены.\n\n"
        f"Новый конечный срок: {plan['deadline']}. Хеш плана: `{digest}`. "
        f"Хеш исходного плана C: `{plan['continuation']['source_plan_sha256']}`.\n")
    return plan


def combine(run):
    run = Path(run)
    source = Path(read(run / "plan.json")["continuation_parent"])
    parent, previous, seal = parent_evidence(source)
    current = read(run / "main/rows.json") if (run / "main/rows.json").exists() else []
    expected = [x["id"] for x in parent["trials"]]
    all_rows = [*previous, *current]
    ids = [x["trial"] for x in all_rows]
    if ids != expected[:len(ids)]:
        raise ValueError("Combined rows must be the unchanged original prefix without duplicates or omissions")
    result = analyze(parent, all_rows, bootstrap_samples=parent["bootstrap_samples"])
    continued_plan = read(run / "main/plan.json") if (run / "main/plan.json").exists() else {}
    pair_policy = continued_plan.get("continuation", {}).get("pair_restart")
    disclosure = pair_policy["disclosure"] if pair_policy else DISCLOSURE
    result.update(original_numerical_criteria_met=result.get("h2_confirmed", False),
        confirmatory=False, protocol_deviations=[disclosure])
    if pair_policy:
        if pair_policy["policy"] != PAIR_POLICY:
            raise ValueError("Unknown whole-pair restart policy")
        result.update(interpretation_policy=PAIR_POLICY,
            sessions=session_summary(parent, ((source, previous), (run, current))),
            interpretation="Original numerical criteria on complete within-session pairs; all prior attempts retained.")
    else:
        result.update(h2_confirmed=False,
            interpretation="All outcomes retained; cluster/window interruption disclosed. Not an uninterrupted original confirmatory run.")
    out = run / "combined"
    (out / "main").mkdir(parents=True, exist_ok=False)
    save(out / "main/plan.json", {**parent, "confirmatory": False, "protocol_deviations": [disclosure]})
    if pair_policy:
        save(out / "prior-unpaired-result.json", pair_policy)
    save(out / "main/rows.json", [dict(row, source_run=str(origin))
        for origin, batch in ((source, previous), (run, current)) for row in batch])
    save(out / "main/analysis.json", result)
    save(out / "provenance.json", {"at": stamp(), "parent": str(source), "parent_seal": seal,
        "continuation": str(run), "parent_trials": len(previous), "continuation_trials": len(current),
        "original_plan_sha256": read(source / "main/frozen.json")["plan_sha256"],
        "continuation_plan_sha256": read(run / "main/frozen.json")["plan_sha256"]})
    (out / "main/PLAN.md").write_text((run / "main/PLAN.md").read_text())
    # Copy only plotting inputs, retaining their origins. Authoritative full
    # snapshots, SQLite backups and ledgers stay in the separate segment roots.
    for origin, batch in ((source, previous), (run, current)):
        for row in batch:
            target = out / "trials" / row["trial"]
            target.mkdir(parents=True)
            for name in ("timeline.jsonl", "submitted.json"):
                shutil.copyfile(origin / "trials" / row["trial"] / name, target / name)
    report(out)
    return result


def run(path, source, *, resume_preparation=False, repeat_pair_from=None):
    directory = Path(path).resolve()
    save(directory / "autopilot-status.json", {"at": stamp(), "status": "running", "pid": os.getpid(), "kind": "unstarted-suffix-continuation"})
    error = None
    try:
        if resume_preparation:
            cloud = Cloud(directory)
            if (directory / "main/frozen.json").exists() or list((directory / "trials").glob("*/submitted.json")):
                raise ValueError("Preparation recovery cannot restart a scientific trial")
            if not (directory / "preparation-recovery.json").exists() or not cloud.state.get("guard_stop_verified_at"):
                raise ValueError("Explicit preparation reconciliation and a verified guard are required")
            if Path(cloud.plan["continuation_parent"]).resolve() != Path(source).resolve():
                raise ValueError("Preparation recovery cannot change its parent series")
            parent_evidence(source)
            resume_after_guard(cloud)
            refresh_access_after_resume(cloud)
        else:
            prepare(Cloud(directory), source, repeat_pair_from=repeat_pair_from)
            phase(directory, "h2.cloudru_ops", "provision")
        phase(directory, "h2.cloudru_setup")
        phase(directory, "h2.cloudru_system")
        observed_phase(directory, "recheck", "h2.cloudru_recovery", "validate")
        phase(directory, "h2.cloudru_continuation", "freeze")
        phase(directory, "h2.cloudru_main", "open-window")
        try:
            cloud = Cloud(directory)
            create_dashboard(cloud)
            promote_dashboard(cloud, "Firefly H2 · " + directory.name)
        except Exception as optional_error:
            save(directory / "dashboard-error.json", {"at": stamp(), "error_type": type(optional_error).__name__,
                "http_status": getattr(optional_error, "status", None),
                "detail": cloud.client.redact(getattr(optional_error, "detail", str(optional_error)))})
        observed_phase(directory, "main", "h2.cloudru_main", "run")
    except Exception as exc:
        error = str(exc)
        save(directory / "autopilot-failure.json", {"at": stamp(), "error": error})
    try:
        cloud = Cloud(directory)
        if cloud.state.get("cluster"):
            phase(directory, "h2.cloudru_finish", "finish")
            phase(directory, "h2.cloudru_report")
        else:
            cloud.cleanup()
        if (directory / "main/rows.json").exists():
            phase(directory, "h2.cloudru_main_report")
        if (directory / "main/frozen.json").exists():
            combine(directory)
    except Exception as exc:
        error = (error + "; " if error else "") + str(exc)
        save(directory / "autopilot-cleanup-or-report-failure.json", {"at": stamp(), "error": str(exc)})
        try:
            Cloud(directory).stop()
        except Exception:
            pass
    status = {"at": stamp(), "status": "failed_with_evidence" if error else "completed", "error": error, "pid": os.getpid()}
    save(directory / "autopilot-status.json", status)
    if INDEX.exists():
        with INDEX.open("a") as stream:
            link = (f"[Объединённый отчёт](results/{directory.name}/combined/main/RESULTS.md). "
                    if (directory / "combined/main/RESULTS.md").exists()
                    else "Основной этап не завершён; объединённый отчёт ещё не создан. ")
            stream.write(f"\n\nАвтоматическое завершение {stamp()}: `{status['status']}`. " + link
                + "Перерыв и смена кластера раскрываются отдельно; архив C остаётся неполным.\n")
    cleanup = directory / "cleanup-inventory-verified.json"
    if cleanup.exists() and read(cleanup)["complete"]:
        watchdog = read(directory / "watchdog.json")["pid"]
        end = time.monotonic() + 60
        while process_is(watchdog, "h2.cloudru_ops") and time.monotonic() < end:
            time.sleep(5)
        print(json.dumps({"at": stamp(), "sealing": True, "status": status["status"]}), flush=True)
        subprocess.run([sys.executable, "-m", "h2.cloudru_finish", "seal", str(directory)], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["run", "resume", "freeze"])
    parser.add_argument("run", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--repeat-pair-from", type=Path)
    args = parser.parse_args()
    if args.action in {"run", "resume"}:
        if not args.source:
            parser.error("run requires --source")
        run(args.run, args.source, resume_preparation=args.action == "resume", repeat_pair_from=args.repeat_pair_from)
    else:
        freeze(Cloud(args.run))
