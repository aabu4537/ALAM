"""recommendations table (M6 session 2)

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-01

Hand-written, matching 0001-0010. Same persisted-artifact shape as
``journey_summaries`` (ADR-0013), latest-wins per user rather than per media
item — recommendations are library-wide, not book-scoped. No ordinal exists
for a library-wide artifact, so staleness snapshots the candidate shelf and
active preference-fact id sets instead (ADR-0014); ``candidates`` holds
ALAM-composed claim text, never LLM output directly, per ADR-0014's
schema-level groundedness decision.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "complete",
                "failed",
                "blocked_ungrounded",
                name="recommendation_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "generated_shelf_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "generated_fact_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("prompt_version_id", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("candidates", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ungrounded_citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_recommendations_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_recommendations"),
    )
    op.create_index(
        "ix_recommendations_user_id_created_at",
        "recommendations",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_recommendations_user_id_created_at", table_name="recommendations")
    op.drop_table("recommendations")
