import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from h2.cloudru_main import budget_check, execution_trials, matrix, open_window, freeze
from h2.cloudru_preflight import CloudruError


def test_primary_matrix_has_independent_pairs_and_balances_order_within_scenario():
    rows = matrix()
    primary = [x for x in rows if x["analysis_group"] == "primary"]
    assert len(rows) == 29 and len(primary) == 24
    assert len({x["id"] for x in rows}) == len(rows)
    assert sum(x["tasks"] for x in primary) == 576
    for scenario in ("short", "long", "mixed"):
        pairs = []
        for block in range(4):
            indexes = [i for i, x in enumerate(primary) if x["scenario"] == scenario and x["block"] == block]
            assert len(indexes) == 2 and indexes[1] == indexes[0] + 1
            pairs.append([primary[i]["variant"] for i in indexes])
        assert pairs.count(["count", "work"]) == pairs.count(["work", "count"]) == 2
    assert all(not x["fault"] for x in primary)


def test_budget_reserves_unreported_usage_and_cleanup_before_allowing_next_trial(tmp_path):
    (tmp_path / "main").mkdir()
    cloud = SimpleNamespace(run=tmp_path, state={"created_at": "2026-10-14T17:00:00+00:00"},
        plan={"estimated_six_hour_total_before_variable_usage": 150},
        client=SimpleNamespace(project_id="p", request=Mock(return_value={"consumptions": [{"amount_nds": 430}]})))
    with pytest.raises(RuntimeError, match="Budget reserve"):
        budget_check(cloud, "main-example")
    saved = json.loads((tmp_path / "main/billing-before-main-example.json").read_text())
    assert saved["reserve_rub"] == 100 and not saved["admission_allowed"]


def test_crossing_the_planning_estimate_does_not_interrupt_authorized_work(tmp_path):
    (tmp_path / "main").mkdir()
    (tmp_path / "budget-policy.json").write_text(json.dumps({"planning_target_rub": 500, "spending_ceiling_rub": 1000}))
    cloud = SimpleNamespace(run=tmp_path, state={"created_at": "2026-10-14T17:00:00+00:00"},
        plan={"estimated_six_hour_total_before_variable_usage": 150},
        client=SimpleNamespace(project_id="p", request=Mock(return_value={"consumptions": [{"amount_nds": 550}]})))
    result = budget_check(cloud, "over-estimate")
    assert result["planning_target_exceeded"] and result["admission_allowed"]
    assert result["spending_ceiling_rub"] == 1000
    cloud.client.request.return_value = {"consumptions": [{"amount_nds": 950}]}
    with pytest.raises(RuntimeError, match="Budget reserve"):
        budget_check(cloud, "actual-ceiling")


def test_explicit_monitor_only_policy_records_spend_without_a_budget_stop(tmp_path):
    (tmp_path / "main").mkdir()
    (tmp_path / "budget-policy.json").write_text(json.dumps({"planning_target_rub": 500, "spending_ceiling_rub": None}))
    cloud = SimpleNamespace(run=tmp_path, state={"created_at": "2026-10-14T17:00:00+00:00"},
        plan={"estimated_six_hour_total_before_variable_usage": 150},
        client=SimpleNamespace(project_id="p", request=Mock(return_value={"consumptions": [{"amount_nds": 600}]})))
    result = budget_check(cloud, "monitor-only")
    assert result["planning_target_exceeded"] and result["admission_allowed"]
    assert result["spending_ceiling_rub"] is None and result["preliminary_rub"] == 600


@pytest.mark.parametrize("ceiling", [None, 1000])
def test_billing_transport_failure_is_nonblocking_only_without_a_monetary_ceiling(tmp_path, ceiling):
    (tmp_path / "main").mkdir()
    (tmp_path / "budget-policy.json").write_text(json.dumps({"planning_target_rub": 500, "spending_ceiling_rub": ceiling}))
    cloud = SimpleNamespace(run=tmp_path, state={"created_at": "2026-10-14T17:00:00+00:00"},
        plan={"estimated_six_hour_total_before_variable_usage": 150},
        client=SimpleNamespace(project_id="p", request=Mock(side_effect=CloudruError("organization", None, {}))))
    if ceiling is None:
        result = budget_check(cloud, "outage")
        assert result["admission_allowed"]
    else:
        with pytest.raises(RuntimeError, match="explicit spending ceiling"):
            budget_check(cloud, "outage")
    saved = json.loads((tmp_path / "main/billing-before-outage.json").read_text())
    assert saved["billing_available"] is False
    assert saved["preliminary_rub"] is None and saved["planning_target_exceeded"] is None
    assert saved["reconciliation_required"] and saved["admission_allowed"] == (ceiling is None)


def test_continuation_executes_only_the_unstarted_original_suffix():
    trials = matrix()
    plan = {"confirmatory": False, "trials": trials,
        "continuation": {"completed_trial_ids": [x["id"] for x in trials[:12]]}}
    remaining = execution_trials(plan)
    assert remaining == trials[12:]
    assert len([x for x in remaining if x["analysis_group"] == "primary"]) == 12
    assert not set(x["id"] for x in remaining).intersection(plan["continuation"]["completed_trial_ids"])


@pytest.mark.parametrize("prefix_indexes", [[0], list(range(11)), list(range(2, 14))])
def test_continuation_rejects_a_split_pair_or_selected_subset(prefix_indexes):
    trials = matrix()
    plan = {"confirmatory": False, "trials": trials,
        "continuation": {"completed_trial_ids": [trials[i]["id"] for i in prefix_indexes]}}
    with pytest.raises(ValueError, match="paired block|exact primary prefix"):
        execution_trials(plan)


@pytest.mark.parametrize("billing_available", [True, False])
def test_main_plan_can_freeze_an_explicit_monitor_only_budget(tmp_path, billing_available):
    (tmp_path / "tuning").mkdir()
    (tmp_path / "pilot").mkdir()
    (tmp_path / "tuning/summary.json").write_text(json.dumps({"passed": True, "results": [],
        "selected": {"config": {"target_queue": 12, "cold_start_seconds": 572}, "slo_seconds": 900}}))
    (tmp_path / "pilot/references.json").write_text("{}")
    (tmp_path / "budget-policy.json").write_text(json.dumps({"planning_target_rub": 500, "spending_ceiling_rub": None}))
    cloud = SimpleNamespace(run=tmp_path, state={"created_at": "2026-10-14T17:00:00+00:00", "published_image": "frozen"},
        plan={"estimated_six_hour_total_before_variable_usage": 150},
        client=SimpleNamespace(project_id="p", request=Mock(return_value={"consumptions": []})))
    if not billing_available:
        cloud.client.request.side_effect = CloudruError("organization", None, {})
    result = freeze(cloud)
    assert result["total_run_budget_rub"] is None
    assert result["planning_target_rub"] == 500
    assert "денежная остановка отключена" in (tmp_path / "main/PLAN.md").read_text()
    assert (result["pre_main_preliminary_billing_rub"] is not None) == billing_available


def test_guard_window_does_not_patch_an_unexpected_cluster(tmp_path):
    old = "2026-10-14T23:00:00+00:00"
    cloud = SimpleNamespace(run=tmp_path, state={"created_at": "2026-10-14T17:00:00+00:00", "deadline": old, "groups": {}, "cluster": {"id": "owned"}},
        kube=Mock(return_value=json.dumps({"spec": {"jobTemplate": {"spec": {"template": {"spec": {
            "containers": [{"name": "guard", "env": [{"name": "CLUSTER_ID", "value": "other"},
                {"name": "DEADLINE", "value": old}]}]}}}}}})))
    with patch("h2.cloudru_main.check_frozen", return_value={"deadline": "2026-10-15T12:00:00+00:00"}):
        with pytest.raises(ValueError, match="guard identity"):
            open_window(cloud)
    assert cloud.kube.call_count == 1 and cloud.state["deadline"] == old


def test_both_guards_are_changed_only_after_remote_readback(tmp_path):
    (tmp_path / "main").mkdir()
    old, new = "2026-10-14T23:00:00+00:00", "2026-10-15T12:00:00+00:00"
    def cron(deadline):
        return json.dumps({"spec": {"jobTemplate": {"spec": {"template": {"spec": {"containers": [{"name": "guard",
            "env": [{"name": "CLUSTER_ID", "value": "owned"}, {"name": "DEADLINE", "value": deadline}]}]}}}}}})
    cloud = SimpleNamespace(run=tmp_path, state={"created_at": "2026-10-14T17:00:00+00:00", "deadline": old, "groups": {}, "cluster": {"id": "owned"},
        "guard_stop_verified_at": "prior-real-stop"}, kube=Mock(side_effect=[cron(old), "patched", cron(new)]), record=Mock())
    with patch("h2.cloudru_main.check_frozen", return_value={"deadline": new}):
        open_window(cloud)
    assert cloud.state["deadline"] == new and cloud.record.call_count == 1
    proof = json.loads((tmp_path / "main/guard-window.json").read_text())
    assert proof["remote_guard_readback_verified"] and proof["old_deadline"] == old


def test_historical_accounting_failure_blocks_baseline_acceptance(tmp_path):
    (tmp_path / "tuning").mkdir()
    (tmp_path / "tuning/summary.json").write_text(json.dumps({"passed": True, "results": [{"trial": "bad"}]}))
    directory = tmp_path / "trials/bad"
    directory.mkdir(parents=True)
    (directory / "observation-errors.jsonl").write_text(json.dumps({"error": "Unexpected VM state requires separate accounting: stopped"}) + "\n")
    with pytest.raises(ValueError, match="invariant violation"):
        freeze(SimpleNamespace(run=tmp_path))
    assert not (tmp_path / "main").exists()
