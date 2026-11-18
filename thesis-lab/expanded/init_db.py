import asyncio
from sqlalchemy import text
from app.core.config import get_settings
from app.db.session import engine, AsyncSessionLocal
from app.db.base import Base
from benchmarks import init_db as register_models  # noqa: F401
from app.modules.users.bootstrap import ensure_default_rbac


async def main():
    assert get_settings().database_url.rsplit("/", 1)[-1].startswith("thesis_exp_")
    async with engine.begin() as c:
        await c.execute(text("DROP SCHEMA public CASCADE"))
        await c.execute(text("CREATE SCHEMA public"))
        await c.run_sync(Base.metadata.create_all)
    async with AsyncSessionLocal() as s:
        await ensure_default_rbac(s)
    await engine.dispose()
    print("Expanded isolated schema initialized", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
