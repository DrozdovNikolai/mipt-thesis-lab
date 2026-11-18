import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from h2.queue import Queue, Conflict, digest


def test_concurrent_claims_and_duplicate_admission(tmp_path):
    queue = Queue(tmp_path / "q.db")
    payload = {"audio_seconds": 10, "fixture": "example"}
    a = queue.admit("task", payload, deadline_seconds=30)
    assert queue.admit("task", payload, deadline_seconds=30)["accepted_at"] == a["accepted_at"]
    with pytest.raises(Conflict):
        queue.admit("task", payload, deadline_seconds=31)
    with ThreadPoolExecutor(8) as pool:
        claimed = list(pool.map(lambda i: queue.claim(str(i)), range(8)))
    assert sum(x is not None for x in claimed) == 1


def test_crash_reopen_expiration_and_fenced_completion(tmp_path):
    now = [100.0]
    path = tmp_path / "q.db"
    queue = Queue(path, lease_seconds=10, clock=lambda: now[0])
    result = {"segments": [{"text": "test", "start": 0, "end": 5}]}
    queue.admit("a", {"audio_seconds": 10}, deadline_seconds=60, expected_sha=digest(result))
    old = queue.claim("old")
    queue.heartbeat("a", "old", old["lease"], "asr")
    now[0] += 11
    queue = Queue(path, lease_seconds=10, clock=lambda: now[0])
    new = queue.claim("new")
    assert new["attempts"] == 2
    assert new["stage"] == "preprocess"
    with pytest.raises(Conflict):
        queue.complete("a", "old", old["lease"], result)
    queue.heartbeat("a", "new", new["lease"], "asr")
    first = queue.complete("a", "new", new["lease"], result)
    again = queue.complete("a", "new", new["lease"], result)
    assert again["completed_at"] == first["completed_at"]
    with pytest.raises(Conflict):
        queue.complete("a", "new", new["lease"], {"changed": True})
    assert first["result_sha"] == first["expected_sha"]
    events = queue.snapshot()["events"]
    assert sum(x["kind"] == "completed" for x in events) == 1
    queue.backup(tmp_path / "copy.db")
    assert Queue(tmp_path / "copy.db", clock=lambda: now[0]).snapshot()["tasks"] == queue.snapshot()["tasks"]


def test_expired_heartbeat_cannot_resurrect_work(tmp_path):
    now = [0]
    queue = Queue(tmp_path / "q.db", lease_seconds=1, clock=lambda: now[0])
    queue.admit("a", {"audio_seconds": 1}, deadline_seconds=10)
    task = queue.claim("a")
    now[0] = 2
    with pytest.raises(Conflict):
        queue.heartbeat("a", "a", task["lease"])
    assert queue.claim("b")["worker"] == "b"
