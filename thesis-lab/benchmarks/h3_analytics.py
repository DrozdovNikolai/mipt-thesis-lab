import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import random
import time
import uuid
import sys

from sqlalchemy import insert, select, text
from app.db.session import AsyncSessionLocal
from app.modules.training import models
from app.modules.training.assessment_models import (
    TrainingSession,
    CrewMemberAssessment,
    FinalReport,
)
from app.modules.users.models import User, UserInfo, UserAircraft, AirlinePosition
from app.modules.commander import analytics_projection as projection
from benchmarks.common import append, client, login


async def seed(c, headers, n, pilots):
    tag = uuid.uuid4().hex[:8]
    r = await c.post(
        "/api/training/airlines",
        headers=headers,
        json={"code": "H" + tag, "name": "Thesis analytics", "active": True},
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    owner = (await c.get("/api/auth/me", headers=headers)).json()["id"]
    r = await c.put(
        "/api/users/" + owner,
        headers=headers,
        json={"airlineId": aid, "aircraftIds": ["A320"]},
    )
    assert r.status_code == 200, r.text
    async with AsyncSessionLocal() as s:
        admin = await s.scalar(select(User).where(User.public_id == uuid.UUID(owner)))
        ac = await s.scalar(
            select(models.AircraftAirline).where(
                models.AircraftAirline.airline_id == aid
            )
        )
        ac2 = models.AircraftAirline(airline_id=aid, code="B737", name="B737")
        s.add(ac2)
        pos = AirlinePosition(
            airline_id=aid, name="Thesis Captain", normalized_name="thesis captain"
        )
        s.add(pos)
        scheme = await s.scalar(
            select(models.GradingScheme).where(
                models.GradingScheme.airline_id == aid,
                models.GradingScheme.is_active == True,
            )
        )
        comps = [
            models.Competence(
                airline_id=aid,
                code=f"TC{i}",
                name=f"Thesis competency {i}",
                order_index=i,
            )
            for i in range(8)
        ]
        s.add_all(comps)
        await s.flush()
        users = list(
            (
                await s.execute(
                    insert(User.__table__).returning(User.id, User.public_id),
                    [
                        dict(
                            public_id=uuid.uuid4(),
                            login=f"{tag}-{i}",
                            email=f"{tag}-{i}@example.com",
                            hashed_password="!synthetic-no-login",
                            airline_id=aid,
                        )
                        for i in range(pilots)
                    ],
                )
            ).all()
        )
        await s.execute(
            insert(UserInfo.__table__),
            [
                dict(
                    id=u.id,
                    first_name="Synthetic",
                    last_name=str(i),
                    date_of_birth=date(1980 + i % 20, 1, 1),
                    position_id=pos.id if i % 2 else None,
                )
                for i, u in enumerate(users)
            ],
        )
        await s.execute(
            insert(UserAircraft.__table__),
            [
                dict(user_id=u.id, aircraft_id=ac.id if i % 2 else ac2.id)
                for i, u in enumerate(users)
            ],
        )
        await s.commit()
        for start in range(0, n, 1000):
            batch = list(range(start, min(n, start + 1000)))
            times = [
                datetime(2020, 1, 1, tzinfo=UTC) + timedelta(minutes=i) for i in batch
            ]
            tids = list(
                (
                    await s.execute(
                        insert(TrainingSession.__table__).returning(TrainingSession.id),
                        [
                            dict(
                                instructor_id=admin.id,
                                grading_scheme_id=scheme.id,
                                status="COMPLETED",
                                submission_status="COMPLETED",
                                completed_at=t,
                                created_at=t,
                                updated_at=t,
                                comment_contract_version=0,
                            )
                            for t in times
                        ],
                    )
                ).scalars()
            )
            assids = list(
                (
                    await s.execute(
                        insert(CrewMemberAssessment.__table__).returning(
                            CrewMemberAssessment.id
                        ),
                        [
                            dict(
                                training_session_id=t,
                                user_id=users[i % pilots].id,
                                training_role="cm1",
                                created_at=ts,
                                updated_at=ts,
                            )
                            for i, t, ts in zip(batch, tids, times)
                        ],
                    )
                ).scalars()
            )
            await s.execute(
                insert(FinalReport.__table__),
                [
                    dict(
                        assessment_id=assid,
                        competence_id=comp.id,
                        grade=str((i // pilots + j) % 4 + 1),
                        grade_code_snapshot=str((i // pilots + j) % 4 + 1),
                        grade_label_snapshot=f"Grade {(i//pilots+j)%4+1}",
                        grade_score_snapshot=Decimal((i // pilots + j) % 4 + 1),
                        grade_color_hex_snapshot="#123456",
                        created_at=ts,
                        updated_at=ts,
                    )
                    for i, assid, ts in zip(batch, assids, times)
                    for j, comp in enumerate(comps)
                ],
            )
            await s.commit()
        await s.execute(text("ANALYZE"))
        await s.commit()
        return dict(
            airline_id=aid,
            users=[dict(id=u.id, public_id=str(u.public_id)) for u in users],
            aircraft_id=ac.id,
            position_id=pos.id,
            competences=[x.id for x in comps],
            n=n,
            pilots=pilots,
        )


async def drain():
    rows = []
    async with AsyncSessionLocal() as s:
        while batch := await projection.process_batch(s, 100):
            rows.extend(batch)
    return rows


async def compare(c, headers, params):
    a = await c.get(
        "http://baseline:8000/_thesis/analytics/baseline",
        headers=headers,
        params=params,
    )
    b = await c.get("/_thesis/analytics/projection", headers=headers, params=params)
    assert a.status_code == 200, a.text
    assert b.status_code == 200, b.text
    assert a.json() == b.json(), (params, a.text, b.text)
    return a.json()


async def correctness(c, headers, data):
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
    for f in filters:
        await compare(c, headers, f)
    response = await compare(c, headers, {})
    # Independent arithmetic oracle for synthetic initial latest-per-pilot grades.
    for j, item in enumerate(response["items"]):
        counts = {str(k): 0 for k in range(1, 5)}
        for p in range(min(data["n"], data["pilots"])):
            last = p + (data["n"] - 1 - p) // data["pilots"] * data["pilots"]
            counts[str((last // data["pilots"] + j) % 4 + 1)] += 1
        actual = {
            x["gradeCode"]: x["pilotCount"] for x in item["grades"] if x["pilotCount"]
        }
        assert actual == {k: v for k, v in counts.items() if v}, (actual, counts)
    append(
        "h3-checks.jsonl",
        dict(
            check="initial_filters_and_independent_oracle",
            size=data["n"],
            passed=True,
            count=len(filters) + 1,
        ),
    )


async def mutations(c, headers, data):
    uid = data["users"][0]["id"]
    async with AsyncSessionLocal() as s:
        assid = await s.scalar(
            text(
                "SELECT assessment_id FROM commander_latest_assessment WHERE user_id=:u"
            ),
            {"u": uid},
        )
        tid = await s.scalar(
            select(CrewMemberAssessment.training_session_id).where(
                CrewMemberAssessment.id == assid
            )
        )
    for kind in (
        "rollback",
        "grade_correction",
        "worker_process_crash",
        "duplicate_job",
        "undo_completion",
        "recomplete",
        "delete_training",
        "rebuild",
    ):
        async with AsyncSessionLocal() as s:
            if kind == "rollback":
                await s.execute(
                    text(
                        "UPDATE final_report SET grade='4',grade_code_snapshot='4' WHERE assessment_id=:a"
                    ),
                    {"a": assid},
                )
                await s.rollback()
                assert (
                    await s.scalar(text("SELECT count(*) FROM commander_dirty_pilot"))
                    == 0
                )
            elif kind == "grade_correction":
                await s.execute(
                    text(
                        "UPDATE final_report SET grade='4',grade_code_snapshot='4',grade_label_snapshot='Grade 4',grade_score_snapshot=4 WHERE assessment_id=:a"
                    ),
                    {"a": assid},
                )
                await s.commit()
            elif kind in ("duplicate_job", "worker_process_crash"):
                for _ in range(3):
                    await s.execute(text("SELECT commander_mark_dirty(:u)"), {"u": uid})
                await s.commit()
            elif kind in ("undo_completion", "recomplete"):
                await s.execute(
                    text("UPDATE training_session SET status=:status WHERE id=:id"),
                    {
                        "status": (
                            "IN_PROGRESS" if kind == "undo_completion" else "COMPLETED"
                        ),
                        "id": tid,
                    },
                )
                await s.commit()
            elif kind == "delete_training":
                await s.execute(
                    text("DELETE FROM training_session WHERE id=:id"), {"id": tid}
                )
                await s.commit()
            else:
                await projection.enqueue_rebuild(s)
        if kind == "worker_process_crash":
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "benchmarks.projection_worker",
                "--crash-before-commit",
                "--once",
            )
            assert await proc.wait() == 77
            async with AsyncSessionLocal() as s:
                assert (
                    await s.scalar(text("SELECT count(*) FROM commander_dirty_pilot"))
                    > 0
                )
        t = time.perf_counter()
        work = await drain()
        duration = (time.perf_counter() - t) * 1000
        for f in (
            {},
            {"asOfDate": "2020-01-02"},
            {"pilotId": data["users"][0]["public_id"]},
        ):
            await compare(c, headers, f)
        append(
            "h3-checks.jsonl",
            dict(
                check=kind,
                size=data["n"],
                passed=True,
                count=3,
                worker_ms=duration,
                max_queue_age_ms=max([r["queue_age_ms"] for r in work], default=0),
            ),
        )


async def main(repeats=2, sizes=(1000, 10000), requests=20):
    async with client() as c:
        headers = await login(c)
        async with AsyncSessionLocal() as s:
            await projection.install(s)
        for n in sizes:
            data = await seed(c, headers, n, min(1000, max(50, n // 10)))
            async with AsyncSessionLocal() as s:
                await projection.enqueue_rebuild(s)
            started = time.perf_counter()
            await drain()
            rebuild_ms = (time.perf_counter() - started) * 1000
            async with AsyncSessionLocal() as s:
                await s.execute(text("ANALYZE"))
                await s.commit()
                storage = (
                    (
                        await s.execute(
                            text(
                                "SELECT relname,pg_total_relation_size(oid) bytes FROM pg_class WHERE relname IN ('commander_assessment_fact','commander_latest_assessment','commander_grade_fact','commander_dirty_pilot')"
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
            append(
                "h3-storage.jsonl",
                dict(size=n, rebuild_ms=rebuild_ms, tables=[dict(r) for r in storage]),
            )
            await correctness(c, headers, data)
            for params in ({}, {"asOfDate": "2020-01-02"}):
                for concurrent in (1, 8):
                    for rep in range(repeats):
                        variants = ["baseline", "projection"]
                        random.Random(n + rep + concurrent).shuffle(variants)
                        for variant in variants:
                            host = (
                                "http://baseline:8000" if variant == "baseline" else ""
                            )
                            url = host + "/_thesis/analytics/" + variant
                            for _ in range(3):
                                r = await c.get(url, headers=headers, params=params)
                                assert r.status_code == 200, r.text
                            before = (
                                await c.get(
                                    host + "/_thesis/resources", headers=headers
                                )
                            ).json()
                            sem = asyncio.Semaphore(concurrent)
                            ctx = dict(
                                hypothesis="H3",
                                rep=rep,
                                size=n,
                                concurrency=concurrent,
                                variant=variant,
                                filters=params,
                            )

                            async def one(i):
                                async with sem:
                                    t = time.perf_counter()
                                    r = await c.get(url, headers=headers, params=params)
                                    latency = (time.perf_counter() - t) * 1000
                                    append(
                                        "h3-requests.jsonl",
                                        {
                                            **ctx,
                                            "request": i,
                                            "latency_ms": latency,
                                            "status": r.status_code,
                                        },
                                    )
                                    assert r.status_code == 200, r.text
                                    return latency

                            start = time.perf_counter()
                            latencies = await asyncio.gather(
                                *(one(i) for i in range(requests))
                            )
                            seconds = time.perf_counter() - start
                            after = (
                                await c.get(
                                    host + "/_thesis/resources", headers=headers
                                )
                            ).json()
                            append(
                                "h3.jsonl",
                                {
                                    **ctx,
                                    "requests": requests,
                                    "seconds": seconds,
                                    "throughput": requests / seconds,
                                    "latencies_ms": latencies,
                                    "backend_cpu_seconds": after["cpuSeconds"]
                                    - before["cpuSeconds"],
                                    "backend_max_rss_kib": after["maxRssKib"],
                                },
                            )
                            print(
                                "H3",
                                n,
                                params,
                                concurrent,
                                rep,
                                variant,
                                round(requests / seconds, 1),
                                flush=True,
                            )
            await mutations(c, headers, data)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--sizes", default="1000,10000")
    p.add_argument("--requests", type=int, default=20)
    a = p.parse_args()
    asyncio.run(main(a.repeats, tuple(map(int, a.sizes.split(","))), a.requests))
