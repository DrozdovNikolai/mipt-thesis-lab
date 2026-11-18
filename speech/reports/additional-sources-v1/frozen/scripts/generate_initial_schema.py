"""One-time initial migration snapshot generator; review changes before using it again."""

from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from north55_speech.db import Base

dialect = postgresql.dialect()
statements = []
for table in Base.metadata.sorted_tables:
    statements.append(str(CreateTable(table).compile(dialect=dialect)).strip())
    statements.extend(
        str(CreateIndex(index).compile(dialect=dialect))
        for index in sorted(table.indexes, key=lambda i: i.name)
    )
Path("migrations/versions/0001_schema.sql").write_text(
    ";\n\n".join(statements) + ";\n", encoding="utf-8"
)
