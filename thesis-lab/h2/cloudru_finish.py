"""Audit retained databases, export evidence, then remove only owned resources."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

from h2.cloud_trial import verify_backup
from h2.cloudru_access import load_profile
from h2.cloudru_billing import consumption
from h2.cloudru_monitoring import export
from h2.cloudru_ops import Cloud, save, stamp
from h2.cloudru_trial import nodes


def audit_backups(run):
    audits = []
    for directory in sorted((run / "trials").glob("*")):
        submitted = directory / "submitted.json"
        if not submitted.exists():
            continue
        snapshot = json.loads((directory / "snapshot.json").read_text())
        expected = [x["id"] for x in json.loads(submitted.read_text())]
        audit = verify_backup(directory / "queue.sqlite", snapshot=snapshot, expected_ids=expected)
        previous = json.loads((directory / "backup-verified.json").read_text())
        if audit["sha256"] != previous["sha256"]:
            raise ValueError("Backup changed after verification: " + directory.name)
        audits.append({"trial": directory.name, **audit})
    save(run / "final-backup-audit.json", {"at": stamp(), "passed": True, "trials": audits})
    return audits


def billing(cloud, suffix):
    query = {"project_ids": cloud.client.project_id,
        "start_date": datetime.fromisoformat(cloud.state.get("budget_started_at", cloud.state["created_at"])).replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
        "end_date": stamp(), "page_filter.limit": 100, "page_filter.page": 1}
    snapshot = consumption(cloud.client, query)
    result = {"at": stamp(), "query": query, "consumptions": snapshot["consumptions"],
        "pages": snapshot["pages"], "preliminary_rub_before_grant": snapshot["preliminary_rub"],
        "not_final_billing_or_grant_balance": True}
    save(cloud.run / ("billing-" + suffix + ".json"), result)
    return result


def scan_secrets(run, runtime):
    profile = load_profile()
    protected = [profile["key_id"], profile["key_secret"], (runtime / "api-token").read_text().strip()]
    guard = json.loads((runtime / "guard-profile.json").read_text())
    protected += [guard["key_id"], guard["key_secret"]]
    needles = [s.encode() for s in protected if s]
    width = max(map(len, needles))
    matches = []
    checked = 0
    for path in sorted(run.rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise ValueError("Do not archive an unexpected symlink: " + str(path.relative_to(run)))
        checked += 1
        tail = b""
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                data = tail + chunk
                if any(value in data for value in needles):
                    matches.append(str(path.relative_to(run)))
                    break
                tail = data[-width:]
    if matches:
        raise ValueError("Private credential material detected in archive files: " + ", ".join(matches))
    return {"passed": True, "files_checked": checked, "known_private_values_checked": len(needles),
            "note": "Exact-value scan for owner/guard keys and runtime API token; not a universal secret detector."}


def finish(cloud):
    audits = audit_backups(cloud.run)
    # Auxiliary telemetry must never prevent deletion of already backed-up
    # resources. Preserve missing-data markers for later reconciliation.
    optional_evidence(cloud, "final-native-export", lambda: export(cloud))
    optional_evidence(cloud, "billing-before-cleanup", lambda: billing(cloud, "before-cleanup"))
    known_vms, known_disks = set(), set()
    for path in (cloud.run / "trials").glob("*/resource-identities.json"):
        record = json.loads(path.read_text())
        known_vms.update(record["vm_ids"])
        known_disks.update(record["disk_ids"])
    if not cloud.state["cluster"].get("deleted_at"):
        system = nodes(cloud.client, cloud.state["groups"]["system"]["id"])
        known_vms.update(x["machine"]["id"] for x in system)
    for disk in cloud.client.compute_list("disks")["items"]:
        if any(v["id"] in known_vms for v in disk["vms"]):
            known_disks.add(disk["id"])
    diagnostic = cloud.run / "zero-selector-diagnostic-ownership.json"
    if diagnostic.exists():
        record = json.loads(diagnostic.read_text())
        known_vms.update(record["vm_ids"])
        known_disks.update(record["disk_ids"])
    save(cloud.run / "cleanup-owned-inventory.json", {"at": stamp(), "vm_ids": sorted(known_vms), "disk_ids": sorted(known_disks)})
    # The watchdog remains a fallback. Complete this normal path with several
    # guarded minutes left so it is not racing another resource writer.
    cloud.stop()
    cloud.cleanup()
    for _ in range(60):
        remaining_vms = [v["id"] for v in cloud.client.compute_list("vms")["items"] if v["id"] in known_vms]
        remaining_disks = [d["id"] for d in cloud.client.compute_list("disks")["items"] if d["id"] in known_disks]
        if not remaining_vms and not remaining_disks:
            break
        time.sleep(5)
    report = {"at": stamp(), "remaining_owned_vms": remaining_vms, "remaining_owned_disks": remaining_disks,
        "complete": not remaining_vms and not remaining_disks,
        "verified_trial_backups": len(audits), "dashboard_retained": (cloud.run / "dashboard-created.json").exists(),
        "registry_note": "Registry removal can have delayed storage billing; final invoice remains separate."}
    save(cloud.run / "cleanup-inventory-verified.json", report)
    optional_evidence(cloud, "billing-after-cleanup", lambda: billing(cloud, "after-cleanup"))
    if not report["complete"]:
        raise RuntimeError("Owned resources remain after cleanup")
    return report


def optional_evidence(cloud, name, collect):
    try:
        result = collect()
    except Exception as error:
        save(cloud.run / (name + "-unavailable.json"), {"at": stamp(), "available": False,
            "error_type": type(error).__name__, "http_status": getattr(error, "status", None),
            "reconciliation_required": True})
        return None
    save(cloud.run / (name + ".json"), result)
    return result


def seal(cloud):
    if not json.loads((cloud.run / "cleanup-inventory-verified.json").read_text())["complete"]:
        raise ValueError("Reconcile cleanup before sealing")
    result = scan_secrets(cloud.run, cloud.runtime)
    save(cloud.run / "secret-scan.json", {"at": stamp(), **result})
    rows = []
    for path in sorted(cloud.run.rglob("*")):
        if not path.is_file() or path.name in {"SHA256SUMS", "sealed.json"}:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(digest + "  " + str(path.relative_to(cloud.run)))
    manifest = cloud.run / "SHA256SUMS"
    manifest.write_text("\n".join(rows) + "\n")
    save(cloud.run / "sealed.json", {"at": stamp(), "files": len(rows),
        "sha256_manifest": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "note": "No further writes to this run; later Billing snapshots belong in a separate reconciliation directory."})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["finish", "seal"])
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    {"finish": finish, "seal": seal}[args.action](Cloud(args.run))
