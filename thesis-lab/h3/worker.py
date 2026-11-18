"""Separate worker process; supervisor waits five seconds after an injected pre-commit death."""

import asyncio
import os
import subprocess
import sys
import time
from sqlalchemy import text
from app.db.session import AsyncSessionLocal
from app.modules.commander.analytics_incremental import process_batch
from expanded.common import append


async def child():
    async with AsyncSessionLocal() as s:
        await s.execute(
            text(
                "UPDATE thesis_worker_control SET worker_pid=:p,last_start=clock_timestamp() WHERE id=1"
            ),
            {"p": os.getpid()},
        )
        await s.commit()
    while True:
        async with AsyncSessionLocal() as s:
            if not await s.scalar(text("SELECT pg_try_advisory_xact_lock(1718774131, 3)")):
                await s.rollback()
                await asyncio.sleep(0.1)
                continue
            # Lock a non-empty batch before deciding to crash. Checking EXISTS in
            # a separate transaction can miss every enqueue between polls.
            pending = (
                await s.execute(
                    text(
                        """SELECT assessment_id FROM commander_dirty_assessment
                ORDER BY assessment_id LIMIT 25 FOR UPDATE SKIP LOCKED"""
                    )
                )
            ).all()
            if not pending and not await s.scalar(text("SELECT count(*) FROM commander_dirty_training")):
                await s.rollback()
                await asyncio.sleep(0.1)
                continue
            async with AsyncSessionLocal() as control:
                crash = await control.scalar(
                    text("SELECT crash_requested FROM thesis_worker_control WHERE id=1")
                )
                if crash:
                    await control.execute(
                        text(
                            "UPDATE thesis_worker_control SET crash_requested=false,crashes=crashes+1 WHERE id=1"
                        )
                    )
                    await control.commit()
            if crash:

                async def die():
                    append(
                        "incremental-worker-crashes.jsonl",
                        dict(
                            pid=os.getpid(),
                            pending_before=len(pending),
                            before_commit=True,
                            time=time.time(),
                        ),
                    )
                    os._exit(77)

                s.commit = die
            started = time.perf_counter()
            cpu = time.process_time()
            result = await process_batch(s, 25)
            append(
                "incremental-worker-batches.jsonl",
                dict(
                    pid=os.getpid(),
                    items=len(result),
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    cpu_seconds=time.process_time() - cpu,
                    results=result,
                ),
            )


def supervise():
    while True:
        started = time.time()
        p = subprocess.Popen([sys.executable, "-m", "h3.worker", "--child"])
        code = p.wait()
        append(
            "incremental-worker-processes.jsonl",
            dict(
                pid=p.pid,
                start=started,
                end=time.time(),
                exit_code=code,
                restart_delay_s=5,
            ),
        )
        if code != 77:
            raise SystemExit(code or 1)
        time.sleep(5)


if __name__ == "__main__":
    if "--child" in sys.argv:
        asyncio.run(child())
    else:
        supervise()
