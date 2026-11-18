import pytest

from h2.cloud_analysis import analyze
from h2.cloud_costs import Ledger, Rates
from h2.cloudru_main import matrix
from h2.cloudru_reboot_recovery import replay_ledger, resume_scope


def completed_primary():
    specs = matrix()
    plan = {"trials": specs, "confirmatory": False,
        "continuation": {"completed_trial_ids": [s["id"] for s in specs[:12]]}}
    rows = [{"trial": s["id"], "valid": True, "lifecycle_complete": True} for s in specs[12:24]]
    directories = [r["trial"] for r in rows] + ["main-short-fixed"]
    return plan, rows, directories


def test_recovery_scope_excludes_every_completed_primary_workload():
    plan, rows, directories = completed_primary()
    remaining = resume_scope(plan, rows, directories)
    assert [s["id"] for s in remaining] == [s["id"] for s in matrix()[24:]]
    assert all(s["analysis_group"] != "primary" for s in remaining)


@pytest.mark.parametrize("change", ["missing_primary", "duplicate_primary", "invalid_primary", "later_started", "unknown_trial"])
def test_recovery_refuses_ambiguous_or_changed_execution(change):
    plan, rows, directories = completed_primary()
    if change == "missing_primary":
        rows.pop()
    elif change == "duplicate_primary":
        rows.append(rows[-1])
    elif change == "invalid_primary":
        rows[0]["valid"] = False
    elif change == "later_started":
        directories.append("main-long-fixed")
    else:
        directories.append("main-unplanned")
    with pytest.raises(ValueError):
        resume_scope(plan, rows, directories)


def observation_points():
    rates = {"vcpu": 2, "ram_gib": 0, "network_ssd_gib": 1, "active_public_ipv4": 0}
    ledger = Ledger(Rates.from_dict(rates))
    points = []
    for at in (10, 20):
        point = {"at": at, "clock": {"basis": "coordinator_utc", "inventory_started_at": at - 1},
            "instances": [{"id": "vm", "created_at": 0, "cores": 2, "memory_gib": 4,
                           "public_ip": False, "status": "RUNNING"}],
            "disks": [{"id": "disk", "created_at": 0, "type": "network-ssd", "size_gib": 40}]}
        ledger.observe(at, observed_from=at - 1, instances=point["instances"], disks=point["disks"])
        point["cost"] = ledger.report()
        points.append(point)
    return rates, points


def test_ledger_resume_keeps_full_creation_to_retirement_cost_and_gap():
    rates, points = observation_points()
    restored = replay_ledger(points, rates)
    uninterrupted = Ledger(Rates.from_dict(rates))
    for point in points:
        uninterrupted.observe(point["at"], observed_from=point["clock"]["inventory_started_at"],
                              instances=point["instances"], disks=point["disks"])
    for ledger in (restored, uninterrupted):
        # Same owned resources after a long missing-observation interval.
        ledger.observe(1000, observed_from=999, instances=points[-1]["instances"], disks=points[-1]["disks"])
        ledger.observe(1010, observed_from=1009, instances=[], disks=[])
    assert restored.report() == uninterrupted.report()
    assert restored.report()["lifecycle_complete"]
    assert restored.report()["estimated_rub_lower"] > points[-1]["cost"]["estimated_rub_upper"]


@pytest.mark.parametrize("change", ["backwards", "cost_changed", "local_clock"])
def test_ledger_resume_rejects_inconsistent_evidence(change):
    rates, points = observation_points()
    if change == "backwards":
        points.reverse()
    elif change == "cost_changed":
        points[-1]["cost"]["estimated_rub_upper"] += 1
    else:
        points[0]["clock"]["basis"] = "client_wall"
    with pytest.raises(ValueError):
        replay_ledger(points, rates)


def test_interrupted_secondary_control_cannot_change_primary_conclusion():
    plan = {"trials": matrix(), "bootstrap_seed": 20261005, "bootstrap_samples": 100,
            "required_on_time_rate": .95, "on_time_noninferiority_margin": .02}
    rows = [{"trial": s["id"], "valid": True, "lifecycle_complete": True,
        "accepted": 24, "correct": 24, "on_time": 24,
        "cost_lower_rub": 1, "cost_upper_rub": 1.01} for s in plan["trials"][:24]]
    before = analyze(plan, rows, bootstrap_samples=100)
    after = analyze(plan, rows + [{"trial": "main-short-fixed", "valid": False,
        "lifecycle_complete": True, "observation_interrupted": True}], bootstrap_samples=100)
    assert before == after
