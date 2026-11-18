"""Exercise immutable migrations against a fresh, isolated database and remove only that DB."""

import json
import os
import subprocess
import uuid

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from north55_speech.core import atomic_json, settings
from north55_speech.db import Base

name = "north55_migration_test_" + uuid.uuid4().hex
url = make_url(settings.database_url)
admin = create_engine(
    url.set(database="postgres"), isolation_level="AUTOCOMMIT", hide_parameters=True
)
target = create_engine(url.set(database=name), hide_parameters=True)
env = os.environ | {
    "NORTH55_DATABASE_URL": url.set(database=name).render_as_string(hide_password=False)
}
steps = []
try:
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    for revision in ("head", "head", "base", "head"):
        operation = "downgrade" if revision == "base" else "upgrade"
        subprocess.run(["alembic", operation, revision], env=env, check=True)
        tables = set(inspect(target).get_table_names()) - {"alembic_version"}
        expected = set() if revision == "base" else set(Base.metadata.tables)
        assert tables == expected, (tables, expected)
        steps.append(
            {"operation": operation, "revision": revision, "application_tables": len(tables)}
        )
    report = {"status": "PASS", "executed": True, "isolated_database": True, "steps": steps}
    atomic_json(settings.report_root / "migration-tests.json", report)
    print(json.dumps(report))
finally:
    target.dispose()
    assert name.startswith("north55_migration_test_") and len(name) == 55
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
    admin.dispose()
