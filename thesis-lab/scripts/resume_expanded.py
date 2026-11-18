"""Reuse only completed phases verbatim; restart the interrupted H3 with fresh databases."""

from datetime import datetime, UTC
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from expanded.orchestrate import ROOT, freeze, run


def digest(folder):
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in folder.rglob("*")
        if p.is_file()
    }


def main(previous, name):
    root = ROOT / "results" / name
    os.environ["THESIS_QUIET_GATE"] = "1"
    freeze(
        root,
        dict(
            phase="expanded-all-continuation",
            resumed_from=str(previous),
            reused_phases=["h2", "transport", "browser"],
            reads=dict(profiles=6, repeats=10, requests=20),
            h2=dict(repeats=10),
            transport=dict(repeats=6, steps=6),
            browser=dict(repeats=2),
            mixed=dict(repeats=3, duration_s=30),
        ),
    )
    reuse = {}
    for phase in ("h2", "transport", "browser"):
        assert (previous / phase / "complete.json").exists() and not (
            previous / phase / "failure.json"
        ).exists()
        expected = digest(previous / phase)
        shutil.copytree(previous / phase, root / phase)
        assert digest(root / phase) == expected
        reuse[phase] = dict(source=str(previous / phase), sha256=expected)
    (root / "reused-phases.json").write_text(json.dumps(reuse, indent=2))
    shutil.copyfile(previous / "host-samples.jsonl", root / "host-samples.jsonl")
    interrupted = root / "prior-interruption"
    interrupted.mkdir()
    for path in (
        "failure.json",
        "reads/failure.json",
        "reads/history-1k/read-series.jsonl",
        "reads/history-1k/read-http.jsonl",
    ):
        shutil.copyfile(previous / path, interrupted / path.replace("/", "-"))
    shutil.copyfile(previous / "aborted-driver.log", interrupted / "driver.log")
    monitor = subprocess.Popen(
        [sys.executable, "-m", "expanded.telemetry", "--monitor"],
        cwd=ROOT,
        env={**os.environ, "THESIS_OUTPUT": str(root)},
    )
    try:
        for phase, repeats in (("reads", 10), ("mixed", 3)):
            print("PHASE", phase, datetime.now(UTC).isoformat(), flush=True)
            run(
                [
                    sys.executable,
                    "-m",
                    "expanded.orchestrate",
                    "--phase",
                    phase,
                    "--repeats",
                    str(repeats),
                    "--requests",
                    "20",
                    "--output",
                    str((root / phase).relative_to(ROOT / "results")),
                ]
            )
        (root / "complete.json").write_text(
            json.dumps(dict(completed_at=datetime.now(UTC).isoformat()))
        )
    except BaseException as exc:
        (root / "failure.json").write_text(
            json.dumps(dict(type=type(exc).__name__, message=str(exc)))
        )
        raise
    finally:
        monitor.terminate()
        monitor.wait()


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), sys.argv[2])
