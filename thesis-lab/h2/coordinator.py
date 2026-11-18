"""Single-writer experiment coordinator; no production routes or credentials."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from app.modules.speech.workload_scaling import StageCost, WorkItem, decide, count_baseline
from h2.queue import Queue, Conflict
from h2.capacity import Capacity, pending_estimates

ROOT = Path(os.environ.get("H2_DATA", "/data"))
FIXTURES = Path(os.environ.get("H2_FIXTURES", "/fixtures"))
ROOT.mkdir(parents=True, exist_ok=True)
queue = Queue(ROOT / "queue.sqlite")
CONFIG_PATH = ROOT / "config.json"
app = FastAPI()
capacity = Capacity()


def config():
    return json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {
        "variant": "fixed", "max_workers": 3, "fixed_workers": 1, "target_queue": 2,
        "cold_start_seconds": 120, "safety_factor": 1.2,
        "costs": {"preprocess": {"fixed_seconds": 0.2, "seconds_per_audio_second": 0.01},
                  "asr": {"fixed_seconds": 1, "seconds_per_audio_second": 0.3}}}


def authenticate(authorization):
    token = os.environ.get("H2_API_TOKEN", "")
    if not token or not secrets.compare_digest(authorization or "", "Bearer " + token):
        raise HTTPException(401, "Invalid experimental API token")


def safe_component(value):
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", value):
        raise HTTPException(400, "Invalid identifier")
    return value


@app.exception_handler(Conflict)
async def conflict_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/metrics")
def metrics():
    cfg = config()
    snapshot = queue.snapshot()
    now = snapshot["at"]
    active = [t for t in snapshot["tasks"] if t["state"] != "done"]
    items = [WorkItem(t["id"], t["accepted_at"], t["deadline_at"],
                      json.loads(t["payload"])["audio_seconds"], t["stage"], t["state"],
                      t["worker"], t["stage_started_at"]) for t in active]
    live_workers = {w["id"] for w in snapshot["workers"] if w["seen_at"] > now - 15}
    ready = len(live_workers)
    observed_capacity = capacity.snapshot()
    excluded = live_workers | {t["worker"] for t in active if t["state"] == "running"}
    pending = pending_estimates(observed_capacity["pods"], now=now,
        cold_start_seconds=cfg["cold_start_seconds"], excluded_ids=excluded)
    decision = decide(items, now=now, costs={s: StageCost(**v) for s, v in cfg["costs"].items()},
                       ready_workers=ready, cold_start_seconds=cfg["cold_start_seconds"],
                       max_workers=cfg["max_workers"], safety_factor=cfg["safety_factor"],
                       pending_worker_seconds=pending)
    count = count_baseline(items, target_queue=cfg["target_queue"], max_workers=cfg["max_workers"])
    target = {"fixed": cfg["fixed_workers"], "count": count, "work": decision.replicas}[cfg["variant"]]
    done = [t for t in snapshot["tasks"] if t["state"] == "done"]
    correct = [t for t in done if t["expected_sha"] and t["result_sha"] == t["expected_sha"]]
    return {**asdict(decision), "value": target, "count_replicas": count, "ready_workers": ready,
            "at": now, "accepted": len(snapshot["tasks"]), "completed": len(done),
            "correct": len(correct), "on_time": sum(t["completed_at"] <= t["deadline_at"] for t in correct),
            "variant": cfg["variant"], "pending_worker_seconds": pending,
            "capacity_observation": {k: v for k, v in observed_capacity.items() if k != "pods"}}


@app.get("/snapshot")
def snapshot(authorization: str | None = Header(None)):
    authenticate(authorization)
    return queue.snapshot()


@app.post("/config")
def set_config(payload: dict, authorization: str | None = Header(None)):
    authenticate(authorization)
    if payload.get("variant") not in {"fixed", "count", "work"}:
        raise HTTPException(400, "Unknown strategy")
    temporary = CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True))
    temporary.replace(CONFIG_PATH)
    return payload


@app.post("/admit/{task_id}")
def admit(task_id: str, payload: dict, authorization: str | None = Header(None)):
    authenticate(authorization)
    safe_component(task_id)
    fixture = safe_component(payload["payload"]["fixture"])
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    metadata = manifest["fixtures"][fixture]
    if payload["payload"]["audio_seconds"] != metadata["audio_seconds"]:
        raise HTTPException(400, "Audio metadata mismatch")
    return queue.admit(task_id, **payload)


@app.post("/claim")
def claim(payload: dict, authorization: str | None = Header(None)):
    authenticate(authorization)
    return queue.claim(payload["worker"])


@app.post("/heartbeat")
def heartbeat(payload: dict, authorization: str | None = Header(None)):
    authenticate(authorization)
    queue.heartbeat(**payload)
    return {"ok": True}


@app.post("/register")
def register(payload: dict, authorization: str | None = Header(None)):
    authenticate(authorization)
    queue.register(**payload)
    return {"ok": True}


@app.post("/complete")
def complete(payload: dict, authorization: str | None = Header(None)):
    authenticate(authorization)
    return queue.complete(**payload)


@app.get("/fixtures/{name}")
def fixture(name: str):
    return FileResponse(FIXTURES / (safe_component(name) + ".wav"), media_type="audio/wav")


@app.put("/artifacts/{task_id}/{lease}/{kind}")
async def put_artifact(task_id: str, lease: str, kind: str, request: Request):
    # The unpredictable current lease is the narrow upload capability; benchmark-only.
    if kind not in {"wav", "json"}:
        raise HTTPException(400)
    safe_component(task_id)
    safe_component(lease)
    path = ROOT / "artifacts" / task_id / lease
    path.mkdir(parents=True, exist_ok=True)
    temporary = path / (kind + ".tmp")
    size = 0
    try:
        with temporary.open("wb") as stream:
            async for chunk in request.stream():
                size += len(chunk)
                if size > 64 * 1024 * 1024:
                    raise HTTPException(413)
                stream.write(chunk)
        with queue.connect() as db:
            row = db.execute("SELECT worker FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise HTTPException(404)
            queue.owned(db, task_id, row["worker"], lease)
            temporary.replace(path / kind)
        return {"bytes": size}
    finally:
        temporary.unlink(missing_ok=True)


@app.get("/artifacts/{task_id}/{lease}/{kind}")
def artifact(task_id: str, lease: str, kind: str):
    if kind not in {"wav", "json"}:
        raise HTTPException(400)
    path = ROOT / "artifacts" / safe_component(task_id) / safe_component(lease) / kind
    return FileResponse(path)
