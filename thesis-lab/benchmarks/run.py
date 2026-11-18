import asyncio
import argparse
from datetime import UTC, datetime
import platform

from benchmarks.common import OUT, save
from benchmarks import h1_sync, h2_scenarios, h3_analytics


async def main(phase):
    assert not (
        OUT / "run.json"
    ).exists(), f"Refusing to append to an existing run: {OUT}"
    config = dict(
        phase=phase,
        started_at=datetime.now(UTC).isoformat(),
        python=platform.python_version(),
        h1=dict(repeats=6, steps=12),
        h2=dict(repeats=6, sizes=[5, 25, 100]),
        h3=dict(repeats=6, sizes=[1000, 10000, 100000], requests=40),
    )
    save("run.json", config)
    try:
        if phase in ("all", "h1"):
            await h1_sync.main(**config["h1"])
        if phase in ("all", "h2"):
            await h2_scenarios.main(**config["h2"])
        if phase in ("all", "h3"):
            await h3_analytics.main(**config["h3"])
    except BaseException as exc:
        save(
            "failure.json",
            dict(
                type=type(exc).__name__,
                message=str(exc),
                time=datetime.now(UTC).isoformat(),
            ),
        )
        raise
    save("complete.json", dict(completed_at=datetime.now(UTC).isoformat()))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--phase", choices=["all", "h1", "h2", "h3"], default="all")
    asyncio.run(main(p.parse_args().phase))
