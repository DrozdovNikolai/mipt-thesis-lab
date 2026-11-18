"""Real HTTP comparison of snapshot/atomic patch/versioned CRUD and simultaneous editor sessions."""

import asyncio
import copy
import random
import time
from expanded.common import client, login, append
from benchmarks.common import UniqueFixtureClient
from tests.test_training_scenario_snapshot_apply import _setup_airline_and_admin_scope

HTTP_RECORDS = []


async def scenario(c, h, size):
    r = await c.post(
        "/api/training/scenarios",
        headers=h,
        json={"title": "Expanded thesis", "aircraftId": "A320"},
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    session_id = f"fixture-{sid}"
    snapshot = {
        "modules": [
            dict(
                id=-1,
                scenarioId=sid,
                orderIndex=0,
                dayStart=True,
                durationMinutes=120,
                exercises=[
                    dict(
                        id=-i - 2,
                        moduleId=-1,
                        orderIndex=i,
                        durationMinutes=5,
                        crewMemberNumber=1,
                        competenceIds=[],
                        params=None,
                        elements=[],
                    )
                    for i in range(size)
                ],
            )
        ]
    }
    r = await c.put(
        f"/api/training/scenarios/{sid}/snapshot",
        headers={**h, "X-Client-Session-Id": session_id},
        params={"expectedVersion": r.json()["contentVersion"]},
        json={"snapshot": snapshot},
    )
    assert r.status_code == 200, r.text
    await release(c, h, sid, session_id)
    return (await c.get(f"/api/training/scenarios/{sid}", headers=h)).json()


async def release(c, h, sid, session_id):
    r = await c.delete(
        f"/api/training/scenarios/{sid}/lock",
        headers={**h, "X-Client-Session-Id": session_id},
    )
    assert r.status_code in (204, 409, 423), r.text


async def send(c, h, variant, loaded, edits, session_id, ctx):
    """One logical attempt; complete HTTP bodies and wall time captured for every physical call."""
    sid = loaded["id"]
    version = loaded["contentVersion"]
    calls = []
    if variant == "snapshot":
        modules = copy.deepcopy(loaded["modules"])
        by_id = {e["id"]: e for m in modules for e in m["exercises"]}
        for eid, changes in edits:
            by_id[eid].update(changes)
        jobs = [
            (
                "PUT",
                f"/api/training/scenarios/{sid}/snapshot",
                {"snapshot": {"modules": modules}},
                {"expectedVersion": version},
            )
        ]
    elif variant == "patch":
        jobs = [
            (
                "POST",
                f"/_expanded/scenarios/{sid}/patch",
                {
                    "expectedVersion": version,
                    "edits": [{"exerciseId": eid, "changes": v} for eid, v in edits],
                },
                None,
            )
        ]
    else:
        jobs = [
            (
                "PUT",
                f"/api/training/exercises/{eid}",
                v,
                {"expectedVersion": version + i},
            )
            for i, (eid, v) in enumerate(edits)
        ]
    for method, url, body, params in jobs:
        req = c.build_request(
            method,
            url,
            headers={**h, "X-Client-Session-Id": session_id},
            json=body,
            params=params,
        )
        t = time.perf_counter()
        r = await c.send(req)
        ms = (time.perf_counter() - t) * 1000
        record = {
            **ctx,
            "method": method,
            "path": url,
            "status": r.status_code,
            "ms": ms,
            "bytes": len(req.content) + len(r.content),
            "error": r.text[:500] if r.status_code != 200 else None,
        }
        HTTP_RECORDS.append(record)
        calls.append(record)
        assert r.status_code in (200, 400, 404, 409, 422, 423), r.text
        if r.status_code != 200:
            break
    return calls


def fields(loaded):
    return {
        e["id"]: e["durationMinutes"] for m in loaded["modules"] for e in m["exercises"]
    }


async def correctness(c, h):
    for variant in ("snapshot", "patch", "crud"):
        loaded = await scenario(c, h, 5)
        sid = loaded["id"]
        ids = list(fields(loaded))
        bad = [
            (ids[0], {"durationMinutes": 7}),
            (
                ids[1],
                {
                    "durationMinutes": 9,
                    "elements": [{"elementId": 2147483000, "orderIndex": 0}],
                },
            ),
        ]
        calls = await send(
            c,
            h,
            variant,
            loaded,
            bad,
            "correctness",
            dict(kind="invalid_second", variant=variant),
        )
        after = (await c.get(f"/api/training/scenarios/{sid}", headers=h)).json()
        actual = fields(after)
        assert calls[-1]["status"] == 400, calls
        assert actual[ids[0]] == (7 if variant == "crud" else 5)
        assert actual[ids[1]] == 5
        if variant != "crud":
            assert after["contentVersion"] == loaded["contentVersion"]
        append(
            "h2-checks.jsonl",
            dict(check="domain_rollback", variant=variant, passed=True),
        )
    loaded = await scenario(c, h, 5)
    other = await scenario(c, h, 5)
    edits = [
        (list(fields(loaded))[0], {"durationMinutes": 7}),
        (list(fields(other))[0], {"durationMinutes": 9}),
    ]
    calls = await send(
        c,
        h,
        "patch",
        loaded,
        edits,
        "scope",
        dict(kind="cross_scenario", variant="patch"),
    )
    assert calls[-1]["status"] == 404, calls
    after = (await c.get(f"/api/training/scenarios/{loaded['id']}", headers=h)).json()
    assert (
        fields(after) == fields(loaded)
        and after["contentVersion"] == loaded["contentVersion"]
    )
    append(
        "h2-checks.jsonl",
        dict(check="cross_scenario_atomic_rejection", variant="patch", passed=True),
    )
    eid = next(iter(fields(loaded)))
    accepted = await send(
        c,
        h,
        "patch",
        loaded,
        [(eid, {"durationMinutes": 7})],
        "cas",
        dict(kind="valid_patch", variant="patch"),
    )
    assert accepted[-1]["status"] == 200
    current = (await c.get(f"/api/training/scenarios/{loaded['id']}", headers=h)).json()
    bad_cases = [
        ("stale_version", loaded, [(eid, {"durationMinutes": 9})], 409),
        (
            "duplicate_exercise",
            current,
            [(eid, {"durationMinutes": 9}), (eid, {"durationMinutes": 10})],
            400,
        ),
        (
            "move_outside_scenario",
            current,
            [(eid, {"moduleId": other["modules"][0]["id"]})],
            400,
        ),
    ]
    for check, source, changes, status in bad_cases:
        calls = await send(
            c, h, "patch", source, changes, "cas", dict(kind=check, variant="patch")
        )
        assert calls[-1]["status"] == status, calls
        actual = (
            await c.get(f"/api/training/scenarios/{loaded['id']}", headers=h)
        ).json()
        assert (
            fields(actual) == fields(current)
            and actual["contentVersion"] == current["contentVersion"]
        )
        append("h2-checks.jsonl", dict(check=check, variant="patch", passed=True))


async def performance(c, h, repeats):
    jobs = [
        (rep, size, count)
        for rep in range(repeats)
        for size in (5, 25, 100)
        for count in sorted({2, (size + 1) // 2})
    ]
    random.Random(91002).shuffle(jobs)
    for job_index, (rep, size, count) in enumerate(jobs):
        if job_index % 10 == 0:
            from expanded.telemetry import quiet

            await quiet(f"h2-performance-{job_index}")
        variants = ["crud", "snapshot", "patch"]
        random.Random(rep + size + count).shuffle(variants)
        for variant in variants:
            loaded = await scenario(c, h, size)
            sid = loaded["id"]
            ids = list(fields(loaded))
            edits = [
                (eid, {"durationMinutes": 7 + i}) for i, eid in enumerate(ids[:count])
            ]
            ctx = dict(kind="clean", rep=rep, size=size, edited=count, variant=variant)
            calls = await send(c, h, variant, loaded, edits, "perf", ctx)
            assert all(x["status"] == 200 for x in calls)
            after = (await c.get(f"/api/training/scenarios/{sid}", headers=h)).json()
            expected = fields(loaded)
            expected.update({eid: v["durationMinutes"] for eid, v in edits})
            assert fields(after) == expected
            assert after["contentVersion"] == loaded["contentVersion"] + (
                count if variant == "crud" else 1
            )
            append(
                "h2-performance.jsonl",
                {
                    **ctx,
                    "requests": len(calls),
                    "http_ms": sum(x["ms"] for x in calls),
                    "bytes": sum(x["bytes"] for x in calls),
                    "correct": True,
                },
            )
        print("H2 expanded performance", rep, size, count, flush=True)


async def concurrent(c, h, repeats):
    jobs = [
        (rep, n, overlap, lease)
        for rep in range(repeats)
        for n in (2, 4)
        for overlap in (False, True)
        for lease in ("shared_session", "distinct_sessions")
    ]
    random.Random(92002).shuffle(jobs)
    for job_index, (rep, n, overlap, lease) in enumerate(jobs):
        if job_index % 10 == 0:
            from expanded.telemetry import quiet

            await quiet(f"h2-concurrent-{job_index}")
        variants = ["crud", "snapshot", "patch"]
        random.Random(rep + n + int(overlap)).shuffle(variants)
        for variant in variants:
            loaded = await scenario(c, h, 25)
            sid = loaded["id"]
            ids = list(fields(loaded))
            base = fields(loaded)
            intents = [
                [
                    (
                        ids[(0 if overlap else 2 * i) + j],
                        {"durationMinutes": 10 + 2 * i + j},
                    )
                    for j in (0, 1)
                ]
                for i in range(n)
            ]
            sessions = [
                "shared" if lease == "shared_session" else f"editor-{i}"
                for i in range(n)
            ]
            gate = asyncio.Event()
            calls = [[] for _ in range(n)]
            outcomes = [None] * n
            start = time.perf_counter()
            ctx = dict(
                rep=rep, editors=n, overlap=overlap, lease=lease, variant=variant
            )

            async def attempt(i, state, round_no):
                async with client() as editor:
                    await gate.wait()
                    result = await send(
                        editor,
                        h,
                        variant,
                        state,
                        intents[i],
                        sessions[i],
                        {**ctx, "editor": i, "attempt": round_no},
                    )
                    calls[i].extend(result)
                    if lease == "distinct_sessions":
                        await release(editor, h, sid, sessions[i])
                    return all(x["status"] == 200 for x in result)

            tasks = [asyncio.create_task(attempt(i, loaded, 0)) for i in range(n)]
            gate.set()
            done = await asyncio.gather(*tasks)
            observed = (await c.get(f"/api/training/scenarios/{sid}", headers=h)).json()
            initial = fields(observed)
            partial = sum(
                0
                < sum(initial[eid] == v["durationMinutes"] for eid, v in intent)
                < len(intent)
                for intent in intents
            )
            if variant != "crud":
                assert partial == 0, (ctx, initial)

            async def finish(i):
                if done[i]:
                    return "saved"
                for turn in range(1, 21):
                    state = (
                        await c.get(f"/api/training/scenarios/{sid}", headers=h)
                    ).json()
                    current = fields(state)
                    if any(
                        current[eid] not in (base[eid], v["durationMinutes"])
                        for eid, v in intents[i]
                    ):
                        return "field_conflict"
                    if await attempt(i, state, turn):
                        return "saved"
                    await asyncio.sleep(0.005 * (i + 1))
                return "retry_exhausted"

            outcomes = await asyncio.gather(*(finish(i) for i in range(n)))
            elapsed = (time.perf_counter() - start) * 1000
            final = fields(
                (await c.get(f"/api/training/scenarios/{sid}", headers=h)).json()
            )
            assert "retry_exhausted" not in outcomes, (ctx, outcomes)
            for i, outcome in enumerate(outcomes):
                if outcome == "saved":
                    assert all(
                        final[eid] == v["durationMinutes"] for eid, v in intents[i]
                    ), (ctx, final, outcomes)
            assert outcomes.count("saved") == (1 if overlap else n), (ctx, outcomes)
            flat = [x for group in calls for x in group]
            append(
                "h2-concurrent.jsonl",
                {
                    **ctx,
                    "initial_partial_intents": partial,
                    "outcomes": outcomes,
                    "saved": outcomes.count("saved"),
                    "field_conflicts": outcomes.count("field_conflict"),
                    "requests": len(flat),
                    "request_conflicts": sum(x["status"] in (409, 423) for x in flat),
                    "version_conflicts_409": sum(x["status"] == 409 for x in flat),
                    "lease_conflicts_423": sum(x["status"] == 423 for x in flat),
                    "bytes": sum(x["bytes"] for x in flat),
                    "completion_ms": elapsed,
                    "correct": True,
                },
            )
        print("H2 concurrency", rep, n, overlap, lease, flush=True)


async def main(repeats):
    async with client() as c:
        h = await login(c)
        await _setup_airline_and_admin_scope(UniqueFixtureClient(c), h)
        try:
            await correctness(c, h)
            await performance(c, h, repeats)
            await concurrent(c, h, repeats)
        finally:
            for record in HTTP_RECORDS:
                append("h2-http.jsonl", record)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--repeats", type=int, default=10)
    asyncio.run(main(p.parse_args().repeats))
