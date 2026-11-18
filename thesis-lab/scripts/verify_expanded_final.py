"""Final source/projection parity after mixed writes, on the projection's own source DB."""

import asyncio
from collections import Counter
from datetime import date
import json
from sqlalchemy import text
from app.db.session import AsyncSessionLocal
from app.modules.commander.service import (
    get_airline_competency_grade_distribution as distribution,
)
from expanded.common import OUT, save


async def main():
    data = json.loads((OUT / "dataset.json").read_text())
    records = []
    async with AsyncSessionLocal() as s:
        assert await s.scalar(text("SELECT count(*) FROM commander_dirty_pilot")) == 0
        tenants = (
            (
                await s.execute(
                    text(
                        "SELECT DISTINCT airline_id FROM users WHERE airline_id IS NOT NULL"
                    )
                )
            )
            .scalars()
            .all()
        )
        for aid in tenants:
            for cutoff in (None, date(2020, 1, 2), date(2019, 12, 31)):
                kwargs = dict(
                    airline_id=aid,
                    pilot_public_id=None,
                    aircraft_id=None,
                    position_id=None,
                    age_from_years=None,
                    age_to_years=None,
                    as_of_date=cutoff,
                )
                source = await distribution(s, **kwargs)
                optimized = await distribution(s, **kwargs, use_optimized=True)
                projected = await distribution(s, **kwargs, use_projection=True)
                assert source == optimized == projected, (aid, cutoff)
                records.append(
                    dict(
                        airline_id=aid,
                        as_of_date=cutoff,
                        passed=True,
                        competencies=len(source["items"]),
                    )
                )
        # Independently calculate current TC0 counts from the final source rows.
        counts = dict(
            (
                await s.execute(
                    text(
                        """SELECT grade,count(*) FROM (
            SELECT DISTINCT ON(a.user_id) r.grade
            FROM crew_member_assessment a JOIN training_session t ON t.id=a.training_session_id
            JOIN users u ON u.id=a.user_id JOIN final_report r ON r.assessment_id=a.id
            WHERE u.airline_id=:aid AND t.status='COMPLETED' AND r.competence_id=:comp
            ORDER BY a.user_id,coalesce(t.completed_at,t.updated_at,t.created_at) DESC,
                a.created_at DESC,a.id DESC,r.updated_at DESC,r.created_at DESC,r.id DESC
        ) x GROUP BY grade"""
                    ),
                    dict(aid=data["airline_id"], comp=data["competences"][0]),
                )
            ).all()
        )
        actual = await distribution(
            s,
            airline_id=data["airline_id"],
            pilot_public_id=None,
            aircraft_id=None,
            position_id=None,
            age_from_years=None,
            age_to_years=None,
            as_of_date=None,
            use_projection=True,
        )
        item = next(
            x for x in actual["items"] if x["competence_id"] == data["competences"][0]
        )
        got = {
            g["grade_code"]: g["pilot_count"]
            for g in item["grades"]
            if g["pilot_count"]
        }
        assert counts == got and sum(counts.values()) == data["pilots"], (counts, got)
        latest = {}
        for ordinal, pilot in enumerate(data["assignment"]):
            latest[pilot] = ordinal
        expected = {
            data["users"][pilot]["public_id"]: str((ordinal // data["pilots"]) % 4 + 1)
            for pilot, ordinal in latest.items()
        }
        for line in (OUT / "mixed-writes.jsonl").read_text().splitlines():
            row = json.loads(line)
            if row["variant"] == "projection" and row["status"] == 200:
                expected[row["pilot_id"]] = row["grade"]
        arithmetic = dict(Counter(expected.values()))
        assert got == arithmetic, (got, arithmetic)
    save(
        "final-parity.json",
        dict(
            passed=True,
            records=records,
            current_tc0_counts=counts,
            arithmetic_expected=arithmetic,
        ),
    )
    print("Final source, optimized SQL and projection parity passed")


if __name__ == "__main__":
    asyncio.run(main())
