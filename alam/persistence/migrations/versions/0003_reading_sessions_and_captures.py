"""reading_sessions and captures tables (ADR-0004, M2)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-31

Hand-written, matching 0001/0002: autogenerate would not emit the check
constraint on ``current_progress`` and would default the two
``structure_unit_id`` foreign keys to a behavior indistinguishable from
RESTRICT anyway, but doing it explicitly documents that the lack of
``ondelete="CASCADE"`` there is a deliberate choice, not an oversight — a
chapter with recorded reflections against it must not be silently excludable
during structure re-verification.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reading_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("media_item_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "completed",
                "abandoned",
                name="reading_session_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("current_structure_unit_id", sa.Uuid(), nullable=False),
        sa.Column("current_ordinal", sa.Integer(), nullable=False),
        sa.Column("current_progress", sa.Float(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
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
            name="fk_reading_sessions_media_item_id_media_items",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["current_structure_unit_id"],
            ["media_structure_units.id"],
            name="fk_reading_sessions_current_structure_unit_id_media_structure_units",
        ),
        sa.CheckConstraint(
            "current_progress >= 0 AND current_progress <= 1",
            name="ck_reading_sessions_current_progress_range",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reading_sessions"),
    )
    op.create_index("ix_reading_sessions_media_item_id", "reading_sessions", ["media_item_id"])
    op.create_index(
        "ix_reading_sessions_media_item_id_status",
        "reading_sessions",
        ["media_item_id", "status"],
    )

    op.create_table(
        "captures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reading_session_id", sa.Uuid(), nullable=False),
        sa.Column("media_item_id", sa.Uuid(), nullable=False),
        sa.Column("structure_unit_id", sa.Uuid(), nullable=False),
        sa.Column("structure_ordinal", sa.Integer(), nullable=False),
        sa.Column("audio_data", sa.LargeBinary(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "transcribed",
                "corrected",
                "extracted",
                "failed",
                name="capture_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("raw_transcript", sa.Text(), nullable=True),
        sa.Column("corrected_transcript", sa.Text(), nullable=True),
        sa.Column("transcript_model", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
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
            ["reading_session_id"],
            ["reading_sessions.id"],
            name="fk_captures_reading_session_id_reading_sessions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["media_item_id"],
            ["media_items.id"],
            name="fk_captures_media_item_id_media_items",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["structure_unit_id"],
            ["media_structure_units.id"],
            name="fk_captures_structure_unit_id_media_structure_units",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_captures"),
    )
    op.create_index("ix_captures_reading_session_id", "captures", ["reading_session_id"])
    op.create_index("ix_captures_media_item_id", "captures", ["media_item_id"])
    op.create_index(
        "ix_captures_media_item_id_structure_ordinal",
        "captures",
        ["media_item_id", "structure_ordinal"],
    )


def downgrade() -> None:
    op.drop_index("ix_captures_media_item_id_structure_ordinal", table_name="captures")
    op.drop_index("ix_captures_media_item_id", table_name="captures")
    op.drop_index("ix_captures_reading_session_id", table_name="captures")
    op.drop_table("captures")

    op.drop_index("ix_reading_sessions_media_item_id_status", table_name="reading_sessions")
    op.drop_index("ix_reading_sessions_media_item_id", table_name="reading_sessions")
    op.drop_table("reading_sessions")
