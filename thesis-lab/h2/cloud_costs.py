"""Resource-time bounds for H2; estimates are never presented as Billing charges.

Each observation is a COMPLETE inventory for one isolated trial's node group,
not a delta and not the complete user's cloud. Failed polls are not observations.
VM and disk inventories are separate: an orphan disk must keep accruing cost.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal
import math


def seconds(value):
    result = (datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
              if isinstance(value, str) else float(value))
    if not math.isfinite(result):
        raise ValueError("Non-finite timestamp")
    return result


@dataclass(frozen=True)
class Rates:
    vcpu: Decimal
    ram_gib: Decimal
    ssd_gib: Decimal
    public_ipv4: Decimal

    @classmethod
    def from_dict(cls, values):
        rates = cls(*(Decimal(str(values[key])) for key in
                      ("vcpu", "ram_gib", "network_ssd_gib", "active_public_ipv4")))
        if any(not v.is_finite() or v < 0 for v in asdict(rates).values()):
            raise ValueError("Invalid RUB hourly rate")
        return rates


class Ledger:
    def __init__(self, rates: Rates):
        self.rates = rates
        self.resources = {}
        self.previous_at = None

    def observe(self, at, *, instances, disks, observed_from=None):
        """Rows use explicit normalized fields, never infer empty lists on failure.

        instance: id, created_at, cores, memory_gib, public_ip, status
        disk: id, created_at, size_gib, type
        A workload VM is not stopped/restarted between creation and deletion.
        Reject a STOPPED VM rather than charging its CPU as if it were running.
        """
        at = seconds(at)
        lower = at if observed_from is None else seconds(observed_from)
        if lower > at:
            raise ValueError("Inventory observation interval runs backwards")
        if self.previous_at is not None and at <= self.previous_at:
            raise ValueError("Inventories must be strictly chronological")
        if self.previous_at is not None and lower < self.previous_at:
            raise ValueError("Inventory observation intervals overlap or remote clock moved backwards")
        rows = [("instance", x) for x in instances] + [("disk", x) for x in disks]
        present = set()
        prepared = []
        for kind, row in rows:
            key = (kind, row["id"])
            if key in present:
                raise ValueError("Duplicate resource in inventory")
            present.add(key)
            start = seconds(row["created_at"])
            if start > at:
                raise ValueError("Resource created after inventory timestamp")
            if kind == "instance":
                if row["status"] not in {"PROVISIONING", "STARTING", "RUNNING", "DELETING"}:
                    raise ValueError("VM lifecycle needs interval accounting: " + row["status"])
                if row["cores"] <= 0 or row["memory_gib"] <= 0:
                    raise ValueError("Invalid VM allocation")
                hourly = (self.rates.vcpu * Decimal(str(row["cores"]))
                          + self.rates.ram_gib * Decimal(str(row["memory_gib"]))
                          + self.rates.public_ipv4 * int(row["public_ip"]))
            else:
                if row["type"] != "network-ssd" or row["size_gib"] <= 0:
                    raise ValueError("Unsupported disk allocation")
                hourly = self.rates.ssd_gib * Decimal(str(row["size_gib"]))
            previous = self.resources.get(key)
            if previous and (previous["gone_by"] is not None or previous["created_at"] != start
                             or previous["hourly"] != hourly):
                raise ValueError("Resource resurrected or allocation changed")
            prepared.append((key, start, hourly))
        # Validate the complete poll before changing accounting state.
        for key, start, hourly in prepared:
            entry = self.resources.setdefault(key, {"created_at": start, "hourly": hourly,
                                                    "last_seen": max(start, lower), "gone_by": None})
            # An inventory is not instantaneous. Its server-clock bracket
            # bounds the last positive observation as well as the first absence.
            entry["last_seen"] = max(start, lower)
            entry["last_seen_upper"] = at
        for key, entry in self.resources.items():
            if key not in present and entry["gone_by"] is None:
                entry["gone_by"] = at
        self.previous_at = at

    def report(self):
        rows, low, high = [], Decimal(0), Decimal(0)
        for (kind, identifier), entry in sorted(self.resources.items()):
            low_seconds = entry["last_seen"] - entry["created_at"]
            high_seconds = (entry["gone_by"] if entry["gone_by"] is not None
                            else entry["last_seen_upper"]) - entry["created_at"]
            lo = Decimal(str(low_seconds)) * entry["hourly"] / 3600
            hi = Decimal(str(high_seconds)) * entry["hourly"] / 3600
            low += lo
            high += hi
            rows.append({"kind": kind, "id": identifier, "created_at": entry["created_at"],
                         "last_seen_at": entry["last_seen"], "last_seen_upper_at": entry["last_seen_upper"],
                         "first_absent_at": entry["gone_by"],
                         "rate_rub_per_hour": float(entry["hourly"]),
                         "estimated_rub_lower": float(lo), "estimated_rub_upper": float(hi),
                         "lifecycle_complete": entry["gone_by"] is not None})
        return {"currency": "RUB", "basis": "resource_time_estimate_not_billing",
                "estimated_rub_lower": float(low), "estimated_rub_upper": float(high),
                "lifecycle_complete": bool(rows) and all(r["lifecycle_complete"] for r in rows),
                "resources": rows,
                "limitations": ["Creation-to-deletion allocation estimate, including provisioning.",
                    "Observation and deletion times are bounded by successful complete inventory poll intervals.",
                    "Resources missed by every poll require reconciliation with node-group operations and Billing IDs.",
                    "Master, system node, registry and Monitoring are shared overhead, reported separately.",
                    "Actual resource Billing charges must be joined by these resource IDs."]}


def task_summary(snapshot):
    """Errors, unverified results and unfinished work stay in the SLO denominator."""
    tasks = snapshot["tasks"]
    if len({t["id"] for t in tasks}) != len(tasks):
        raise ValueError("Duplicate logical task")
    completed = [t for t in tasks if t["state"] == "done"]
    correct = [t for t in completed if t.get("expected_sha")
               and t.get("result_sha") == t["expected_sha"]]
    on_time = [t for t in correct if t["completed_at"] <= t["deadline_at"]]
    return {"accepted": len(tasks), "completed": len(completed), "correct": len(correct),
            "on_time": len(on_time), "unfinished": len(tasks) - len(completed),
            "incorrect_or_unverified": len(completed) - len(correct),
            "on_time_rate": len(on_time) / len(tasks) if tasks else None,
            "processing_seconds": [t["completed_at"] - t["accepted_at"] for t in correct],
            "start_latency_seconds": [t["first_started_at"] - t["accepted_at"] for t in tasks
                                      if t.get("first_started_at") is not None]}


def verify_resource_coverage(identities, cost):
    """A discovered VM must not disappear without entering the cost ledger."""
    for kind, field in (("instance", "vm_ids"), ("disk", "disk_ids")):
        discovered = set(identities[field])
        measured = {x["id"] for x in cost["resources"] if x["kind"] == kind}
        if discovered != measured:
            raise ValueError("Incomplete cost coverage for " + kind + ": discovered and measured IDs differ")
    return True
