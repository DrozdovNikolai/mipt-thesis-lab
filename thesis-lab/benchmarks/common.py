import asyncio
import json
import os
from pathlib import Path
import time
import uuid

import httpx

OUT = Path(os.environ.get("THESIS_OUTPUT", "/results/pilot"))
OUT.mkdir(parents=True, exist_ok=True)


def save(name, value):
    (OUT / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str)
    )


def append(name, row):
    with (OUT / name).open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


async def login(client):
    for attempt in range(60):
        try:
            health = await client.get("/")
            if health.status_code == 200:
                break
        except httpx.TransportError:
            pass
        await asyncio.sleep(0.5)
    r = await client.post(
        "/api/auth/login", json={"login": "admin", "password": "admin123"}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["accessToken"]}


async def measured(client, method, path, body, headers, context, *, params=None):
    request = client.build_request(
        method, path, json=body, headers=headers, params=params
    )
    start = time.perf_counter()
    response = await client.send(request)
    elapsed = (time.perf_counter() - start) * 1000
    append(
        "requests.jsonl",
        {
            **context,
            "path": path,
            "method": method,
            "status": response.status_code,
            "latency_ms": elapsed,
            "sent_bytes": len(request.content),
            "received_bytes": len(response.content),
        },
    )
    return response, elapsed, len(request.content) + len(response.content)


def client():
    return httpx.AsyncClient(
        base_url="http://app:8000",
        timeout=120,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=50),
    )


class UniqueFixtureClient:
    """Reuse repository fixture builders without colliding with earlier datasets."""

    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.tag = uuid.uuid4().hex[:8]

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    async def post(self, path, **kwargs):
        if "json" in kwargs:
            body = dict(kwargs["json"])
            if path == "/api/training/airlines":
                body["code"] = "T" + self.tag
            if path == "/api/training/users":
                body["email"] = self.tag + "." + body["email"]
            kwargs["json"] = body
        return await self.wrapped.post(path, **kwargs)
