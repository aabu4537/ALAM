"""llm_calls table (M5.5a)

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-01

Hand-written, matching 0001-0008. Additive only, per ADR-0011: a new table,
nothing else touched. ``job_id`` is nullable — a call made outside a job
(an eval run, a one-off script) has no job to attribute to.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_site", sa.String(length=200), nullable=False),
        sa.Column("prompt_version_id", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name="fk_llm_calls_job_id_jobs",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_llm_calls"),
    )
    op.create_index("ix_llm_calls_job_id", "llm_calls", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_job_id", table_name="llm_calls")
    op.drop_table("llm_calls")
