"""Persist cases and validated immutable input datasets."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("name_search", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("relative_path", sa.String(200), nullable=False, unique=True),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("quality", sa.JSON(), nullable=False),
    )
    op.create_index("ix_datasets_case_id", "datasets", ["case_id"])


def downgrade():
    op.drop_table("datasets")
    op.drop_table("cases")
