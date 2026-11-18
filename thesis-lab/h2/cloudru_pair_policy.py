"""Prospective whole-pair restart rule; retained outcomes never choose retries."""
import json
from pathlib import Path

from h2.cloud_costs import task_summary, verify_resource_coverage
from h2.cloud_trial import verify_backup

POLICY = "complete-pairs-across-sessions-v1"
DISCLOSURE = (
    "Сравнение проводится полными парами в нескольких сеансах при прежней конфигурации. "
    "Шесть завершённых пар C сохранены. После инфраструктурного сбоя E до задач второй "
    "стратегии оборванная пара повторяется целиком; её прежний одиночный результат "
    "сохранён отдельно. Порядок, нагрузки и численные критерии не меняются."
)
MEASUREMENT_FIELDS = (
    "config", "slo_seconds", "observation_horizon_seconds", "workloads", "trials",
    "required_on_time_rate", "on_time_noninferiority_margin", "required_result_parity_rate",
    "bootstrap_seed", "bootstrap_samples", "references_sha256", "measurement_clock",
    "cost_rule", "decision_rule", "fixed_control_rule", "fault_rule", "failure_rule",
)


def restart_pair(parent, completed, prior_rows, failure):
    """Choose by matrix position and missing counterpart, never by performance."""
    specs = parent["trials"]
    n = len(completed)
    if [r["trial"] for r in completed] != [s["id"] for s in specs[:n]]:
        raise ValueError("Completed prefix changed")
    if len(prior_rows) != 1 or prior_rows[0]["trial"] != specs[n]["id"]:
        raise ValueError("Only one retained first half of the next pair is eligible")
    a, b = specs[n:n + 2]
    if (a["analysis_group"] != "primary" or b["analysis_group"] != "primary"
            or (a["scenario"], a["block"]) != (b["scenario"], b["block"])
            or {a["variant"], b["variant"]} != {"work", "count"}):
        raise ValueError("Restart must include one complete original pair")
    if failure != {"trial": b["id"], "error": "mk8s: HTTP None"}:
        raise ValueError("Restart is limited to the recorded pre-admission infrastructure failure")
    return [a["id"], b["id"]]


def verify_pair_source(source, parent, completed):
    from h2.cloudru_continuation import verify_archive
    source = Path(source).resolve()
    read = lambda name: json.loads((source / name).read_text())
    seal = verify_archive(source)
    prior = read("main/plan.json")
    if any(prior[k] != parent[k] for k in MEASUREMENT_FIELDS):
        raise ValueError("Interrupted session measurement parameters differ")
    if prior["image"].split("@")[-1] != parent["image"].split("@")[-1]:
        raise ValueError("Interrupted session image differs")
    if not read("cleanup-inventory-verified.json")["complete"]:
        raise ValueError("Interrupted session resources have not been reconciled")
    rows, failure = read("main/rows.json"), read("main/failure.json")
    pair = restart_pair(parent, completed, rows, {k: failure[k] for k in ("trial", "error")})
    failed = source / "trials" / pair[1]
    if any((failed / name).exists() for name in ("submitted.json", "manifest.json", "timeline.jsonl")):
        raise ValueError("The counterpart already entered workload setup/admission")
    if {p.name for p in (source / "trials").glob("main-*")} != set(pair):
        raise ValueError("Unexpected extra trial in interrupted session")
    events = [json.loads(s) for s in (source / "events.jsonl").read_text().splitlines()]
    if not any(x.get("name") == "request_error" and x.get("label") == "pool:" + pair[1]
               and x.get("http_status") is None for x in events):
        raise ValueError("Missing evidence of the pre-admission pool creation failure")
    d = source / "trials" / pair[0]
    load = lambda name: json.loads((d / name).read_text())
    row, snapshot, cost = rows[0], load("horizon-snapshot.json"), load("cost-summary.json")
    if not row["valid"] or not row["lifecycle_complete"] or not cost["lifecycle_complete"]:
        raise ValueError("Prior standalone trial lacks a complete measurement record")
    if any(row[k] != v for k, v in task_summary(snapshot).items()):
        raise ValueError("Prior standalone row differs from snapshot")
    verify_resource_coverage(load("resource-identities.json"), cost)
    if (row["cost_lower_rub"], row["cost_upper_rub"]) != (cost["estimated_rub_lower"], cost["estimated_rub_upper"]):
        raise ValueError("Prior standalone cost differs from its ledger")
    audit = verify_backup(d / "queue.sqlite", snapshot=load("snapshot.json"),
        expected_ids=[x["id"] for x in load("submitted.json")])
    if audit["sha256"] != load("backup-verified.json")["sha256"]:
        raise ValueError("Prior standalone backup changed")
    return {"policy": POLICY, "prior_session": str(source), "prior_seal": seal,
        "repeated_pair": pair, "retained_unpaired_rows": rows,
        "selection_rule": "Whole pair chosen solely by the missing counterpart before new observations; no selection by outcome.",
        "primary_rule": "Use both new attempts for this pair regardless of outcome; never choose the better work attempt.",
        "disclosure": DISCLOSURE}


def session_summary(plan, batches):
    specs = {s["id"]: s for s in plan["trials"] if s["analysis_group"] == "primary"}
    pair_sources, sessions = {}, []
    for source, rows in batches:
        selected = [r for r in rows if r["trial"] in specs]
        for row in selected:
            s = specs[row["trial"]]
            key = (s["scenario"], s["block"])
            if key in pair_sources and pair_sources[key] != str(source):
                raise ValueError("A primary pair crosses session boundaries")
            pair_sources[key] = str(source)
        sessions.append({"source_run": str(source), "primary_trials": len(selected),
            "variants": {variant: {field: sum(r[field] for r in selected if specs[r["trial"]]["variant"] == variant)
                for field in ("accepted", "correct", "on_time", "cost_lower_rub", "cost_upper_rub")}
                for variant in ("work", "count")}})
    return sessions
