"""journey_summaries table (M6 session 1)

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-01

Hand-written, matching 0001-0009. One row per generated artifact (not
upserted in place) — written ``pending`` before the LLM call and updated to
its terminal status after, per the persisted-artifact pattern ADR-0013
describes. ``layer3_spans`` and ``excluded_snapshot`` are JSONB, same idiom
as ``media_items.attributes``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "journey_summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("media_item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "complete",
                "failed",
                "blocked_leaked",
                name="journey_summary_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("generated_at_ordinal", sa.Integer(), nullable=False),
        sa.Column("prompt_version_id", sa.String(length=100), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("draft", sa.Text(), nullable=True),
        sa.Column("layer3_leaked", sa.Boolean(), nullable=True),
        sa.Column("layer3_spans", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("excluded_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
            name="fk_journey_summaries_media_item_id_media_items",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_journey_summaries"),
    )
    op.create_index(
        "ix_journey_summaries_media_item_id_created_at",
        "journey_summaries",
        ["media_item_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_journey_summaries_media_item_id_created_at", table_name="journey_summaries")
    op.drop_table("journey_summaries")
