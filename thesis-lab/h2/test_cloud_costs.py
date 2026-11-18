from decimal import Decimal

import pytest

from h2.cloud_costs import Ledger, Rates, task_summary, verify_resource_coverage


def rates():
    return Rates(Decimal("1"), Decimal("0.5"), Decimal("0.01"), Decimal("0.25"))


def vm():
    return {"id": "vm", "created_at": 0, "cores": 4, "memory_gib": 8,
            "public_ip": True, "status": "RUNNING"}


def disk():
    return {"id": "disk", "created_at": 0, "size_gib": 40, "type": "network-ssd"}


def test_disk_keeps_accruing_after_vm_is_deleted_and_missing_polls_widen_bounds():
    ledger = Ledger(rates())
    ledger.observe(3600, instances=[vm()], disks=[disk()])
    ledger.observe(3660, instances=[], disks=[disk()])
    assert not ledger.report()["lifecycle_complete"]
    # A failed poll at 3700 is NOT an empty inventory. Next successful poll is later.
    ledger.observe(7200, instances=[], disks=[disk()])
    ledger.observe(7260, instances=[], disks=[])
    report = ledger.report()
    assert report["lifecycle_complete"]
    assert report["estimated_rub_lower"] == pytest.approx(8.25 + 0.8)
    assert report["estimated_rub_upper"] == pytest.approx(8.25 * 3660 / 3600 + 0.4 * 7260 / 3600)


def test_no_resources_cannot_be_reported_as_a_completed_free_trial():
    ledger = Ledger(rates())
    ledger.observe(100, instances=[], disks=[])
    assert not ledger.report()["lifecycle_complete"]


def test_stopped_vm_is_not_silently_charged_cpu_and_failed_poll_is_atomic():
    ledger = Ledger(rates())
    ledger.observe(100, instances=[vm()], disks=[disk()])
    before = ledger.report()
    with pytest.raises(ValueError, match="interval accounting"):
        ledger.observe(200, instances=[{**vm(), "status": "STOPPED"}], disks=[])
    assert ledger.report() == before


def test_resource_reappearing_after_absence_is_not_treated_as_two_free_intervals():
    ledger = Ledger(rates())
    ledger.observe(100, instances=[vm()], disks=[])
    ledger.observe(200, instances=[], disks=[])
    with pytest.raises(ValueError, match="resurrected"):
        ledger.observe(300, instances=[vm()], disks=[])


def test_unfinished_wrong_unverified_and_late_results_stay_in_denominator():
    good = {"id": "good", "state": "done", "expected_sha": "abc", "result_sha": "abc",
            "accepted_at": 0, "first_started_at": 5, "completed_at": 10, "deadline_at": 15}
    tasks = [good, {**good, "id": "late", "completed_at": 20},
             {**good, "id": "wrong", "result_sha": "wrong"},
             {**good, "id": "unverified", "expected_sha": None},
             {**good, "id": "pending", "state": "queued", "first_started_at": None}]
    result = task_summary({"tasks": tasks})
    assert (result["accepted"], result["completed"], result["correct"], result["on_time"]) == (5, 4, 2, 1)
    assert result["on_time_rate"] == 0.2
    assert result["unfinished"] == 1
    assert result["incorrect_or_unverified"] == 2


def test_missing_expected_results_are_not_counted_as_correct():
    task = {"id": "t", "state": "done", "result_sha": None, "expected_sha": None,
            "accepted_at": 0, "first_started_at": 1, "completed_at": 2, "deadline_at": 10}
    assert task_summary({"tasks": [task]})["correct"] == 0


def test_discovered_but_unmeasured_vm_is_not_a_free_resource():
    identity = {"vm_ids": ["observed", "missed"], "disk_ids": ["disk"]}
    cost = {"resources": [{"kind": "instance", "id": "observed"}, {"kind": "disk", "id": "disk"}]}
    with pytest.raises(ValueError, match="coverage"):
        verify_resource_coverage(identity, cost)
    cost["resources"].append({"kind": "instance", "id": "missed"})
    assert verify_resource_coverage(identity, cost)


def test_remote_inventory_bracket_widens_cost_bounds_without_inventing_precision():
    ledger = Ledger(rates())
    ledger.observe(105, observed_from=100, instances=[vm()], disks=[disk()])
    ledger.observe(205, observed_from=200, instances=[], disks=[])
    result = ledger.report()
    assert result["estimated_rub_lower"] == pytest.approx((8.25 + .4) * 100 / 3600)
    assert result["estimated_rub_upper"] == pytest.approx((8.25 + .4) * 205 / 3600)
    assert result["lifecycle_complete"]


def test_resource_created_during_inventory_does_not_have_negative_lifetime():
    ledger = Ledger(rates())
    ledger.observe(105, observed_from=100, instances=[{**vm(), "created_at": 103}], disks=[])
    assert ledger.report()["estimated_rub_lower"] == 0
    ledger.observe(110, observed_from=108, instances=[], disks=[])
    assert ledger.report()["estimated_rub_upper"] == pytest.approx(8.25 * 7 / 3600)


def test_backwards_remote_clock_still_rejects_the_complete_inventory_atomically():
    ledger = Ledger(rates())
    ledger.observe(105, observed_from=100, instances=[vm()], disks=[])
    before = ledger.report()
    with pytest.raises(ValueError, match="overlap or remote clock"):
        ledger.observe(110, observed_from=104, instances=[], disks=[])
    assert ledger.report() == before
