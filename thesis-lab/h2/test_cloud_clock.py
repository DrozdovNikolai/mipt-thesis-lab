"""Regressions for the retained 2026-10-15 WSL wall-clock discontinuity."""
from decimal import Decimal
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from h2.cloud_costs import Ledger, Rates
from h2.cloud_trial import Trial


def trial_for_clock_test(tmp_path, server_times):
    trial = Trial.__new__(Trial)
    trial.output, trial.ns, trial.phase = tmp_path, "test", "clock-regression"
    trial.observation_lock = threading.Lock()
    trial.api = Mock(side_effect=[{"at": value} for value in server_times])
    trial.cloud_inventory = Mock(return_value=([], [], []))
    trial.cloud = SimpleNamespace(kube=Mock(side_effect=lambda *a: json.dumps(
        {"spec": {"replicas": 0}} if "deployment" in a else {"items": []})))
    trial.ledger = Ledger(Rates(*(Decimal(1) for _ in range(4))))
    return trial


def test_local_clock_stepping_back_does_not_reorder_cloud_observations(tmp_path):
    trial = trial_for_clock_test(tmp_path, [100, 102, 110, 112])
    with patch("h2.cloud_trial.time.time", side_effect=[10000, 9000]):
        first, second = trial.observe(), trial.observe()
    assert (first["at"], second["at"]) == (102, 112)
    assert second["clock"]["client_wall_at"] < first["clock"]["client_wall_at"]
    assert second["clock"]["inventory_started_at"] == 110
    assert trial.ledger.previous_at == 112


def test_remote_clock_step_remains_a_validation_failure(tmp_path):
    trial = trial_for_clock_test(tmp_path, [100, 102, 101, 103])
    trial.observe()
    with pytest.raises(ValueError, match="remote clock"):
        trial.observe()
    assert len((tmp_path / "timeline.jsonl").read_text().splitlines()) == 1


def test_horizon_uses_admission_clock_even_when_local_clock_is_in_the_future(tmp_path):
    trial = trial_for_clock_test(tmp_path, [100, 120, 1810])
    with patch("h2.cloud_trial.time.time", side_effect=AssertionError("Local wall clock must not control horizon")):
        assert trial.seconds_until(1800) == 1700
        assert trial.seconds_until(1800) == 1680
        assert trial.seconds_until(1800) == 0
