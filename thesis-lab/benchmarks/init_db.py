# Models are imported for SQLAlchemy metadata registration.
# ruff: noqa: F401
import asyncio
import sys
from sqlalchemy import text
from app.db.base import Base
from app.db.session import engine
from app.core.config import get_settings
from app.modules.ai import models as ai
from app.modules.auth import models as auth
from app.modules.speech import models as speech
from app.modules.support import models as support
from app.modules.training import models as training, assessment_models
from app.modules.users import models as users


async def main():
    assert get_settings().database_url.endswith("/thesis_bench")
    async with engine.begin() as c:
        if "--reset" in sys.argv:
            await c.execute(text("DROP SCHEMA public CASCADE"))
            await c.execute(text("CREATE SCHEMA public"))
        await c.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Isolated thesis schema ready")


if __name__ == "__main__":
    asyncio.run(main())
