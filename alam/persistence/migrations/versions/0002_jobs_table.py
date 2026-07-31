"""Jobs table with leased claims

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-31

Hand-written. Autogenerate does not emit the partial index predicates, and the
two claim-path indexes are the difference between an index-only lookup and a
sequential scan over every terminal job ever run.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(length=100), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column(
            "run_after",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
    )

    # The claim query has two arms and each gets its own partial index. Both are
    # tiny in practice: succeeded and failed rows are excluded entirely, so the
    # indexes stay proportional to outstanding work rather than to history.
    op.create_index(
        "ix_jobs_claimable",
        "jobs",
        ["run_after"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_jobs_expired_leases",
        "jobs",
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index("ix_jobs_job_type_status", "jobs", ["job_type", "status"])


def downgrade() -> None:
    op.drop_index("ix_jobs_job_type_status", table_name="jobs")
    op.drop_index("ix_jobs_expired_leases", table_name="jobs")
    op.drop_index("ix_jobs_claimable", table_name="jobs")
    op.drop_table("jobs")
