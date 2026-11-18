"""ASR smoke and crash recovery on an isolated Docker Compose project."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ENV = Path.home() / ".local/share/firefly-thesis/h2-local-20261005/runtime.env"
PROJECT = "firefly-thesis-h2-20261005"


def compose(*args, **kwargs):
    return subprocess.run(["docker", "compose", "-p", PROJECT, "--env-file", str(ENV),
        "-f", str(ROOT / "h2/compose.local.yml"), *args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=False, parents=True)
    ENV.parent.mkdir(parents=True, exist_ok=True)
    if not ENV.exists():
        with ENV.open("x") as stream:
            stream.write("H2_API_TOKEN=" + secrets.token_hex(32) + "\n")
    ENV.chmod(0o600)
    token = ENV.read_text().strip().split("=", 1)[1]

    def api(path, payload=None):
        req = urllib.request.Request("http://127.0.0.1:18082" + path,
             data=json.dumps(payload).encode() if payload is not None else None,
             headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3 if path == "/health" else 30) as r:
            return json.load(r)

    def wait_done(task_id, seconds=300):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            snapshot = api("/snapshot")
            row = next(t for t in snapshot["tasks"] if t["id"] == task_id)
            if row["state"] == "done":
                return row
            time.sleep(1)
        raise RuntimeError("Task did not finish: " + task_id)

    compose("up", "-d", "coordinator")
    try:
        for _ in range(60):
            try:
                api("/health")
                break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("Coordinator unavailable")
        if api("/snapshot")["tasks"]:
            raise RuntimeError("Local queue is not empty; preserve evidence and use a new project")
        raw = compose("exec", "-T", "coordinator", "cat", "/fixtures/manifest.json", capture_output=True, text=True).stdout
        manifest = json.loads(raw)
        (args.output / "fixtures.json").write_text(raw)
        compose("--profile", "worker", "up", "-d", "worker")
        references = {}
        for name, metadata in manifest["fixtures"].items():
            task_id = "reference-" + name
            api("/admit/" + task_id, {"payload": {"fixture": name, **metadata}, "deadline_seconds": 300})
            row = wait_done(task_id)
            references[name] = {"result_sha": row["result_sha"], "result": json.loads(row["result"]),
                                "processing_seconds": row["completed_at"] - row["first_started_at"]}
            print("REFERENCE", name, round(references[name]["processing_seconds"], 3), flush=True)
        (args.output / "references.json").write_text(json.dumps(references, indent=2))
        for name, metadata in manifest["fixtures"].items():
            task_id = "repeat-" + name
            api("/admit/" + task_id, {"payload": {"fixture": name, **metadata}, "deadline_seconds": 300,
                                     "expected_sha": references[name]["result_sha"]})
            row = wait_done(task_id)
            if row["result_sha"] != row["expected_sha"]:
                raise RuntimeError("Repeated ASR changed result: " + name)
            print("PARITY", name, flush=True)
        # The adapter exits with 77 after genuine ASR but before completion commit.
        name = "pilot-30"
        api("/admit/crash-1", {"payload": {"fixture": name, **manifest["fixtures"][name],
            "crash_after_asr_first_attempt": True}, "deadline_seconds": 180,
            "expected_sha": references[name]["result_sha"]})
        worker = compose("ps", "-q", "worker", capture_output=True, text=True).stdout.strip()
        for _ in range(90):
            status = json.loads(subprocess.check_output(["docker", "inspect", worker, "--format", "{{json .State}}"], text=True))
            if not status["Running"]:
                break
            time.sleep(1)
        if status["ExitCode"] != 77:
            raise RuntimeError("Injected process crash did not occur")
        (args.output / "crash-process.json").write_text(json.dumps(status, indent=2))
        with (args.output / "worker-before-crash.log").open("w") as stream:
            compose("logs", "--no-color", "worker", stdout=stream, stderr=subprocess.STDOUT)
        # A new process/container identity must receive the retried task.
        compose("--profile", "worker", "up", "-d", "--force-recreate", "worker")
        row = wait_done("crash-1")
        assert row["attempts"] == 2 and row["result_sha"] == row["expected_sha"]
        snapshot = api("/snapshot")
        (args.output / "snapshot.json").write_text(json.dumps(snapshot, indent=2))
        summary = {"passed": True, "reference_tasks": len(references), "parity_tasks": len(references),
                   "crash_recovery_tasks": 1, "all_done": all(t["state"] == "done" for t in snapshot["tasks"]),
                   "note": "Local integration smoke on shared WSL; not cloud performance evidence"}
        (args.output / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)
    except BaseException as error:
        (args.output / "failure.json").write_text(json.dumps({"type": type(error).__name__, "error": str(error)}, indent=2))
        try:
            (args.output / "snapshot-failure.json").write_text(json.dumps(api("/snapshot"), indent=2))
        except Exception:
            pass
        raise
    finally:
        with (args.output / "compose.log").open("w") as stream:
            compose("logs", "--no-color", stdout=stream, stderr=subprocess.STDOUT)
        compose("stop", "--timeout", "60", "worker", "coordinator")


if __name__ == "__main__":
    main()
