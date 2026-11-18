"""Configure addresses/credentials without modifying frozen benchmark sources."""

import json
import os
import runpy
import sys

import httpx


def configure():
    from expanded import common

    targets = json.loads(os.environ.get("THESIS_TARGET_URLS", "{}"))
    password = os.environ["ADMIN_PASSWORD"]
    if not password:
        raise ValueError("ADMIN_PASSWORD must not be empty")

    def client(host="functional"):
        return httpx.AsyncClient(
            base_url=targets.get(host, f"http://{host}:8000"),
            timeout=120,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
        )

    async def login(c):
        response = await c.post("/api/auth/login", json={"login": "admin", "password": password})
        response.raise_for_status()
        return {"Authorization": "Bearer " + response.json()["accessToken"]}

    common.client = client
    common.login = login


def main():
    allowed = {"expanded.reads", "expanded.mixed", "expanded.dataset", "expanded.init_db", "expanded.install", "expanded.explain"}
    if len(sys.argv) < 2 or sys.argv[1] not in allowed:
        raise SystemExit("Expected an allowlisted expanded benchmark module")
    module = sys.argv.pop(1)
    configure()
    runpy.run_module(module, run_name="__main__")


if __name__ == "__main__":
    main()
