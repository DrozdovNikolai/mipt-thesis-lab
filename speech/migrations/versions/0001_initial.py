"""Initial storage, outbox, attempts, audit and model/benchmark registry.

Revision ID: 0001
"""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    snapshot = Path(__file__).with_name("0001_schema.sql").read_text(encoding="utf-8")
    for statement in snapshot.split(";"):
        if statement.strip():
            op.execute(statement)


def downgrade():
    for name in (
        "review_revisions",
        "events",
        "transcript_segments",
        "pipeline_runs",
        "outbox_events",
        "job_attempts",
        "processing_jobs",
        "audio_assets",
        "sessions",
        "benchmark_runs",
        "model_versions",
    ):
        op.drop_table(name)
