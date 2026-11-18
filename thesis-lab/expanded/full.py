"""Run the fixed expansion matrix sequentially and preserve partial failures."""

from datetime import datetime, UTC
import json
import os
import subprocess
import sys
from expanded.orchestrate import ROOT, compose, freeze, inside, run


def main(name):
    output = ROOT / "results" / name
    os.environ["THESIS_QUIET_GATE"] = "1"
    freeze(
        output,
        dict(
            phase="expanded-all",
            reads=dict(profiles=6, repeats=10, requests=20),
            h2=dict(repeats=10),
            transport=dict(repeats=6, steps=6),
            browser=dict(repeats=2),
            mixed=dict(repeats=3, duration_s=30),
        ),
    )
    monitor = subprocess.Popen(
        [sys.executable, "-m", "expanded.telemetry", "--monitor"],
        cwd=ROOT,
        env={**os.environ, "THESIS_OUTPUT": str(output)},
    )
    try:
        compose("stop", "original", "optimized", "projection", "worker", "seed")
        for phase in ("h2", "transport", "browser", "reads", "mixed"):
            print("PHASE", phase, datetime.now(UTC).isoformat(), flush=True)
            target = output / phase
            if phase in ("h2", "reads", "mixed"):
                run(
                    [
                        sys.executable,
                        "-m",
                        "expanded.orchestrate",
                        "--phase",
                        phase,
                        "--repeats",
                        "3" if phase == "mixed" else "10",
                        "--requests",
                        "20",
                        "--output",
                        str(target.relative_to(ROOT / "results")),
                    ]
                )
            else:
                freeze(
                    target,
                    dict(
                        phase=phase, repeats=6 if phase == "transport" else 2, steps=6
                    ),
                )
                env = {
                    **os.environ,
                    "THESIS_OUTPUT": "/results/"
                    + str(target.relative_to(ROOT / "results")),
                }
                compose(
                    "up",
                    "-d",
                    "--wait",
                    "--force-recreate",
                    "functional",
                    "proxy",
                    env=env,
                )
                if phase == "transport":
                    inside(
                        target,
                        "expanded.h1_transport",
                        "--repeats",
                        "6",
                        "--steps",
                        "6",
                    )
                else:
                    run(["node", "expanded/browser.mjs", str(target), "2"])
                (target / "complete.json").write_text(
                    json.dumps(dict(completed_at=datetime.now(UTC).isoformat()))
                )
        (output / "complete.json").write_text(
            json.dumps(dict(completed_at=datetime.now(UTC).isoformat()))
        )
    except BaseException as exc:
        (output / "failure.json").write_text(
            json.dumps(dict(type=type(exc).__name__, message=str(exc)))
        )
        raise
    finally:
        monitor.terminate()
        monitor.wait()


if __name__ == "__main__":
    main(sys.argv[1])
