"""Analysis snapshots and their durable lifecycle events."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("datasets.id"), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("engine_label", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("started_at", sa.String(40)),
        sa.Column("finished_at", sa.String(40)),
        sa.Column("error_code", sa.String(60)),
        sa.Column("error_message", sa.Text()),
        sa.Column("summary", sa.JSON()),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.UniqueConstraint("dataset_id", "request_key", name="uq_analysis_request"),
    )
    op.create_index("ix_analysis_runs_case_id", "analysis_runs", ["case_id"])
    op.create_index("ix_analysis_runs_dataset_id", "analysis_runs", ["dataset_id"])
    op.create_index(
        "uq_active_analysis_dataset",
        "analysis_runs",
        ["dataset_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running', 'validating')"),
    )
    op.create_table(
        "analysis_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("analysis_id", sa.String(36), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_analysis_events_analysis_id", "analysis_events", ["analysis_id"])


def downgrade():
    op.drop_table("analysis_events")
    op.drop_table("analysis_runs")
