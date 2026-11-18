import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from h2.cloudru_finish import finish, scan_secrets
from h2.cloudru_preflight import CloudruError


def test_failed_backup_audit_prevents_destructive_cleanup(tmp_path):
    cloud = SimpleNamespace(run=tmp_path, stop=Mock(), cleanup=Mock())
    with patch("h2.cloudru_finish.audit_backups", side_effect=ValueError("corrupt backup")):
        with pytest.raises(ValueError, match="corrupt backup"):
            finish(cloud)
    cloud.stop.assert_not_called()
    cloud.cleanup.assert_not_called()


def test_billing_outage_does_not_prevent_cleanup_of_verified_backed_up_resources(tmp_path):
    cloud = SimpleNamespace(run=tmp_path, state={"cluster": {"deleted_at": "done"}},
        stop=Mock(), cleanup=Mock(), client=SimpleNamespace(compute_list=Mock(return_value={"items": []})))
    with patch("h2.cloudru_finish.audit_backups", return_value=[]), \
         patch("h2.cloudru_finish.export", side_effect=CloudruError("monitoring", 503, {})), \
         patch("h2.cloudru_finish.billing", side_effect=CloudruError("organization", None, {})):
        result = finish(cloud)
    cloud.stop.assert_called_once()
    cloud.cleanup.assert_called_once()
    assert result["complete"]
    for name in ("final-native-export", "billing-before-cleanup", "billing-after-cleanup"):
        saved = json.loads((tmp_path / (name + "-unavailable.json")).read_text())
        assert saved["available"] is False and saved["reconciliation_required"]


def test_secret_scan_detects_private_values_across_read_boundaries_without_echoing_them(tmp_path):
    run, runtime = tmp_path / "results", tmp_path / "private"
    run.mkdir(); runtime.mkdir()
    private = "sensitive-value-crossing-the-boundary"
    (runtime / "api-token").write_text(private)
    (runtime / "guard-profile.json").write_text(json.dumps({"key_id": "guard-key-id", "key_secret": "guard-key-secret"}))
    (run / "log.txt").write_bytes(b"x" * (1024 * 1024 - 5) + private.encode())
    with patch("h2.cloudru_finish.load_profile", return_value={"key_id": "owner-key-id", "key_secret": "owner-key-secret"}):
        with pytest.raises(ValueError) as failure:
            scan_secrets(run, runtime)
    assert "log.txt" in str(failure.value) and private not in str(failure.value)
