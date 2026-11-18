"""Read-only H2 cloud inventory and Billing snapshot; never provisions resources.

Authentication is the owner's existing YC profile. Tokens stay in memory.
Raw source responses are retained for later tariff/quota review, but no billing
contact details or credential files are copied into the experiment archive.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def cli(plan, *args, timeout=90, raw=False):
    command = ["yc", "--profile", plan["profile"], "--folder-id", plan["folder_id"],
               "--no-browser", *args]
    if not raw:
        command += ["--format", "json"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError("YC command timed out; interactive authentication may be required: "
                           + " ".join(args[:3])) from None
    if result.returncode:
        # Never log auth output, auth URLs or credentials from command diagnostics.
        raise RuntimeError("YC command failed: " + " ".join(args[:3]) + "; exit=" + str(result.returncode))
    return result.stdout.strip() if raw else json.loads(result.stdout or "null")


def billing_account_and_skus(plan, token):
    def get(path, query=None):
        url = "https://billing.api.cloud.yandex.net/billing/v1/" + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)

    account = get("billingAccounts/" + plan["billing_account_id"])
    # The public schema omits remaining promotional grant information.
    account = {k: account.get(k) for k in ("id", "active", "currency", "balance")}
    skus, pages, page_token = [], 0, ""
    while True:
        page = get("skus", {"currency": "RUB", "billingAccountId": plan["billing_account_id"],
                            "pageSize": 1000, "pageToken": page_token})
        skus.extend(page.get("skus", []))
        pages += 1
        page_token = page.get("nextPageToken", "")
        if not page_token:
            break
        if pages >= 30:
            raise RuntimeError("SKU pagination exceeded 30 pages; tariff data incomplete")
    return {"account": account, "currency_requested": "RUB", "sku_pages": pages, "skus": skus}


def quota_requirements(*, zone="ru-central1-a", zonal=False):
    # A fixed system node plus at most three simultaneous ASR worker nodes.
    result = {"compute.instances.count": 4, "compute.instanceCores.count": 16,
            "compute.instanceMemory.size": 32 * 2**30, "compute.ssdDisks.size": 160 * 2**30,
            "compute.disks.count": 4, "vpc.externalAddresses.count": 5,
            "vpc.networks.count": 1, "vpc.subnets.count": 1, "vpc.securityGroups.count": 1}
    if zonal:
        for key in ("compute.instanceCores.count", "compute.instanceMemory.size", "compute.ssdDisks.size"):
            result[key + "." + zone] = result.pop(key)
    result.update({"managed-kubernetes.clusters.count": 1, "managed-kubernetes.nodeGroups.count": 2,
                   "managed-kubernetes.nodes.count": 4, "managed-kubernetes.cores.count": 16,
                   "managed-kubernetes.memory.size": 32 * 2**30,
                   "managed-kubernetes.disk.size": 160 * 2**30,
                   "managed-kubernetes.masterCores.count": 2,
                   "managed-kubernetes.masterMemory.size": 8 * 2**30,
                   "container-registry.registries.count": 1})
    return result


def assess_quotas(observations, *, zone="ru-central1-a"):
    quotas = {q["quota_id"]: q for key, value in observations.items() if key.startswith("quota_")
              for q in value.get("quota_limits", [])}
    return [{"id": key, "needed": needed,
             "available": float(quotas[key]["limit"]) - float(quotas[key].get("usage", 0)) if key in quotas else None,
             "fits": key in quotas and float(quotas[key]["limit"]) - float(quotas[key].get("usage", 0)) >= needed}
            for key, needed in quota_requirements(zone=zone,
                zonal="compute.instanceCores.count." + zone in quotas).items()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--plan", type=Path, default=ROOT / "cloud/plan.json")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    plan = json.loads(args.plan.read_text())
    now = datetime.now(UTC)
    report = {"at": now.isoformat(), "read_only": True, "created_resources": [],
              "errors": {}, "observations": {}, "provisioning_ready": False}
    save(args.output / "context.json", {k: plan[k] for k in
         ("profile", "cloud_id", "folder_id", "billing_account_id", "zone")})
    try:
        token = cli(plan, "iam", "create-token", timeout=45, raw=True)
    except RuntimeError as exc:
        report["errors"]["authentication"] = str(exc)
        save(args.output / "preflight.json", report)
        print(json.dumps({"read_only": True, "errors": report["errors"]}, ensure_ascii=False))
        raise SystemExit(2)

    queries = {
        "folder": lambda: cli(plan, "resource-manager", "folder", "get", plan["folder_id"]),
        "kubernetes_versions": lambda: cli(plan, "managed-kubernetes", "list-versions"),
        "quota_services": lambda: cli(plan, "quota-manager", "quota-limit", "list-services",
                                      "--resource-type", "resource-manager.cloud"),
        "billing_prices": lambda: billing_account_and_skus(plan, token),
        # One ConsumptionCore request: the service permits one request/minute/IP.
        "account_usage_since_grant_screenshot": lambda: cli(plan, "billing", "consumption-core",
            "get-billing-account-usage-report", plan["billing_account_id"],
            "--start-date", "2026-10-03T00:00:00Z", "--end-date", now.strftime("%Y-%m-%dT23:59:59Z"),
            "--aggregation-period", "day", timeout=150),
    }
    for service in ("compute", "vpc", "managed-kubernetes", "container-registry"):
        queries["quota_" + service] = lambda s=service: cli(plan, "quota-manager", "quota-limit", "list",
            "--service", s, "--resource-type", "resource-manager.cloud", "--resource-id", plan["cloud_id"])
    for service, kind in (("compute", "instance"), ("compute", "disk"), ("vpc", "network"),
                          ("managed-kubernetes", "cluster"), ("container", "registry")):
        queries[service + "_" + kind] = lambda s=service, k=kind: cli(plan, s, k, "list")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): key for key, fn in queries.items()}
        for future in as_completed(futures):
            key = futures[future]
            try:
                value = future.result()
                save(args.output / (key + ".json"), value)
                report["observations"][key] = value if key != "billing_prices" else {
                    "account": value["account"], "sku_count": len(value["skus"]),
                    "source_file": "billing_prices.json"}
            except Exception as exc:
                report["errors"][key] = type(exc).__name__ + ": " + str(exc)[:500]
    report["quota_checks"] = assess_quotas(report["observations"], zone=plan["zone"])
    report["remaining_review"] = [
        "Select an available Kubernetes version and verify all reported quota checks.",
        "Select current RUB SKU tiers for Ice Lake CPU/RAM, SSD, IPv4, zonal master and registry.",
        "Compute a conservative budget from account-wide costs, not the folder alone.",
        "Grant screenshot is historical; account balance is not the remaining grant.",
        "Freeze the cloud pilot plan and provision a bounded window only after those checks."]
    save(args.output / "preflight.json", report)
    print(json.dumps({"read_only": True, "errors": report["errors"],
                      "quota_checks": report["quota_checks"], "provisioning_ready": False}, indent=2))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
