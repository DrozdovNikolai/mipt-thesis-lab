"""Durable projection worker, with explicit process-death test points."""

import argparse
import asyncio
import os
from app.db.session import AsyncSessionLocal
from app.modules.commander.analytics_projection import process_batch


async def main(crash, once):
    async with AsyncSessionLocal() as s:
        if crash:

            async def die():
                os._exit(77)

            s.commit = die
        while True:
            batch = await process_batch(s)
            if once:
                break
            if not batch:
                await asyncio.sleep(0.25)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--crash-before-commit", action="store_true")
    p.add_argument("--once", action="store_true")
    a = p.parse_args()
    asyncio.run(main(a.crash_before_commit, a.once))
