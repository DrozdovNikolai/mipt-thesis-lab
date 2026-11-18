"""Repeat real ASR parity/recovery checks under a compact worker resource budget.

Reuses the original local functional test with a fresh Compose project and data
volume. Its timings are local readiness observations, never cloud benchmarks.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import subprocess
import sys

from h2 import local_run
from h2.cloud_trial import verify_backup

IMAGE = "sha256:a410db19970c48afe507d872e065aa4d4ceed15feca3a5f4469144c589aadf5e"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    run_id = out.name
    if not re.fullmatch(r"[a-z0-9-]{1,55}", run_id):
        raise ValueError("Output directory name must be a short lowercase run identifier")
    project = "ff-" + run_id
    runtime = Path.home() / ".local/share/firefly-thesis" / run_id
    runtime.mkdir(parents=True, mode=0o700, exist_ok=False)
    runtime.chmod(0o700)
    local_run.ENV = runtime / "runtime.env"
    local_run.PROJECT = project
    specification = {
        "services": {
            "coordinator": {
                "image": IMAGE, "command": ["uvicorn", "h2.coordinator:app", "--host", "0.0.0.0",
                    "--port", "8080", "--log-level", "warning"],
                "cpus": 1, "mem_limit": "1g", "environment": {"H2_API_TOKEN": "${H2_API_TOKEN:?}"},
                "ports": ["127.0.0.1:18082:8080"], "volumes": ["data:/data"], "networks": ["bench", "access"]},
            "worker": {
                "image": IMAGE, "cpus": 1.5, "mem_limit": "2g", "memswap_limit": "2g",
                "environment": {"H2_API_TOKEN": "${H2_API_TOKEN:?}", "H2_COORDINATOR": "http://coordinator:8080"},
                "networks": ["bench"], "profiles": ["worker"]},
        },
        "networks": {
            "bench": {"internal": True, "ipam": {"config": [{"subnet": "10.253.223.0/24"}]}},
            "access": {"ipam": {"config": [{"subnet": "10.253.224.0/24"}]}},
        }, "volumes": {"data": {}},
    }
    compose_file = out / "compose.json"
    compose_file.write_text(json.dumps(specification, indent=2) + "\n")
    prefix = ["docker", "compose", "-p", project, "--env-file", str(local_run.ENV), "-f", str(compose_file)]
    saved_backup = False

    def raw_compose(*parts, **kwargs):
        return subprocess.run(prefix + list(parts), check=True, **kwargs)

    def preserve():
        nonlocal saved_backup
        workers = raw_compose("ps", "-a", "-q", "worker", capture_output=True, text=True).stdout.splitlines()
        observations = []
        for worker in workers:
            inspect = json.loads(subprocess.check_output(["docker", "inspect", worker], text=True))[0]
            state = inspect["State"]
            row = {"id": worker, "state": state, "image": inspect["Image"],
                   "memory_limit_bytes": inspect["HostConfig"]["Memory"],
                   "swap_limit_bytes": inspect["HostConfig"]["MemorySwap"],
                   "nano_cpus": inspect["HostConfig"]["NanoCpus"]}
            if state["Running"]:
                for metric in ("memory.peak", "memory.events", "cpu.stat"):
                    result = subprocess.run(["docker", "exec", worker, "cat", "/sys/fs/cgroup/" + metric],
                                            capture_output=True, text=True)
                    row[metric] = result.stdout if result.returncode == 0 else None
            observations.append(row)
        (out / "worker-resources.json").write_text(json.dumps(observations, indent=2) + "\n")
        export = """import sqlite3
from contextlib import closing
with closing(sqlite3.connect('/data/queue.sqlite')) as source:
    with closing(sqlite3.connect('/data/compact-export.sqlite')) as target:
        source.backup(target)
        assert target.execute('PRAGMA journal_mode=DELETE').fetchone()[0] == 'delete'
"""
        raw_compose("exec", "-T", "coordinator", "python", "-c", export, capture_output=True)
        data = raw_compose("exec", "-T", "coordinator", "cat", "/data/compact-export.sqlite", capture_output=True).stdout
        (out / "queue.sqlite").write_bytes(data)
        snapshot = out / "asr/snapshot.json"
        if not snapshot.exists():
            snapshot = out / "asr/snapshot-failure.json"
        if snapshot.exists():
            value = json.loads(snapshot.read_text())
            audit = verify_backup(out / "queue.sqlite", snapshot=value, expected_ids=[t["id"] for t in value["tasks"]])
            (out / "backup-audit.json").write_text(json.dumps(audit, indent=2) + "\n")
            saved_backup = True

    def compose(*parts, **kwargs):
        if parts and parts[0] == "stop":
            try:
                preserve()
            except Exception as exc:
                (out / "preservation-error.json").write_text(json.dumps({"type": type(exc).__name__}) + "\n")
        return raw_compose(*parts, **kwargs)

    local_run.compose = compose
    original_argv = sys.argv
    try:
        sys.argv = ["h2.local_run", str(out / "asr")]
        local_run.main()
        resources = json.loads((out / "worker-resources.json").read_text())
        if not saved_backup or not resources or any(r["state"]["OOMKilled"] for r in resources):
            raise RuntimeError("Compact readiness requires audited backup and no OOM")
        (out / "summary.json").write_text(json.dumps({"passed": True, "local_readiness_only": True,
            "at": datetime.now(UTC).isoformat(), "image": IMAGE, "worker_cpus": 1.5,
            "worker_memory_gib": 2, "swap_enabled": False,
            "worker_memory_peak_bytes": [int(r["memory.peak"]) for r in resources if r.get("memory.peak")],
            "asr_summary": json.loads((out / "asr/summary.json").read_text())}, indent=2) + "\n")
    finally:
        sys.argv = original_argv
        # This fresh project owns only the containers/networks created above.
        # Retain its volume unless a standalone queue backup was verified.
        cleanup = ["down", "--remove-orphans"] + (["--volumes"] if saved_backup else [])
        result = subprocess.run(prefix + cleanup, capture_output=True, text=True)
        (out / "cleanup.log").write_text(result.stdout + result.stderr)
        (out / "cleanup.json").write_text(json.dumps({"exit_code": result.returncode,
                                                      "volume_removed": saved_backup and result.returncode == 0}) + "\n")


if __name__ == "__main__":
    main()
