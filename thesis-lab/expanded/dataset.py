import asyncio
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
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
from expanded.common import save, client, login


async def seed(c, headers, n, pilots, skew=False):
    tag = uuid.uuid4().hex[:8]
    assignment = [i % pilots for i in range(n)]
    if skew:
        hot = max(1, pilots // 10)
        assignment = [
            (
                (i // 10 * 8 + i % 10) % hot
                if i % 10 < 8
                else hot + (i // 10 * 2 + i % 10 - 8) % (pilots - hot)
            )
            for i in range(n)
        ]
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
                models.GradingScheme.is_active.is_(True),
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
                                user_id=users[assignment[i]].id,
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
            assignment=assignment,
            airline_id=aid,
            users=[dict(id=u.id, public_id=str(u.public_id)) for u in users],
            aircraft_id=ac.id,
            position_id=pos.id,
            competences=[x.id for x in comps],
            n=n,
            pilots=pilots,
        )


async def main(profile):
    from sqlalchemy import text

    async with client("seed") as c:
        h = await login(c)
        data = await seed(
            c, h, profile["n"], profile["pilots"], profile.get("skew", False)
        )
        noise = []
        for _ in range(profile.get("neighbors", 0)):
            other = await seed(c, h, 25000, 250)
            noise.append(dict(airline_id=other["airline_id"], n=25000, pilots=250))
        owner = (await c.get("/api/auth/me", headers=h)).json()["id"]
        r = await c.put(
            "/api/users/" + owner,
            headers=h,
            json={"airlineId": data["airline_id"], "aircraftIds": ["A320"]},
        )
        assert r.status_code == 200, r.text
        async with AsyncSessionLocal() as s:
            probes = (
                (
                    await s.execute(
                        text(
                            """SELECT DISTINCT ON(a.user_id) a.user_id,u.public_id,r.id report_id,
                r.grade,r.competence_id
                FROM crew_member_assessment a JOIN users u ON u.id=a.user_id
                JOIN training_session t ON t.id=a.training_session_id
                JOIN final_report r ON r.assessment_id=a.id
                WHERE u.airline_id=:aid AND r.competence_id=:comp
                ORDER BY a.user_id,t.completed_at DESC,a.created_at DESC,a.id DESC,r.id DESC"""
                        ),
                        {"aid": data["airline_id"], "comp": data["competences"][0]},
                    )
                )
                .mappings()
                .all()
            )
        data["probes"] = [dict(x) for x in probes]
        data["noise"] = noise
        data["profile"] = profile
        save("dataset.json", data)
        print("Seed prepared", profile, flush=True)


if __name__ == "__main__":
    import json

    asyncio.run(main(json.loads(sys.argv[1])))
