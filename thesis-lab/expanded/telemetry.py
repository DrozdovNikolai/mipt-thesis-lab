"""Predeclared admission gate; never discards measurements after seeing outcomes."""

import asyncio
import json
import os
from pathlib import Path
import time


def sample():
    values = list(map(int, Path("/proc/stat").read_text().splitlines()[0].split()[1:9]))
    return dict(
        time=time.time(),
        load1=os.getloadavg()[0],
        cpus=os.cpu_count(),
        ticks=sum(values),
        idle_ticks=values[3],
        iowait_ticks=values[4],
    )


def record(name, row):
    out = Path(os.environ.get("THESIS_OUTPUT", "/results/expanded-pilot"))
    out.mkdir(parents=True, exist_ok=True)
    with (out / name).open("a") as f:
        f.write(json.dumps(row) + "\n")


async def quiet(label):
    if os.environ.get("THESIS_QUIET_GATE") != "1":
        return
    consecutive = 0
    previous = sample()
    while consecutive < 3:
        await asyncio.sleep(2)
        current = sample()
        idle = (current["idle_ticks"] - previous["idle_ticks"]) / max(
            1, current["ticks"] - previous["ticks"]
        )
        accepted = idle >= 0.65 and current["load1"] <= current["cpus"]
        consecutive = consecutive + 1 if accepted else 0
        record(
            "admission.jsonl",
            dict(
                **current,
                label=label,
                idle_fraction=idle,
                accepted=accepted,
                consecutive=consecutive
            ),
        )
        previous = current
    print("QUIET HOST admitted", label, flush=True)


async def monitor():
    while True:
        record("host-samples.jsonl", sample())
        await asyncio.sleep(1)


if __name__ == "__main__":
    import sys

    asyncio.run(monitor() if "--monitor" in sys.argv else quiet(" ".join(sys.argv[1:])))
