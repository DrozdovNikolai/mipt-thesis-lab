"""Fixed arrival schedules, real correction API, full read endpoint, and filtered visibility observers."""

import asyncio
from datetime import datetime
import json
import random
import time
from expanded.common import OUT, client, login, append


async def drain(c, h, timeout=120):
    until = time.perf_counter() + timeout
    while time.perf_counter() < until:
        r = await c.get("/_expanded/queue", headers=h)
        assert r.status_code == 200, r.text
        if r.json()["pending"] == 0:
            return
        await asyncio.sleep(0.2)
    raise AssertionError("Projection failed to converge after mixed load")


async def case(data, rep, rate, variant, crash, duration):
    from expanded.telemetry import quiet

    await quiet(f"mixed-{rep}-{rate}-{variant}-{crash}")
    ctx = dict(
        rep=rep,
        write_rate=rate,
        read_rate=4,
        variant=variant,
        crash=crash,
        duration_s=duration,
    )
    async with client(variant) as c:
        h = await login(c)
        await drain(c, h)
        worker_before = (await c.get("/_expanded/queue", headers=h)).json()
        probes = data["probes"][: int(duration * rate)]
        assert len(probes) == int(duration * rate)
        r = await c.post(
            "/_expanded/probe-state",
            headers=h,
            json={"report_ids": [x["report_id"] for x in probes]},
        )
        assert r.status_code == 200, r.text
        current = {x["reportId"]: x["grade"] for x in r.json()["items"]}
        preflight = await c.post(
            "/_expanded/correction",
            headers=h,
            json={
                "report_id": probes[-1]["report_id"],
                "grade": current[probes[-1]["report_id"]],
            },
        )
        assert preflight.status_code == 200, preflight.text
        await drain(c, h)
        for _ in range(3):
            r = await c.get("/_expanded/analytics", headers=h)
            assert r.status_code == 200, r.text
        before = (await c.get("/_expanded/resources", headers=h)).json()
        start = time.perf_counter() + 0.1
        writes = []
        reads = []
        samples = []
        write_sem = asyncio.Semaphore(16)
        read_sem = asyncio.Semaphore(8)
        finished = asyncio.Event()

        async def wait_until(offset):
            await asyncio.sleep(max(0, start + offset - time.perf_counter()))

        async def observe(probe, grade, confirmed, acknowledged):
            count = 0
            deadline = time.perf_counter() + 45
            last_status = None
            while time.perf_counter() < deadline:
                r = await c.get(
                    "/_expanded/analytics",
                    headers=h,
                    params={"pilotId": probe["public_id"], "observed": True},
                )
                count += 1
                last_status = r.status_code
                if r.status_code == 200:
                    items = r.json()["items"]
                    item = next(
                        x for x in items if x["competenceId"] == probe["competence_id"]
                    )
                    visible = any(
                        x["gradeCode"] == grade and x["pilotCount"] == 1
                        for x in item["grades"]
                    )
                    if visible:
                        observed = datetime.fromisoformat(
                            r.headers["X-Thesis-Observed-At"]
                        )
                        ms = (
                            observed - datetime.fromisoformat(confirmed)
                        ).total_seconds() * 1000
                        return dict(
                            visible=True,
                            freshness_ms=(time.perf_counter() - acknowledged) * 1000,
                            pg_freshness_ms=ms,
                            pg_clock_anomaly=ms < 0,
                            commit_confirmed_at=confirmed,
                            observed_at=r.headers["X-Thesis-Observed-At"],
                            observer_requests=count,
                        )
                await asyncio.sleep(0.1)
            return dict(
                visible=False,
                freshness_ms=None,
                observer_requests=count,
                last_status=last_status,
                censored_after_s=45,
            )

        async def write_one(i, probe):
            await wait_until(i / rate)
            scheduled = start + i / rate
            async with write_sem:
                issued = time.perf_counter()
                grade = str(int(current[probe["report_id"]]) % 4 + 1)
                r = await c.post(
                    "/_expanded/correction",
                    headers=h,
                    json={"report_id": probe["report_id"], "grade": grade},
                )
                ended = time.perf_counter()
                row = dict(
                    index=i,
                    report_id=probe["report_id"],
                    pilot_id=probe["public_id"],
                    grade=grade,
                    status=r.status_code,
                    http_ms=(ended - issued) * 1000,
                    scheduled_to_ack_ms=(ended - scheduled) * 1000,
                    driver_wait_ms=(issued - scheduled) * 1000,
                    offset_s=issued - start,
                )
            if r.status_code == 200:
                row.update(
                    await observe(probe, grade, r.json()["commitConfirmedAt"], ended)
                )
            else:
                row.update(
                    visible=False,
                    freshness_ms=None,
                    error=r.text[:500],
                    observer_requests=0,
                )
            writes.append(row)

        async def read_one(i):
            await wait_until(i / 4)
            scheduled = start + i / 4
            async with read_sem:
                issued = time.perf_counter()
                r = await c.get("/_expanded/analytics", headers=h)
                ended = time.perf_counter()
                reads.append(
                    dict(
                        index=i,
                        status=r.status_code,
                        http_ms=(ended - issued) * 1000,
                        scheduled_to_response_ms=(ended - scheduled) * 1000,
                        driver_wait_ms=(issued - scheduled) * 1000,
                        offset_s=issued - start,
                    )
                )

        async def sample_queue():
            await wait_until(0)
            while not finished.is_set():
                r = await c.get("/_expanded/queue", headers=h)
                assert r.status_code == 200, r.text
                samples.append(dict(offset_s=time.perf_counter() - start, **r.json()))
                await asyncio.sleep(0.25)

        async def crash_worker():
            if crash:
                await wait_until(duration / 3)
                r = await c.post("/_expanded/worker-crash", headers=h)
                assert r.status_code == 200, r.text

        sampler = asyncio.create_task(sample_queue())
        jobs = [asyncio.create_task(write_one(i, p)) for i, p in enumerate(probes)]
        jobs += [asyncio.create_task(read_one(i)) for i in range(int(duration * 4))]
        jobs += [asyncio.create_task(crash_worker())]
        try:
            await asyncio.gather(*jobs)
            await drain(c, h)
        finally:
            finished.set()
            await sampler
        ended = time.perf_counter()
        after = (await c.get("/_expanded/resources", headers=h)).json()
        worker_after = (await c.get("/_expanded/queue", headers=h)).json()
        assert any(
            r["status"] == 200 for r in writes
        ), "No writes accepted: invalid mixed workload"
        if crash:
            assert worker_after["crashes"] == worker_before["crashes"] + 1, (
                worker_before,
                worker_after,
            )
            assert worker_after["workerPid"] != worker_before["workerPid"], (
                worker_before,
                worker_after,
            )
            assert worker_after["crashRequested"] is False
        for r in writes:
            append("mixed-writes.jsonl", {**ctx, **r})
        for r in reads:
            append("mixed-reads.jsonl", {**ctx, **r})
        for r in samples:
            append("mixed-queue.jsonl", {**ctx, **r})
        # Recheck each acknowledged update after queue drain. No later write touches the same pilot within this case.
        for row in writes:
            if row["status"] != 200:
                continue
            r = await c.get(
                "/_expanded/analytics", headers=h, params={"pilotId": row["pilot_id"]}
            )
            assert r.status_code == 200, r.text
            item = next(
                x
                for x in r.json()["items"]
                if x["competenceId"] == data["competences"][0]
            )
            assert any(
                g["gradeCode"] == row["grade"] and g["pilotCount"] == 1
                for g in item["grades"]
            )
        append(
            "mixed-series.jsonl",
            {
                **ctx,
                "writes": len(writes),
                "reads": len(reads),
                "write_errors": sum(r["status"] != 200 for r in writes),
                "read_errors": sum(r["status"] != 200 for r in reads),
                "not_visible_before_deadline": sum(not r["visible"] for r in writes),
                "observer_requests": sum(r["observer_requests"] for r in writes),
                "elapsed_s": ended - start,
                "backend_cpu_seconds": after["cpuSeconds"] - before["cpuSeconds"],
                "rss_kib": after["rssKib"],
                "sql_delta": {
                    k: after["sql"][k] - before["sql"][k] for k in before["sql"]
                },
                "converged": True,
                "worker_before": worker_before,
                "worker_after": worker_after,
            },
        )
        print(
            "MIXED",
            ctx,
            "writes",
            len(writes),
            "seconds",
            round(ended - start, 1),
            flush=True,
        )


async def main(repeats, duration):
    data = json.loads((OUT / "dataset.json").read_text())
    jobs = [
        (rep, rate, v, False)
        for rep in range(repeats)
        for rate in (1, 8)
        for v in ("original", "optimized", "projection", "incremental")
    ]
    random.Random(93003).shuffle(jobs)
    jobs += [(0, rate, variant, True) for rate in (1, 8) for variant in ("projection", "incremental")]
    for rep, rate, v, crash in jobs:
        await case(data, rep, rate, v, crash, duration)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--duration", type=float, default=30)
    a = p.parse_args()
    asyncio.run(main(a.repeats, a.duration))
