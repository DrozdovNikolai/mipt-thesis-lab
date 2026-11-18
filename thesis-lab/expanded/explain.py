import asyncio
from datetime import date
import json
import sys
from sqlalchemy import event
from app.db.session import AsyncSessionLocal, engine
from app.modules.commander.service import get_airline_competency_grade_distribution
from expanded.common import OUT, save


async def main(variant):
    data = json.loads((OUT / "dataset.json").read_text())
    output = []
    for cutoff in (None, date(2020, 1, 2)):
        captured = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                captured.append((statement, parameters))

        event.listen(engine.sync_engine, "before_cursor_execute", capture)
        async with AsyncSessionLocal() as s:
            await get_airline_competency_grade_distribution(
                s,
                airline_id=data["airline_id"],
                pilot_public_id=None,
                aircraft_id=None,
                age_from_years=None,
                age_to_years=None,
                position_id=None,
                as_of_date=cutoff,
                use_projection=variant == "projection",
                use_optimized=variant == "optimized",
            )
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        async with engine.connect() as conn:
            for sql, params in captured:
                plan = await conn.exec_driver_sql(
                    "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON,TIMING OFF) " + sql, params
                )
                output.append(
                    dict(
                        as_of_date=cutoff,
                        sql=sql,
                        parameters=params,
                        plan=plan.scalar_one(),
                    )
                )
    save("explain-" + variant + ".json", output)
    await engine.dispose()
    print("SQL diagnostics", variant, len(output), flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
