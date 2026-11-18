"""Read-only YC checks. Tokens remain in memory and never enter the report."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def yc(plan, *args, raw=False):
    completed = subprocess.run(
        ["yc", "--profile", plan["profile"], *args, *([] if raw else ["--format", "json"])],
        capture_output=True, text=True, timeout=150,
    )
    if completed.returncode:
        # CLI errors may contain diagnostics; never include auth command output.
        raise RuntimeError(f"YC command failed: {' '.join(args[:3])}, exit {completed.returncode}")
    return completed.stdout.strip() if raw else json.loads(completed.stdout)


def billing(plan):
    token = yc(plan, "iam", "create-token", raw=True)
    base = "https://billing.api.cloud.yandex.net/billing/v1/billingAccounts/"
    headers = {"Authorization": "Bearer " + token}

    def get(path):
        req = urllib.request.Request(base + path, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"Billing HTTP {error.code}") from None

    account = get(plan["billing_account_id"])
    bindings = []
    page_token = ""
    while True:
        from urllib.parse import urlencode
        query = "?" + urlencode({"pageSize": 1000, "pageToken": page_token})
        page = get(plan["billing_account_id"] + "/billableObjectBindings" + query)
        bindings.extend(page.get("billableObjectBindings", []))
        page_token = page.get("nextPageToken", "")
        if not page_token:
            break
    # Avoid copying billing contact details if the API schema grows.
    return {
        "account": {key: account.get(key) for key in ("id", "active", "currency", "balance")},
        "cloud_bound": any(b.get("billableObject", {}).get("id") == plan["cloud_id"] for b in bindings),
        "grant_api_note": "Account balance is not proof of remaining monetary grant; grant details are checked in Billing UI.",
    }


def estimate(plan):
    rates = {key: Decimal(value) for key, value in plan["rates_rub_per_hour"].items()}
    total = Decimal(0)
    roles = {}
    for machine in plan["machines"]:
        hourly = (
            machine["cores"] * rates["vcpu"]
            + machine["memory_gib"] * rates["ram_gib"]
            + machine["ssd_gib"] * rates["network_ssd_gib"]
            + int(machine["public_ip"]) * rates["active_public_ipv4"]
        )
        roles[machine["role"]] = str(hourly)
        total += hourly
    return {
        "by_role_rub_per_hour": roles,
        "total_rub_per_hour": str(total),
        "first_window_base_cost_rub": str(total * Decimal(str(plan["first_window_hours"]))),
        "persistent_disks_rub_per_day_after_stop": str(sum(m["ssd_gib"] for m in plan["machines"]) * rates["network_ssd_gib"] * 24),
        "excludes": ["custom metrics", "object storage", "chargeable egress", "tax/tariff changes after price_checked_on"],
        "note": "Estimate before grants; stopping VMs does not delete billable disks. This is not a Billing hard spending limit.",
    }


def check_quotas(plan, compute, vpc):
    quotas = {q["quota_id"]: q for data in (compute, vpc) for q in data.get("quota_limits", [])}
    machines = plan["machines"]
    requested = {
        "compute.instances.count": len(machines),
        "compute.instanceCores.count": sum(m["cores"] for m in machines),
        "compute.instanceMemory.size": sum(m["memory_gib"] for m in machines) * 2**30,
        "compute.ssdDisks.size": sum(m["ssd_gib"] for m in machines) * 2**30,
        "compute.disks.count": len(machines),
        "vpc.externalAddresses.count": sum(int(m["public_ip"]) for m in machines),
        "vpc.networks.count": 1,
        "vpc.subnets.count": 1,
        "vpc.securityGroups.count": 2,
    }
    rows = []
    for key, need in requested.items():
        q = quotas.get(key)
        available = float(q["limit"]) - float(q.get("usage", 0)) if q else None
        rows.append({"quota": key, "required": need, "available": available, "fits": available is not None and available >= need})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=ROOT / "cloud/plan.json")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    plan_bytes = args.plan.read_bytes()
    plan = json.loads(plan_bytes)
    tasks = {
        "folder": lambda: yc(plan, "resource-manager", "folder", "get", plan["folder_id"]),
        "compute_quotas": lambda: yc(plan, "quota-manager", "quota-limit", "list", "--service", "compute", "--resource-type", "resource-manager.cloud", "--resource-id", plan["cloud_id"]),
        "vpc_quotas": lambda: yc(plan, "quota-manager", "quota-limit", "list", "--service", "vpc", "--resource-type", "resource-manager.cloud", "--resource-id", plan["cloud_id"]),
        "billing": lambda: billing(plan),
        "image": lambda: yc(plan, "compute", "image", "get", plan["image_id"]),
        "zones": lambda: yc(plan, "compute", "zone", "list"),
    }
    for service, kind in (("compute", "instance"), ("compute", "disk"), ("vpc", "network"), ("vpc", "subnet"), ("vpc", "security-group"), ("iam", "service-account")):
        tasks[f"{service}_{kind}"] = lambda s=service, k=kind: yc(plan, s, k, "list", "--folder-id", plan["folder_id"])
    report = {"checked_at": datetime.now(UTC).isoformat(), "plan_sha256": hashlib.sha256(plan_bytes).hexdigest(), "read_only": True, "errors": {}, "observations": {}, "estimate": estimate(plan)}
    with ThreadPoolExecutor(max_workers=4) as executor:
        pending = {executor.submit(func): name for name, func in tasks.items()}
        for future in as_completed(pending):
            name = pending[future]
            try:
                report["observations"][name] = future.result()
            except Exception as error:
                report["errors"][name] = str(error)
    obs = report["observations"]
    report["quota_checks"] = check_quotas(plan, obs.get("compute_quotas", {}), obs.get("vpc_quotas", {}))
    report["grant"] = plan["grant"]
    report["cpu_quota_sufficient"] = all(row["fits"] for row in report["quota_checks"])
    report["gpu_quotas"] = [q for q in obs.get("compute_quotas", {}).get("quota_limits", []) if "Gpus" in q["quota_id"]]
    report["folder_matches_cloud"] = obs.get("folder", {}).get("cloud_id") == plan["cloud_id"]
    report["zone_up"] = any(z["id"] == plan["zone"] and z.get("status") == "UP" for z in obs.get("zones", []))
    report["grant_details_confirmed"] = all(plan["grant"].get(k) is not None for k in ("confirmed_remaining_rub", "expires_at"))
    report["resources_created_by_check"] = []
    (args.output / "plan.json").write_bytes(plan_bytes)
    (args.output / "preflight.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("checked_at", "cpu_quota_sufficient", "folder_matches_cloud", "zone_up", "grant_details_confirmed", "errors", "estimate")}, ensure_ascii=False, indent=2))
    if report["errors"] or not report["cpu_quota_sufficient"] or not report["folder_matches_cloud"] or not report["zone_up"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
