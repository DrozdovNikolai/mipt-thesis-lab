import asyncio
from collections import Counter
import json
import random
import time
import httpx
from expanded.common import OUT, append, save, client, login


def oracle(data, historical=False):
    latest = {}
    for i, p in enumerate(data["assignment"]):
        if not historical or i < 2880:
            latest[p] = i
    return [
        dict(Counter(str((i // data["pilots"] + j) % 4 + 1) for i in latest.values()))
        for j in range(8)
    ], len(latest)


async def correctness():
    data = json.loads((OUT / "dataset.json").read_text())
    variants = ("original", "optimized", "projection", "incremental")
    filters = [
        {},
        {"asOfDate": "2020-01-02"},
        {"asOfDate": "2019-12-31"},
        {"pilotId": data["users"][0]["public_id"]},
        {"aircraftId": data["aircraft_id"]},
        {"positionId": data["position_id"]},
        {"ageFromYears": 30, "ageToYears": 40},
        {
            "asOfDate": "2020-01-02",
            "aircraftId": data["aircraft_id"],
            "positionId": data["position_id"],
        },
    ]
    references = {}
    for variant in variants:
        async with client(variant) as c:
            h = await login(c)
            for f in filters:
                r = await c.get("/_expanded/analytics", headers=h, params=f)
                assert r.status_code == 200, r.text
                key = json.dumps(f, sort_keys=True)
                actual = r.json()
                if variant == "original":
                    references[key] = actual
                else:
                    assert actual == references[key], (
                        variant,
                        f,
                        actual,
                        references[key],
                    )
                if f in ({}, {"asOfDate": "2020-01-02"}):
                    expected, trained = oracle(data, bool(f))
                    assert len(actual["items"]) == 8
                    assert actual["pilotsWithCompletedTraining"] == trained
                    for j, item in enumerate(actual["items"]):
                        counts = {
                            g["gradeCode"]: g["pilotCount"]
                            for g in item["grades"]
                            if g["pilotCount"]
                        }
                        assert counts == expected[j], (
                            variant,
                            f,
                            j,
                            counts,
                            expected[j],
                        )
                append(
                    "read-checks.jsonl", dict(variant=variant, filters=f, passed=True)
                )
    save("references.json", references)
    print("Read correctness and arithmetic oracle passed", flush=True)


async def block(rep, requests):
    from expanded.telemetry import quiet

    await quiet(f"reads-{OUT.name}-{rep}")
    references = json.loads((OUT / "references.json").read_text())
    groups = [(f, n) for f in ({}, {"asOfDate": "2020-01-02"}) for n in (1, 8)]
    random.Random(98000 + rep).shuffle(groups)
    for f, concurrency in groups:
        variants = ["original", "optimized", "projection", "incremental"]
        random.Random(rep + concurrency + len(f)).shuffle(variants)
        for variant in variants:
            async with client(variant) as c:
                h = await login(c)
                expected = references[json.dumps(f, sort_keys=True)]
                for _ in range(3):
                    r = await c.get("/_expanded/analytics", headers=h, params=f)
                    assert r.status_code == 200 and r.json() == expected
                before = (await c.get("/_expanded/resources", headers=h)).json()
                semaphore = asyncio.Semaphore(concurrency)

                async def one(i):
                    async with semaphore:
                        t = time.perf_counter()
                        try:
                            r = await c.get("/_expanded/analytics", headers=h, params=f)
                        except httpx.TransportError as error:
                            return dict(
                                request=i,
                                ms=(time.perf_counter() - t) * 1000,
                                status=0,
                                correct=False,
                                transport_error=type(error).__name__
                                + ": "
                                + str(error),
                            )
                        ms = (time.perf_counter() - t) * 1000
                        return dict(
                            request=i,
                            ms=ms,
                            status=r.status_code,
                            correct=r.status_code == 200 and r.json() == expected,
                        )

                start = time.perf_counter()
                rows = await asyncio.gather(*(one(i) for i in range(requests)))
                elapsed = time.perf_counter() - start
                after = (await c.get("/_expanded/resources", headers=h)).json()
                ctx = dict(rep=rep, variant=variant, filters=f, concurrency=concurrency)
                for row in rows:
                    append("read-http.jsonl", {**ctx, **row})
                assert all(r["correct"] for r in rows if r["status"] == 200), (
                    ctx,
                    rows,
                )
                successful = [r for r in rows if r["correct"]]
                append(
                    "read-series.jsonl",
                    {
                        **ctx,
                        "latencies_ms": [r["ms"] for r in successful],
                        "requests": requests,
                        "successful_requests": len(successful),
                        "errors": len(rows) - len(successful),
                        "seconds": elapsed,
                        "throughput": len(successful) / elapsed,
                        "backend_cpu_seconds": after["cpuSeconds"]
                        - before["cpuSeconds"],
                        "backend_pid": after["pid"],
                        "backend_instance": after["instanceId"],
                        "rss_kib": after["rssKib"],
                        "sql_delta": {
                            k: after["sql"][k] - before["sql"][k] for k in before["sql"]
                        },
                    },
                )
                print(
                    "READ",
                    OUT.name,
                    rep,
                    variant,
                    concurrency,
                    f,
                    round(requests / elapsed, 1),
                    flush=True,
                )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    p.add_argument("--rep", type=int, default=0)
    p.add_argument("--requests", type=int, default=20)
    a = p.parse_args()
    asyncio.run(correctness() if a.check else block(a.rep, a.requests))
