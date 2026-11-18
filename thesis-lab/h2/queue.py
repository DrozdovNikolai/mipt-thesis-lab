"""Durable experimental speech queue; lease fencing and idempotent admission.

One coordinator owns the SQLite WAL database on persistent storage. This is an
adapter for the experiment, not a replacement of Firefly's production Celery.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Conflict(ValueError):
    pass


class Queue:
    def __init__(self, path, *, lease_seconds=30, clock=time.time):
        self.path, self.lease_seconds, self.clock = str(path), lease_seconds, clock
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS tasks(
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, payload_sha TEXT NOT NULL,
                accepted_at REAL NOT NULL, deadline_at REAL NOT NULL,
                state TEXT NOT NULL, stage TEXT NOT NULL, worker TEXT,
                lease TEXT, lease_until REAL, stage_started_at REAL,
                first_started_at REAL, completed_at REAL, result TEXT, result_sha TEXT,
                attempts INTEGER NOT NULL DEFAULT 0, expected_sha TEXT);
              CREATE TABLE IF NOT EXISTS events(
                seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
                task TEXT, kind TEXT NOT NULL, detail TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS workers(
                id TEXT PRIMARY KEY, seen_at REAL NOT NULL, ready_at REAL NOT NULL,
                metadata TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, db, task, kind, detail):
        db.execute("INSERT INTO events(at,task,kind,detail) VALUES(?,?,?,?)",
                   (self.clock(), task, kind, canonical(detail)))

    def admit(self, task_id, payload, *, deadline_seconds, expected_sha=None):
        if deadline_seconds <= 0 or not task_id or payload.get("audio_seconds", 0) <= 0:
            raise ValueError("Invalid task admission")
        intent = {"payload": payload, "deadline_seconds": deadline_seconds,
                  "expected_sha": expected_sha}
        with self.connect() as db:
            existing = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if existing:
                if existing["payload_sha"] != digest(intent):
                    raise Conflict("Idempotency key has another intent")
                return dict(existing)
            now = self.clock()
            db.execute("""INSERT INTO tasks(id,payload,payload_sha,accepted_at,deadline_at,
                       state,stage,expected_sha) VALUES(?,?,?,?,?,'queued','preprocess',?)""",
                       (task_id, canonical(payload), digest(intent), now, now + deadline_seconds, expected_sha))
            self.event(db, task_id, "accepted", intent)
            return dict(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def expire(self, db):
        rows = db.execute("SELECT * FROM tasks WHERE state='running' AND lease_until<=?",
                          (self.clock(),)).fetchall()
        for task in rows:
            self.event(db, task["id"], "lease_expired", {"worker": task["worker"], "lease": task["lease"]})
            # The ASR checkpoint is on a worker-local filesystem; retry all stages.
            db.execute("""UPDATE tasks SET state='queued',stage='preprocess',worker=NULL,
                       lease=NULL,lease_until=NULL,stage_started_at=NULL WHERE id=?""", (task["id"],))

    def claim(self, worker):
        with self.connect() as db:
            self.expire(db)
            if db.execute("SELECT id FROM tasks WHERE worker=? AND state='running'", (worker,)).fetchone():
                raise Conflict("Worker already owns an in-flight task")
            row = db.execute("SELECT * FROM tasks WHERE state='queued' ORDER BY accepted_at,id LIMIT 1").fetchone()
            if not row:
                return None
            lease, now = uuid.uuid4().hex, self.clock()
            db.execute("""UPDATE tasks SET state='running',worker=?,lease=?,lease_until=?,
                       stage_started_at=?,first_started_at=COALESCE(first_started_at,?),
                       attempts=attempts+1 WHERE id=?""",
                       (worker, lease, now + self.lease_seconds, now, now, row["id"]))
            self.event(db, row["id"], "claimed", {"worker": worker, "lease": lease})
            return dict(db.execute("SELECT * FROM tasks WHERE id=?", (row["id"],)).fetchone())

    def owned(self, db, task_id, worker, lease):
        row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row or row["state"] != "running" or row["worker"] != worker or row["lease"] != lease or row["lease_until"] <= self.clock():
            raise Conflict("Stale or invalid lease")
        return row

    def heartbeat(self, task_id, worker, lease, stage=None):
        with self.connect() as db:
            row = self.owned(db, task_id, worker, lease)
            now = self.clock()
            if stage and stage != row["stage"]:
                if (row["stage"], stage) != ("preprocess", "asr"):
                    raise Conflict("Invalid stage transition")
                db.execute("UPDATE tasks SET stage=?,stage_started_at=? WHERE id=?", (stage, now, task_id))
                self.event(db, task_id, "stage", {"stage": stage, "worker": worker, "lease": lease})
            db.execute("UPDATE tasks SET lease_until=? WHERE id=?", (now + self.lease_seconds, task_id))

    def complete(self, task_id, worker, lease, result):
        sha = digest(result)
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row and row["state"] == "done" and row["worker"] == worker and row["lease"] == lease:
                if row["result_sha"] != sha:
                    raise Conflict("Completed result is immutable")
                return dict(row)
            row = self.owned(db, task_id, worker, lease)
            if row["stage"] != "asr":
                raise Conflict("Cannot complete before ASR")
            db.execute("UPDATE tasks SET state='done',completed_at=?,result=?,result_sha=? WHERE id=?",
                       (self.clock(), canonical(result), sha, task_id))
            self.event(db, task_id, "completed", {"result_sha": sha, "lease": lease,
                       "matches_reference": sha == row["expected_sha"] if row["expected_sha"] else None})
            return dict(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def register(self, worker, metadata):
        with self.connect() as db:
            now = self.clock()
            exists = db.execute("SELECT id FROM workers WHERE id=?", (worker,)).fetchone()
            db.execute("""INSERT INTO workers VALUES(?,?,?,?) ON CONFLICT(id)
                       DO UPDATE SET seen_at=excluded.seen_at""", (worker, now, now, canonical(metadata)))
            if not exists:
                self.event(db, None, "worker_ready", {"worker": worker, **metadata})

    def snapshot(self):
        with self.connect() as db:
            self.expire(db)
            return {"at": self.clock(), "tasks": [dict(x) for x in db.execute("SELECT * FROM tasks ORDER BY accepted_at,id")],
                    "workers": [dict(x) for x in db.execute("SELECT * FROM workers")],
                    "events": [dict(x) for x in db.execute("SELECT * FROM events ORDER BY seq")]}

    def backup(self, destination):
        with sqlite3.connect(self.path) as source, sqlite3.connect(destination) as target:
            source.backup(target)
