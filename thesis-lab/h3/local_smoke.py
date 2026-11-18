"""Validate a portable bundle in a disposable local Compose project, never in YC."""

import argparse
from datetime import UTC, datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess

PROJECT = "firefly-thesis-h3-smoke-v2"
VARIANTS = ("original", "optimized", "projection", "incremental")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    subprocess.run(["sha256sum", "--check", "--quiet", "SHA256SUMS"], cwd=bundle, check=True)
    for kind, flags in (("ps", ["-aq"]), ("volume", ["ls", "-q"]), ("network", ["ls", "-q"])):
        present = subprocess.check_output(["docker", kind, *flags, "--filter", "label=com.docker.compose.project=" + PROJECT], text=True).strip()
        if present:
            raise RuntimeError("An existing smoke project is present; refusing to reuse or remove it")
    if (bundle / "results/cloud-smoke").exists():
        raise RuntimeError("Existing smoke measurements must be archived separately before a new run")
    ids = subprocess.check_output(["docker", "network", "ls", "-q"], text=True).split()
    networks = json.loads(subprocess.check_output(["docker", "network", "inspect", *ids], text=True))
    used = [ipaddress.ip_network(c["Subnet"]) for n in networks for c in (n.get("IPAM", {}).get("Config") or []) if c.get("Subnet")]
    candidates = [ipaddress.ip_network(f"10.254.{i}.0/24") for i in range(220, 240)]
    available = [n for n in candidates if not any(n.version == other.version and n.overlaps(other) for other in used)]
    if len(available) < 2:
        raise RuntimeError("No available smoke subnet; existing networks will not be modified")
    subnet, access_subnet = available[:2]
    env = {**os.environ, **{key: secrets.token_hex(24) for key in ("DB_PASSWORD", "ADMIN_PASSWORD", "JWT_SECRET_KEY", "JWT_REFRESH_SECRET_KEY")}, "SERVER_PRIVATE_IP": "127.0.0.1", "THESIS_OUTPUT": "/results/cloud-smoke"}
    server_override = output / "server.override.json"
    server_override.write_text(json.dumps({"networks": {"isolated": {"ipam": {"config": [{"subnet": str(subnet)}]}}, "access": {"ipam": {"config": [{"subnet": str(access_subnet)}]}}}}, indent=2))
    base = ["docker", "compose", "--project-name", PROJECT, "-f", str(bundle / "h3/compose.server.yml"), "-f", str(server_override)]
    # Attach a distinct load-generator container to the test-only server network.
    # A two-VM path and YC security groups still need a subsequent cloud smoke test.
    override = output / "loadgen.override.json"
    override.write_text(json.dumps({"services": {"runner": {"networks": ["smoke"], "environment": {"THESIS_TARGET_URLS": json.dumps({v: f"http://{v}:8000" for v in VARIANTS})}}}, "networks": {"smoke": {"external": True, "name": PROJECT + "_isolated"}}}, indent=2))
    loadgen = ["docker", "compose", "--project-name", PROJECT, "-f", str(bundle / "h3/compose.loadgen.yml"), "-f", str(override)]
    log = (output / "commands.log").open("w")

    def run(argv, *, environment=None):
        # No secret values are present in argv; credentials are inherited in env.
        log.write("\n" + " ".join(argv) + "\n")
        log.flush()
        subprocess.run(argv, env=environment or env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)

    def compose(*args):
        run([*base, *args])

    def inside(module, *args, database="seed"):
        assert database in ("seed", "validation", *VARIANTS)
        url = "postgresql+asyncpg://thesis:" + env["DB_PASSWORD"] + "@db:5432/thesis_exp_" + database
        run([*base, "run", "--rm", "--no-deps", "-e", "DATABASE_URL", "-e", "DATABASE_SYNC_URL", "runner", "python", "-m", "h3.entry", module, *map(str, args)], environment={**env, "DATABASE_URL": url, "DATABASE_SYNC_URL": url.replace("postgresql+asyncpg", "postgresql+psycopg")})

    result = {"started_at": datetime.now(UTC).isoformat(), "environment": "local Docker smoke only", "bundle_sha256sums": hashlib.sha256((bundle / "SHA256SUMS").read_bytes()).hexdigest(), "passed": False, "paid_resources_created": False}
    try:
        compose("up", "-d", "--wait", "db", "redis")
        inside("expanded.init_db")
        compose("up", "-d", "--wait", "seed")
        inside("h3.dataset", json.dumps({"id": "incremental-smoke-1k", "n": 1000, "pilots": 100, "neighbors": 1, "neighbor_n": 20, "neighbor_pilots": 5}))
        compose("stop", "seed")
        compose("exec", "-T", "db", "psql", "-U", "thesis", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", "CREATE DATABASE thesis_exp_validation TEMPLATE thesis_exp_seed")
        inside("h3.validate", database="validation")
        for variant in VARIANTS:
            for sql in (f"DROP DATABASE IF EXISTS thesis_exp_{variant} WITH (FORCE)", f"CREATE DATABASE thesis_exp_{variant} TEMPLATE thesis_exp_seed"):
                compose("exec", "-T", "db", "psql", "-U", "thesis", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-c", sql)
            inside("h3.install", variant, database=variant)
        compose("up", "-d", "--wait", *VARIANTS, "worker", "worker-incremental")
        for args in (("h3.reads", "--check"), ("h3.reads", "--rep", "0", "--requests", "4"), ("h3.mixed", "--repeats", "1", "--duration", "2")):
            run([*loadgen, "run", "--rm", "--no-deps", "runner", "python", "-m", "h3.entry", *args])
        compose("stop", "worker", "worker-incremental")
        for variant in ("projection", "incremental"):
            inside("h3.coalescing", variant, database=variant)
        raw = bundle / "results/cloud-smoke"
        checks = [json.loads(s) for s in (raw / "read-checks.jsonl").read_text().splitlines()]
        reads = [json.loads(s) for s in (raw / "read-http.jsonl").read_text().splitlines()]
        cases = [json.loads(s) for s in (raw / "mixed-series.jsonl").read_text().splitlines()]
        assert len(checks) == 32 and all(r["passed"] for r in checks)
        assert len(reads) == 64 and all(r["status"] == 200 and r["correct"] for r in reads)
        assert len(cases) == 12 and all(r["converged"] and not r["write_errors"] and not r["read_errors"] and not r["not_visible_before_deadline"] for r in cases)
        validation = json.loads((raw / "incremental-validation-complete.json").read_text())
        assert validation["passed"]
        bursts = [json.loads(s) for s in (raw / "coalescing.jsonl").read_text().splitlines()]
        assert len(bursts) == 20 and all(r["correct"] and r["pending_before_drain"] == 1 for r in bursts)
        result.update(validation=validation, coalescing_cases=len(bursts))
        result.update(passed=True, read_checks=len(checks), measured_read_requests=len(reads), mixed_cases=len(cases))
    except BaseException as error:
        result["failure"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        raw = bundle / "results/cloud-smoke"
        if raw.exists():
            shutil.copytree(raw, output / "raw", dirs_exist_ok=True)
        try:
            compose("down", "--volumes", "--remove-orphans")
            result["local_resources_removed"] = True
        except Exception:
            result["local_resources_removed"] = False
            result["passed"] = False
        result["ended_at"] = datetime.now(UTC).isoformat()
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        log.close()
        print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
