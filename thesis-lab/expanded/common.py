import json
import os
import time
from pathlib import Path
import httpx

OUT = Path(os.environ.get("THESIS_OUTPUT", "/results/expanded-pilot"))
OUT.mkdir(parents=True, exist_ok=True)


def save(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str)
    )


def append(name, value):
    value = {"recorded_at": time.time(), **value}
    with (OUT / name).open("a") as f:
        f.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")


def client(host="functional"):
    return httpx.AsyncClient(
        base_url=f"http://{host}:8000",
        timeout=120,
        limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
    )


async def login(c):
    r = await c.post("/api/auth/login", json=dict(login="admin", password="admin123"))
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["accessToken"]}
