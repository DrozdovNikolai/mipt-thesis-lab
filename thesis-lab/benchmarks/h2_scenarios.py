"""Versioned snapshots vs real legacy CRUD. Logical operation: edit two exercises."""

import asyncio
import copy
import random
from benchmarks.common import append, client, login, measured, UniqueFixtureClient
from tests.test_training_scenario_snapshot_apply import _setup_airline_and_admin_scope


async def main(repeats=2, sizes=(5, 25, 100)):
    async with client() as c:
        headers = await login(c)
        await _setup_airline_and_admin_scope(UniqueFixtureClient(c), headers)
        jobs = [
            (rep, size, fault)
            for rep in range(repeats)
            for size in sizes
            for fault in (
                "clean",
                "invalid_second",
                "interrupted_between",
                "stale_writer",
            )
        ]
        random.Random(260916).shuffle(jobs)
        for rep, size, fault in jobs:
            variants = ["crud_legacy", "crud_versioned", "snapshot"]
            random.Random(rep + size + len(fault)).shuffle(variants)
            for variant in variants:
                r = await c.post(
                    "/api/training/scenarios",
                    headers=headers,
                    json={"title": "Thesis H2", "aircraftId": "A320"},
                )
                assert r.status_code == 201, r.text
                sid = r.json()["id"]
                version = r.json()["contentVersion"]
                url = f"/api/training/scenarios/{sid}"
                h = {**headers, "X-Client-Session-Id": f"thesis-{sid}"}
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
                    url + "/snapshot",
                    params={"expectedVersion": version},
                    headers=h,
                    json={"snapshot": snapshot},
                )
                assert r.status_code == 200, r.text
                loaded = (await c.get(url, headers=headers)).json()
                version = loaded["contentVersion"]
                old = loaded["modules"]
                new = copy.deepcopy(old)
                new[0]["exercises"][0]["durationMinutes"] = 7
                new[0]["exercises"][1]["durationMinutes"] = 9
                ctx = dict(
                    hypothesis="H2",
                    rep=rep,
                    size=size,
                    fault=fault,
                    variant=variant,
                    scenario_id=sid,
                )
                expected = [5] * size
                statuses = []
                byte_count = 0
                elapsed = 0
                # A previously accepted other edit must survive an old writer.
                if fault == "stale_writer":
                    r = await c.put(
                        f"/api/training/exercises/{old[0]['exercises'][0]['id']}",
                        headers=h,
                        params={"expectedVersion": version},
                        json={"durationMinutes": 11},
                    )
                    assert r.status_code == 200, r.text
                    expected[0] = 11
                if fault == "invalid_second":
                    # Valid request schema but a reference to an absent library element:
                    # failure happens inside domain validation/transaction, not HTTP parsing.
                    new[0]["exercises"][1]["elements"] = [
                        {"elementId": 2147483000, "orderIndex": 0}
                    ]
                if variant == "snapshot":
                    if fault != "interrupted_between":
                        r, elapsed, byte_count = await measured(
                            c,
                            "PUT",
                            url + "/snapshot",
                            {"snapshot": {"modules": new}},
                            h,
                            ctx,
                            params={"expectedVersion": version},
                        )
                        statuses.append(r.status_code)
                    # Crash before the single request is delivered: no partial logical edit.
                else:
                    for i in (0, 1):
                        if i == 1 and fault == "interrupted_between":
                            break
                        body = {"durationMinutes": 7 if i == 0 else 9}
                        if i == 1 and fault == "invalid_second":
                            body["elements"] = new[0]["exercises"][1]["elements"]
                        kwargs = (
                            {}
                            if variant == "crud_legacy"
                            else {"params": {"expectedVersion": version + i}}
                        )
                        r, lat, b = await measured(
                            c,
                            "PUT",
                            f"http://baseline:8000/api/training/exercises/{old[0]['exercises'][i]['id']}",
                            body,
                            headers if variant == "crud_legacy" else h,
                            ctx,
                            **kwargs,
                        )
                        elapsed += lat
                        byte_count += b
                        statuses.append(r.status_code)
                        if r.status_code != 200:
                            break
                actual = [
                    e["durationMinutes"]
                    for e in (await c.get(url, headers=headers)).json()["modules"][0][
                        "exercises"
                    ]
                ]
                if fault == "clean":
                    expected[:2] = [7, 9]
                    assert actual == expected, (ctx, actual)
                else:
                    assert statuses == [] or all(
                        s in (200, 400, 409, 422) for s in statuses
                    ), (ctx, statuses)
                target = [7, 9] + [5] * (size - 2)
                partial = actual != expected and actual != target
                lost = fault == "stale_writer" and actual[0] != 11
                if variant == "snapshot" and fault != "clean":
                    assert actual == expected, (ctx, actual)
                append(
                    "h2.jsonl",
                    {
                        **ctx,
                        "body_bytes": byte_count,
                        "save_ms": elapsed,
                        "requests": len(statuses),
                        "partial": partial,
                        "lost_update": lost,
                        "conflict_detected": 409 in statuses,
                        "statuses": statuses,
                        "correct_expected_state": actual == expected,
                        "actual_durations": actual[:2],
                    },
                )
                print(
                    "H2",
                    rep,
                    size,
                    fault,
                    variant,
                    round(elapsed),
                    partial,
                    lost,
                    flush=True,
                )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--sizes", default="5,25,100")
    a = p.parse_args()
    asyncio.run(main(a.repeats, tuple(map(int, a.sizes.split(",")))))
