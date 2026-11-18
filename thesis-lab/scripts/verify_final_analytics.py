"""Independent arithmetic audit after all H3 mutations, including deletion of pilot 0's latest training."""

import asyncio
from collections import Counter
import json
from pathlib import Path
import sys

from sqlalchemy import text
from app.db.session import AsyncSessionLocal
from app.modules.commander.service import get_airline_competency_grade_distribution


async def main(output):
    results = []
    async with AsyncSessionLocal() as session:
        tenants = (
            await session.execute(
                text(
                    "SELECT id,code FROM airline WHERE code ~ '^H[0-9a-f]{8}$' ORDER BY id"
                )
            )
        ).all()
        assert len(tenants) == 3
        for aid, code in tenants:
            pilots = await session.scalar(
                text(
                    "SELECT count(*) FROM users WHERE airline_id=:a AND login LIKE :pattern"
                ),
                {"a": aid, "pattern": code[1:] + "-%"},
            )
            training_count = await session.scalar(
                text(
                    "SELECT count(*) FROM crew_member_assessment a JOIN users u ON u.id=a.user_id WHERE u.airline_id=:a"
                ),
                {"a": aid},
            )
            n = training_count + 1
            assert n in (1000, 10000, 100000) and pilots == min(1000, max(50, n // 10))
            kwargs = dict(
                airline_id=aid,
                pilot_public_id=None,
                aircraft_id=None,
                age_from_years=None,
                age_to_years=None,
                position_id=None,
                as_of_date=None,
            )
            baseline = await get_airline_competency_grade_distribution(
                session, **kwargs
            )
            candidate = await get_airline_competency_grade_distribution(
                session, **kwargs, use_projection=True
            )
            assert baseline == candidate
            assert len(candidate["items"]) == 8
            assert candidate["pilots_with_completed_training"] == pilots
            for j, item in enumerate(candidate["items"]):
                expected = Counter()
                for p in range(pilots):
                    last = p + (n - 1 - p) // pilots * pilots
                    if p == 0:
                        last -= pilots
                    expected[str((last // pilots + j) % 4 + 1)] += 1
                actual = {
                    g["grade_code"]: g["pilot_count"]
                    for g in item["grades"]
                    if g["pilot_count"]
                }
                assert actual == dict(expected), (n, j, actual, expected)
            results.append(dict(size=n, pilots=pilots, competencies=8, passed=True))
        assert (
            await session.scalar(text("SELECT count(*) FROM commander_dirty_pilot"))
            == 0
        )
    output.write_text(json.dumps(dict(passed=True, tenants=results), indent=2))
    print(output)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
