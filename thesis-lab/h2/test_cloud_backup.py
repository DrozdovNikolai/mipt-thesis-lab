import json
import sqlite3
from contextlib import closing

import pytest

from h2.cloud_trial import verify_backup
from h2.queue import Queue, digest


def fixture(tmp_path):
    q = Queue(tmp_path / "live.sqlite")
    result = {"language": "en", "aligned": {"segments": [{"text": "test", "start": 0, "end": 1}]}}
    q.admit("done", {"fixture": "pilot-30", "audio_seconds": 30}, deadline_seconds=60,
            expected_sha=digest(result))
    lease = q.claim("worker")["lease"]
    q.heartbeat("done", "worker", lease, stage="asr")
    q.complete("done", "worker", lease, result)
    q.admit("pending", {"fixture": "pilot-900", "audio_seconds": 900}, deadline_seconds=60)
    backup = tmp_path / "backup.sqlite"
    q.backup(backup)
    return q, backup


def test_backup_restores_completed_and_unfinished_tasks_without_claiming_all_correct(tmp_path):
    q, backup = fixture(tmp_path)
    audit = verify_backup(backup, snapshot=q.snapshot(), expected_ids=["done", "pending"])
    assert audit["passed"]
    assert audit["restored_counts"]["tasks"] == 2
    assert audit["metrics"]["correct"] == 1
    assert audit["metrics"]["unfinished"] == 1


def test_missing_submission_cannot_be_hidden_by_a_self_consistent_backup(tmp_path):
    q, backup = fixture(tmp_path)
    with pytest.raises(ValueError, match="submitted workload"):
        verify_backup(backup, snapshot=q.snapshot(), expected_ids=["done", "pending", "lost"])


def test_duplicate_accepted_completion_is_detected_independently(tmp_path):
    q, backup = fixture(tmp_path)
    with closing(sqlite3.connect(backup)) as db, db:
        db.execute("INSERT INTO events(at,task,kind,detail) VALUES(0,'done','completed','{}')")
    with pytest.raises(ValueError, match="duplicate"):
        verify_backup(backup, snapshot=q.snapshot(), expected_ids=["done", "pending"])


def test_forged_result_with_unchanged_digest_is_detected(tmp_path):
    q, backup = fixture(tmp_path)
    snap = q.snapshot()
    forged = json.dumps({"language": "en", "aligned": {"segments": []}})
    with closing(sqlite3.connect(backup)) as db, db:
        db.execute("UPDATE tasks SET result=? WHERE id='done'", (forged,))
    next(t for t in snap["tasks"] if t["id"] == "done")["result"] = forged
    with pytest.raises(ValueError, match="hash"):
        verify_backup(backup, snapshot=snap, expected_ids=["done", "pending"])


def test_open_wal_cannot_be_silently_ignored_by_standalone_backup_audit(tmp_path):
    q, backup = fixture(tmp_path)
    with closing(sqlite3.connect(backup)) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("UPDATE tasks SET result_sha='changed' WHERE id='done'")
        db.commit()
        with pytest.raises(ValueError, match="WAL sidecar"):
            verify_backup(backup, snapshot=q.snapshot(), expected_ids=["done", "pending"])
