import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from h2 import cloudru_recovery as recovery
from h2.cloudru_main import budget_check
from h2.cloudru_finish import audit_backups


def source_archive(tmp_path, *, clean=True):
    source = tmp_path / "original"
    source.mkdir()
    data = {"cleanup-inventory-verified.json": {"complete": clean},
        "state.json": {"project_id": "p", "created_at": "2026-10-14T17:37:00+00:00"},
        "main/plan.json": {"config": {"target_queue": 12}, "slo_seconds": 900},
        "main/frozen.json": {"plan_sha256": "prior-plan"},
        "main/rows.json": [{"trial": "original-primary-trial"}],
        "tuning/summary.json": {"passed": True, "selected": {"config": {"target_queue": 12}, "slo_seconds": 900}},
        "pending-v2-published.json": {"local_image": "sha256:unchanged"}}
    rows = []
    for name, value in data.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        rows.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + name)
    manifest = source / "SHA256SUMS"
    manifest.write_text("\n".join(rows) + "\n")
    (source / "sealed.json").write_text(json.dumps({"sha256_manifest": hashlib.sha256(manifest.read_bytes()).hexdigest()}))
    return source


def test_recovery_refuses_changed_sealed_evidence_before_writing_new_state(tmp_path):
    source = source_archive(tmp_path)
    (source / "main/rows.json").write_text("[]")
    cloud = SimpleNamespace(record=Mock())
    with pytest.raises(ValueError, match="Sealed source file changed"):
        recovery.prepare(cloud, source)
    cloud.record.assert_not_called()


def test_recovery_keeps_original_calibration_and_does_not_import_primary_rows(tmp_path, monkeypatch):
    source = source_archive(tmp_path)
    run = tmp_path / "replacement"
    run.mkdir()
    cloud = SimpleNamespace(run=run, state={"project_id": "p", "created_at": "2026-10-15T06:00:00+00:00"},
        plan={"estimated_six_hour_total_before_variable_usage": 150}, record=Mock())
    monkeypatch.setattr(recovery, "billing", lambda *args: {"preliminary_rub_before_grant": 150})
    recovery.prepare(cloud, source)
    assert cloud.state["budget_started_at"] == "2026-10-14T17:37:00+00:00"
    assert cloud.plan["calibration_run"] == str(source.resolve())
    assert cloud.plan["source_image"] == "sha256:unchanged"
    assert not (run / "main/rows.json").exists()
    assert json.loads((run / "recovery.json").read_text())["original_primary_rows_reused"] == 0


def test_recovery_cannot_ignore_previous_calendar_day_charges(tmp_path):
    (tmp_path / "main").mkdir()
    client = SimpleNamespace(project_id="p", request=Mock(return_value={"consumptions": [{"amount_nds": 430}]}))
    cloud = SimpleNamespace(run=tmp_path, client=client,
        state={"created_at": "2026-10-15T06:00:00+00:00", "budget_started_at": "2026-10-14T17:37:00+00:00"},
        plan={"estimated_six_hour_total_before_variable_usage": 150})
    with pytest.raises(RuntimeError, match="Budget reserve"):
        budget_check(cloud, "new-main")
    assert client.request.call_args.args[2]["start_date"].startswith("2026-10-14T00:00:00")


def test_setup_failure_before_admission_has_an_empty_backup_audit(tmp_path):
    assert audit_backups(tmp_path) == []
    assert json.loads((tmp_path / "final-backup-audit.json").read_text())["passed"]
