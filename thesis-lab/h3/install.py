import asyncio
import sys
import time
from sqlalchemy import text
from app.db.session import AsyncSessionLocal
from app.modules.commander import analytics_projection, analytics_optimized
from expanded.common import save


async def main(variant):
    from app.modules.commander import analytics_incremental
    projection_module = analytics_incremental if variant == "incremental" else analytics_projection
    start = time.perf_counter()
    async with AsyncSessionLocal() as s:
        await s.execute(text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))
        await s.commit()
        if variant == "optimized":
            await analytics_optimized.install(s)
        if variant in ("projection", "incremental"):
            # Source indexes also benefit incremental updates; their write/storage cost is included.
            await analytics_optimized.install(s)
            await projection_module.install(s)
            await projection_module.enqueue_rebuild(s)
            while await projection_module.process_batch(s):
                pass
            await s.execute(
                text(
                    """CREATE TABLE thesis_worker_control(id int PRIMARY KEY,
                crash_requested boolean NOT NULL DEFAULT false, crashes int NOT NULL DEFAULT 0,
                worker_pid int, last_start timestamptz)"""
                )
            )
            await s.execute(text("INSERT INTO thesis_worker_control(id) VALUES(1)"))
            await s.commit()
        await s.execute(text("ANALYZE"))
        await s.commit()
        tables = (
            (
                await s.execute(
                    text(
                        """SELECT relname,pg_total_relation_size(relid) bytes
            FROM pg_stat_user_tables ORDER BY relname"""
                    )
                )
            )
            .mappings()
            .all()
        )
        indexes = (
            (
                await s.execute(
                    text(
                        """SELECT indexrelname,pg_relation_size(indexrelid) bytes
            FROM pg_stat_user_indexes WHERE indexrelname LIKE 'thesis_%' ORDER BY indexrelname"""
                    )
                )
            )
            .mappings()
            .all()
        )
        save(
            "storage-" + variant + ".json",
            dict(
                variant=variant,
                install_ms=(time.perf_counter() - start) * 1000,
                tables=[dict(x) for x in tables],
                extra_source_indexes=[dict(x) for x in indexes],
            ),
        )
        print("Variant installed", variant, flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
