"""Frozen paired H2 comparison with real cloud allocation and bounded cleanup."""
import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import random
import time

from h2.cloud_analysis import analyze
from h2.cloud_budget import policy as budget_policy
from h2.cloudru_access import AccessError
from h2.cloudru_billing import BillingUnavailable, consumption
from h2.cloudru_preflight import CloudruError
from h2.cloud_costs import task_summary, verify_resource_coverage
from h2.cloud_tuning import workloads
from h2.cloudru_ops import Cloud, save, stamp
from h2.cloudru_trial import Trial
from h2.cloudru_window import change_window

SOURCES = ("h2/cloud_budget.py", "h2/cloudru_billing.py", "h2/cloudru_recovery.py", "h2/cloudru_window.py", "h2/cloudru_main.py", "h2/cloud_analysis.py", "h2/cloud_tuning.py", "h2/cloudru_trial.py",
    "h2/cloud_trial.py", "h2/cloudru_manifests.py", "h2/manifests.py", "h2/cloudru_ops.py",
    "h2/cloud_costs.py", "h2/coordinator.py", "h2/capacity.py", "h2/queue.py", "h2/worker.py",
    "worktrees/h2-autoscaling/firefly-backend/app/modules/speech/workload_scaling.py")


def matrix(seed=20261005):
    rng = random.Random(seed)
    orders = {scenario: [0, 0, 1, 1] for scenario in workloads()}
    for order in orders.values():
        rng.shuffle(order)
    trials = []
    for block in range(4):
        scenarios = list(workloads())
        rng.shuffle(scenarios)
        for scenario in scenarios:
            variants = ("count", "work") if orders[scenario][block] == 0 else ("work", "count")
            for variant in variants:
                trials.append({"id": f"main-{scenario}-{block:02d}-{variant}", "variant": variant,
                    "scenario": scenario, "block": block, "tasks": 24, "analysis_group": "primary", "fault": False})
    for scenario in workloads():
        trials.append({"id": "main-" + scenario + "-fixed", "variant": "fixed", "scenario": scenario,
            "block": 0, "tasks": 24, "analysis_group": "fixed_control", "fault": False})
    variants = ["count", "work"]
    rng.shuffle(variants)
    for variant in variants:
        trials.append({"id": "main-mixed-fault-" + variant, "variant": variant, "scenario": "mixed", "block": 0,
            "tasks": 24, "analysis_group": "optional_fault_demonstration", "fault": True})
    return trials


def freeze(cloud):
    calibration = Path(getattr(cloud, "plan", {}).get("calibration_run", cloud.run))
    tuning = json.loads((calibration / "tuning/summary.json").read_text())
    if not tuning["passed"]:
        raise ValueError("Real-cloud pilot validation must pass before freezing")
    # Earlier pilot adapters recorded invariant violations as observation
    # errors. Audit those retained errors before trusting baseline selection.
    invalid_terms = ("allocation changed", "Unexpected VM state", "ownership", "resurrected",
        "ASR VM unexpectedly", "strictly chronological", "Resource created after", "Invalid VM allocation",
        "Unsupported disk allocation", "Unexpected node", "Trial disk", "Duplicate resource")
    for trial in tuning["results"]:
        directory = calibration / "trials" / trial["trial"]
        if (directory / "validation-failure.json").exists() or (directory / "placement-failure.json").exists():
            raise ValueError("Baseline pilot has an invalid resource observation")
        errors = directory / "observation-errors.jsonl"
        if errors.exists():
            for line in errors.read_text().splitlines():
                if any(term in json.loads(line)["error"] for term in invalid_terms):
                    raise ValueError("Baseline pilot contains a resource-accounting invariant violation")
        verify_resource_coverage(json.loads((directory / "resource-identities.json").read_text()),
                                 json.loads((directory / "cost-summary.json").read_text()))
    out = cloud.run / "main"
    config = tuning["selected"]["config"]
    deadline = datetime.now(UTC) + timedelta(hours=15, minutes=15)
    horizon = 1800
    primary_and_control_seconds = 27 * (horizon + 90) + 3 * 600 + 600
    if (deadline - datetime.now(UTC)).total_seconds() < primary_and_control_seconds:
        raise RuntimeError("Insufficient bounded window for the full primary and control matrix; do not freeze a truncated plan")
    out.mkdir(exist_ok=False)
    prior_bill = budget_check(cloud, "main-window")
    spending_policy = budget_policy(cloud)
    billing_text = (f"{prior_bill['preliminary_rub']:.2f} ₽ предварительных начислений"
        if prior_bill["preliminary_rub"] is not None else "недоступен; требуется последующая сверка")
    plan = {"at": stamp(), "confirmatory": True, "image": cloud.state["published_image"], "config": config,
        "slo_seconds": tuning["selected"]["slo_seconds"], "observation_horizon_seconds": horizon,
        "workloads": workloads(group="main"), "trials": matrix(), "required_on_time_rate": .95,
        "on_time_noninferiority_margin": .02, "required_result_parity_rate": 1,
        "bootstrap_seed": 20261005, "bootstrap_samples": 20000,
        "deadline": deadline.isoformat(), "total_run_budget_rub": spending_policy["spending_ceiling_rub"],
        "planning_target_rub": spending_policy["planning_target_rub"], "budget_policy": spending_policy,
        "spending_ceiling_description": (f"{spending_policy['spending_ceiling_rub']:g} ₽ с резервом"
            if spending_policy["spending_ceiling_rub"] is not None
            else "денежная остановка отключена по просьбе владельца; действуют фиксированные матрица, ресурсы и срок"),
        "maximum_remaining_base_spend_rub": cloud.plan["estimated_six_hour_total_before_variable_usage"] / 6 * 15.25,
        "pre_main_preliminary_billing_rub": prior_bill["preliminary_rub"],
        "budget_note": "Includes the original attempt. Planning target is informational. An explicitly set spending ceiling uses a reserve; a null ceiling means monitoring without monetary interruption.",
        "sources_sha256": {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in SOURCES},
        "references_sha256": hashlib.sha256((calibration / "pilot/references.json").read_bytes()).hexdigest(),
        "calibration_source": str(calibration),
        "calibration_seal": json.loads((calibration / "sealed.json").read_text()) if (calibration / "sealed.json").exists() else None,
        "measurement_clock": "Coordinator UTC brackets each inventory; local wall clock is diagnostic only. The 1800-second horizon uses the same clock as admission.",
        "prior_incomplete_series": cloud.plan.get("prior_incomplete_series"),
        "cost_rule": "VM+SSD creation-to-deletion allocation estimate, including actual excess nodes and idle tail. Common master/system cost separate.",
        "decision_rule": "All planned primary blocks valid; exact result parity; both strategies >=95% on-time in each scenario; lower paired on-time CI >=-2 pp; upper conservative paired cost ratio CI <1.",
        "fixed_control_rule": "Three warm workers before admission; fresh group setup cost retained and disclosed. Secondary descriptive control only.",
        "fault_rule": "Optional final paired demonstration only if >=90 guarded minutes remain for both trials; kill one owned worker while ASR runs. Never mixed into primary CI.",
        "failure_rule": "Retain every admitted task and failed attempt. No replacing failed primary trials or stopping for an attractive result."}
    save(out / "plan.json", plan)
    source_dir = out / "source"
    for name in SOURCES:
        target = source_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(name).read_bytes())
    (out / "references.json").write_bytes((calibration / "pilot/references.json").read_bytes())
    (out / "calibration-summary.json").write_bytes((calibration / "tuning/summary.json").read_bytes())
    plan_hash = hashlib.sha256((out / "plan.json").read_bytes()).hexdigest()
    save(out / "frozen.json", {"at": stamp(), "plan_sha256": plan_hash, "before_any_main_admission": True})
    (out / "PLAN.md").write_text(f'''# H2: основная серия Cloud.ru\n\nЗафиксирована {plan['at']}, до первой основной задачи.\nХеш JSON-плана: `{plan_hash}`.\n\n12 парных блоков: по четыре для короткого, длинного и смешанного пакета\nиз 24 заданий. В каждом блоке count и work идут подряд; порядок AB/BA\nсбалансирован внутри сценария и перемешан с seed 20261005. Пилотные\nаудио и измерения не входят в основную выборку. Отдельно выполняются\nтри описательных fixed-контроля и, при запасе времени, одна пара со сбоем.\n\nSLO: {plan['slo_seconds']} с после приёма. Count target: {config['target_queue']}.\nХолодный старт в контроллере: {config['cold_start_seconds']} с.\nВсе варианты используют один образ, ресурсы и HPA/KEDA. Динамический\nпрогон начинается с нуля ВМ. Наблюдение длится 1800 с после первого\nприёма независимо от того, когда закончилась работа. Затем — выгрузка\nи очистка. Ручная очистка не считается автоматическим scale-to-zero.\n\nОсновной денежный показатель — расчётные ВМ+SSD на корректную задачу.\nУчитываются все ВМ группы, включая избыточные, provisioning и простой.\nПервичный ratio использует верхнюю границу стоимости work и нижнюю\nграницу count. Bootstrap: 20000 выборок парных блоков внутри сценария,\n95% CI; задания одного блока не считаются независимыми повторами.\n\nДля подтверждения требуются все 12 пар, точное совпадение результатов,\nне менее 95% в срок у обеих стратегий в каждом сценарии, нижняя граница\nCI разницы своевременности не ниже −2 п.п. и верхняя граница CI стоимости\nниже 1. Неполная серия, ошибки или незавершённые задачи не исключаются\nради положительного вывода. При невыполнении критериев H2 не подтверждена.\n\nЭто CPU-эксперимент на синтетической речи с готовой tiny.en. Вывод\nограничен этими нагрузками и облачным окном; редкие сбои, GPU и HA\nкоординатора не доказываются. Расчётные рубли не выдаются за начисления\nBilling по отдельному прогону. Общие расходы master/system и Billing\nпубликуются отдельно.\n\nПлановый ориентир — {plan['planning_target_rub']:g} ₽ до гранта; его превышение не останавливает серию. Допустимый общий расход, включая первую попытку, — {plan['spending_ceiling_description']}.\nНовый абсолютный срок удаления: {plan['deadline']}.\nПредварительная верхняя оценка постоянных тарифов нового окна:\n{plan['maximum_remaining_base_spend_rub']:.2f} ₽. До него Billing: {billing_text}. Перед каждым прогоном проверяется общий бюджет с резервом на задержку Billing, переменные услуги и очистку. При явно заданном денежном пределе новые прогоны допускаются с резервом; в режиме наблюдения сумма начислений не останавливает серию. Каждая проверка сохраняет действующую денежную политику; её отдельное согласованное изменение не меняет научные параметры. Это не технический лимит счёта Cloud.ru.\n''')
    return plan


def check_frozen(cloud):
    out = cloud.run / "main"
    frozen = json.loads((out / "frozen.json").read_text())
    if hashlib.sha256((out / "plan.json").read_bytes()).hexdigest() != frozen["plan_sha256"]:
        raise ValueError("Frozen main plan changed")
    plan = json.loads((out / "plan.json").read_text())
    if plan["image"] != cloud.state["published_image"]:
        raise ValueError("Main image identity changed")
    for name, expected in plan["sources_sha256"].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest() != expected:
            raise ValueError("Frozen runtime source changed: " + name)
    if hashlib.sha256((out / "references.json").read_bytes()).hexdigest() != plan["references_sha256"]:
        raise ValueError("Frozen cloud references changed")
    return plan


def open_window(cloud):
    plan = check_frozen(cloud)
    proof = change_window(cloud, deadline=plan["deadline"], phase="main")
    save(cloud.run / "main/guard-window.json", proof)


def budget_check(cloud, trial_id):
    spending_policy = budget_policy(cloud)
    now = datetime.now(UTC)
    query = {"project_ids": cloud.client.project_id,
        "start_date": datetime.fromisoformat(cloud.state.get("budget_started_at", cloud.state["created_at"])).replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
        "end_date": now.isoformat(), "page_filter.limit": 100, "page_filter.page": 1}
    # Billing is asynchronous. Keep a whole maximum-rate hour plus two trial
    # horizons and 50 RUB for delayed variable charges/cleanup as a reserve.
    reserve = cloud.plan["estimated_six_hour_total_before_variable_usage"] / 6 * 2 + 50
    ceiling = spending_policy["spending_ceiling_rub"]
    try:
        snapshot = consumption(cloud.client, query)
    except (CloudruError, AccessError, BillingUnavailable) as error:
        report = {"at": stamp(), "query": query, "billing_available": False,
            "preliminary_rub": None, "planning_target_exceeded": None, **spending_policy,
            "reserve_rub": reserve, "admission_allowed": ceiling is None,
            "not_a_hard_billing_cap": True, "reconciliation_required": True,
            "error_type": type(error).__name__, "http_status": getattr(error, "status", None),
            "note": "Billing unavailable after bounded reads. Unknown spend is not zero; retry at the next scheduled check."}
        save(cloud.run / "main" / ("billing-before-" + trial_id + ".json"), report)
        if ceiling is not None:
            raise RuntimeError("Billing unavailable with an explicit spending ceiling; no new admission") from error
        return report
    billed = snapshot["preliminary_rub"]
    allowed = ceiling is None or billed + reserve < ceiling
    report = {"at": stamp(), "query": query, "response": {"consumptions": snapshot["consumptions"]},
              "pages": snapshot["pages"], "billing_available": True, "preliminary_rub": billed,
              **spending_policy, "planning_target_exceeded": billed >= spending_policy["planning_target_rub"],
              "reserve_rub": reserve, "admission_allowed": allowed, "not_a_hard_billing_cap": True}
    save(cloud.run / "main" / ("billing-before-" + trial_id + ".json"), report)
    if not allowed:
        raise RuntimeError("Budget reserve reached; preserve partial results and clean up")
    return report


def inject_fault(trial):
    snapshot = trial.api("/snapshot")
    eligible = [x for x in snapshot["tasks"] if x["state"] == "running" and x["stage"] == "asr"
                and snapshot["at"] - x["stage_started_at"] >= 2]
    if not eligible:
        return False
    task = sorted(eligible, key=lambda x: (x["first_started_at"], x["id"]))[0]
    pods = json.loads(trial.cloud.kube("-n", trial.ns, "get", "pods", "-l", "app=worker", "-o", "json"))
    matches = [p for p in pods["items"] if p["metadata"]["uid"] == task["worker"]]
    if len(matches) != 1:
        return False
    pod = matches[0]
    if pod["spec"].get("nodeName") not in trial.known_nodes:
        raise ValueError("Refuse to fault a pod outside the owned trial pool")
    proof = {"at": stamp(), "task": task, "pod": pod, "kind": "forced worker deletion during ASR"}
    save(trial.output / "fault-intent.json", proof)
    trial.cloud.kube("-n", trial.ns, "delete", "pod", pod["metadata"]["name"],
                     "--grace-period=0", "--force", "--wait=false")
    save(trial.output / "fault-requested.json", {"at": stamp(), "old_uid": task["worker"], "task_id": task["id"]})
    return True


def execution_trials(plan):
    continuation = plan.get("continuation")
    if not continuation:
        return plan["trials"]
    completed = continuation["completed_trial_ids"]
    prefix = plan["trials"][:len(completed)]
    if plan.get("confirmatory") is not False or not completed:
        raise ValueError("Continuation must disclose the protocol deviation")
    if completed != [x["id"] for x in prefix] or any(x["analysis_group"] != "primary" for x in prefix):
        raise ValueError("Continuation must use an exact primary prefix, without selecting results")
    pairs = {}
    for spec in prefix:
        pairs.setdefault((spec["scenario"], spec["block"]), set()).add(spec["variant"])
    if any(variants != {"count", "work"} for variants in pairs.values()):
        raise ValueError("Continuation cannot split a paired block between clusters")
    return plan["trials"][len(completed):]


def run(cloud):
    plan = check_frozen(cloud)
    if not cloud.state.get("main_window_opened_at") or cloud.state["deadline"] != plan["deadline"]:
        raise ValueError("Verify both guards for the main window first")
    out = cloud.run / "main"
    if (out / "rows.json").exists():
        raise ValueError("A started main matrix requires explicit reconciliation; never silently retry trials")
    refs = json.loads((out / "references.json").read_text())
    rows = []
    trial = None
    try:
        optional_allowed = None
        for spec in execution_trials(plan):
            check_frozen(cloud)
            remaining = (datetime.fromisoformat(cloud.state["deadline"]) - datetime.now(UTC)).total_seconds()
            if spec["analysis_group"] == "optional_fault_demonstration":
                if optional_allowed is None:
                    optional_allowed = remaining >= 5400
                if not optional_allowed:
                    save(out / "optional-fault-skipped.json", {"at": stamp(), "reason": "Less than 90 guarded minutes for the whole optional pair"})
                    continue
            if remaining < 2700 + (600 if spec["variant"] == "fixed" else 0):
                raise RuntimeError("Guarded window cannot fit another complete trial; do not truncate its horizon")
            budget_check(cloud, spec["id"])
            cfg = {**plan["config"], "variant": spec["variant"], "fixed_workers": 3}
            trial = Trial(cloud, spec["id"], cfg, phase="main")
            trial.setup(fixed_nodes=3 if spec["variant"] == "fixed" else None)
            if spec["variant"] == "fixed":
                cloud.kube("-n", trial.ns, "wait", "deployment/worker", "--for=jsonpath={.status.readyReplicas}=3",
                           "--timeout=600s", timeout=610)
            if not trial.api("/metrics")["capacity_observation"]["fresh"]:
                raise ValueError("Capacity observation unavailable before admission")
            for fixture in plan["workloads"][spec["scenario"]]:
                trial.admit(fixture, expected_sha=refs[fixture]["sha256"], deadline_seconds=plan["slo_seconds"])
            origin = min(x["accepted_at"] for x in trial.submitted)
            end = origin + plan["observation_horizon_seconds"]
            faulted = False
            while (horizon_remaining := trial.seconds_until(end)) > 0:
                if getattr(trial, "fatal_observation_error", None):
                    raise ValueError(trial.fatal_observation_error)
                if trial.forward.poll() is not None:
                    raise RuntimeError("Lost coordinator connection during the observation horizon")
                if spec["fault"] and not faulted:
                    faulted = inject_fault(trial)
                time.sleep(min(2, horizon_remaining))
            snapshot = trial.api("/snapshot")
            save(trial.output / "horizon-snapshot.json", snapshot)
            summary = task_summary(snapshot)
            trial.retire()
            cost = json.loads((trial.output / "cost-summary.json").read_text())
            verify_resource_coverage(json.loads((trial.output / "resource-identities.json").read_text()), cost)
            row = {"trial": spec["id"], "at": stamp(), "valid": True,
                "lifecycle_complete": cost["lifecycle_complete"], **summary,
                "cost_lower_rub": cost["estimated_rub_lower"], "cost_upper_rub": cost["estimated_rub_upper"],
                "fault_requested": faulted, "fault_required": spec["fault"],
                "observation_horizon_seconds": plan["observation_horizon_seconds"]}
            rows.append(row)
            save(out / "rows.json", rows)
            save(out / "analysis.json", analyze(plan, rows, bootstrap_samples=plan["bootstrap_samples"]))
            print(json.dumps({"phase": "main-trial-retired", **row}), flush=True)
            trial = None
        result = analyze(plan, rows, bootstrap_samples=plan["bootstrap_samples"])
        save(out / "summary.json", {"at": stamp(), "analysis": result,
            "completed_trials": len(rows), "planned_trials": len(plan["trials"]),
            "cost_basis": "resource_time_estimate_not_billing"})
    except BaseException as error:
        save(out / "failure.json", {"at": stamp(), "trial": trial.id if trial else None, "error": str(error)})
        if trial:
            try:
                trial.backup()
            except Exception as backup_error:
                save(trial.output / "backup-error.json", {"error": str(backup_error)})
            trial.close()
        save(out / "partial-analysis.json", analyze(plan, rows, bootstrap_samples=plan["bootstrap_samples"]))
        cloud.stop()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze", "open-window", "run"])
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    cloud = Cloud(args.run)
    {"freeze": freeze, "open-window": open_window, "run": run}[args.action](cloud)
