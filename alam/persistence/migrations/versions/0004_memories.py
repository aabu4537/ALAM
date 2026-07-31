"""memories table (ADR-0001, M2 session 3)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-31

Hand-written, matching 0001-0003. No embedding or tsvector column yet — those
arrive at M3 (rule 7). ``structure_unit_id`` intentionally has no ``ondelete``
cascade, same reasoning as 0003's ``captures``/``reading_sessions`` FKs: a
chapter with memories already extracted against it must not be silently
excludable during structure re-verification.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("capture_id", sa.Uuid(), nullable=False),
        sa.Column("media_item_id", sa.Uuid(), nullable=False),
        sa.Column("structure_unit_id", sa.Uuid(), nullable=False),
        sa.Column("structure_ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "memory_type",
            sa.Enum(
                "prediction",
                "opinion",
                "emotional_reaction",
                "confusion",
                "character_judgment",
                "favorite_moment",
                "meta_comment",
                "other",
                name="memory_type",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("prompt_version_id", sa.String(length=100), nullable=False),
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
            ["capture_id"],
            ["captures.id"],
            name="fk_memories_capture_id_captures",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["media_item_id"],
            ["media_items.id"],
            name="fk_memories_media_item_id_media_items",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["structure_unit_id"],
            ["media_structure_units.id"],
            name="fk_memories_structure_unit_id_media_structure_units",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memories"),
    )
    op.create_index("ix_memories_capture_id", "memories", ["capture_id"])
    op.create_index("ix_memories_media_item_id", "memories", ["media_item_id"])
    op.create_index(
        "ix_memories_media_item_id_structure_ordinal",
        "memories",
        ["media_item_id", "structure_ordinal"],
    )


def downgrade() -> None:
    op.drop_index("ix_memories_media_item_id_structure_ordinal", table_name="memories")
    op.drop_index("ix_memories_media_item_id", table_name="memories")
    op.drop_index("ix_memories_capture_id", table_name="memories")
    op.drop_table("memories")
