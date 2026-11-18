"""Crash after a successful HTTP response but before deleting its durable queue row."""

import asyncio
import json
import os
import sqlite3
import sys
from benchmarks.common import client, measured, append


async def main():
    config = json.load(sys.stdin)
    db = sqlite3.connect(config["queue"])
    async with client() as c:
        while row := db.execute(
            "SELECT id,path,body FROM queue ORDER BY id LIMIT 1"
        ).fetchone():
            r, lat, size = await measured(
                c,
                "POST",
                row[1],
                json.loads(row[2]),
                config["headers"],
                config["context"],
            )
            if r.status_code != 200:
                raise RuntimeError(r.text)
            append(
                "h1-worker.jsonl",
                dict(
                    training_id=config["context"]["training_id"],
                    body_bytes=size,
                    latency_ms=lat,
                ),
            )
            if config["crash"]:
                os._exit(77)
            db.execute("DELETE FROM queue WHERE id=?", (row[0],))
            db.commit()
    db.close()


if __name__ == "__main__":
    asyncio.run(main())
