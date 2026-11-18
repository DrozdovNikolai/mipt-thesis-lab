import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from h2 import cloudru_autopilot as autopilot
from h2.cloudru_window import change_window


def test_failed_baseline_never_opens_main_window_and_still_attempts_cleanup(tmp_path, monkeypatch):
    (tmp_path / "pilot-v2").mkdir()
    (tmp_path / "pilot-v2/summary.json").write_text(json.dumps({"cold_probes": 3, "automatic_zero_observed": True}))
    monkeypatch.setattr(autopilot, "process_is", lambda *args: False)
    monkeypatch.setattr(autopilot, "Cloud", lambda *args: SimpleNamespace())
    monkeypatch.setattr(autopilot, "billing", lambda *args: {"preliminary_rub_before_grant": 10})
    windows = []
    monkeypatch.setattr(autopilot, "change_window", lambda *args, **kwargs: windows.append(kwargs["phase"]))
    def failed_tuning(*args):
        (tmp_path / "tuning").mkdir()
        (tmp_path / "tuning/summary.json").write_text(json.dumps({"passed": False}))
    monkeypatch.setattr(autopilot, "observed_phase", failed_tuning)
    calls = []
    monkeypatch.setattr(autopilot, "phase", lambda run, module, *args: calls.append((module, args)))
    monkeypatch.setattr(autopilot, "update_index", lambda *args: None)
    autopilot.run(tmp_path, 123)
    assert windows == ["tuning"]
    assert calls == [("h2.cloudru_finish", ("finish",)), ("h2.cloudru_report", ())]
    assert json.loads((tmp_path / "autopilot-status.json").read_text())["status"] == "failed_with_evidence"


def test_phase_deadline_cannot_outlive_the_independent_guard_key_margin():
    cloud = SimpleNamespace(state={"created_at": "2026-10-14T17:00:00+00:00"}, kube=Mock())
    with pytest.raises(ValueError, match="expiry"):
        change_window(cloud, deadline="2026-10-15T17:00:00+00:00", phase="tuning")
    cloud.kube.assert_not_called()
