"""briefings table (M6 session 4)

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-01

Hand-written, matching 0001-0011. Same persisted-artifact shape as
``journey_summaries``/``recommendations`` (ADR-0013), latest-wins per media
item like journey summaries — but pre-book, so there's no ordinal to key
staleness off of; ``generated_catalog_present`` and ``generated_fact_snapshot``
are what ``domain.synthesis_staleness.is_briefing_stale`` compares against
current state instead. ``claims`` holds ALAM-composed claim text, never LLM
output directly, reusing the same citation-groundedness scheme
``recommendations`` established (ADR-0014).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "briefings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("media_item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "complete",
                "failed",
                "blocked_ungrounded",
                name="briefing_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "generated_fact_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("generated_catalog_present", sa.Boolean(), nullable=False),
        sa.Column("prompt_version_id", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("claims", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
            ["media_item_id"],
            ["media_items.id"],
            name="fk_briefings_media_item_id_media_items",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_briefings"),
    )
    op.create_index(
        "ix_briefings_media_item_id_created_at",
        "briefings",
        ["media_item_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_briefings_media_item_id_created_at", table_name="briefings")
    op.drop_table("briefings")
