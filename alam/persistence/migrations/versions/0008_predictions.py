"""predictions and prediction_evidence tables (M5 session 1)

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-31

Hand-written, matching 0001-0007. ``predictions`` is derived 1:1 from a
``memory_type=prediction`` memory (``source_memory_id``, unique,
``ON DELETE CASCADE`` — a prediction has no existence independent of the
memory that stated it, unlike most FKs in this schema). ``prediction_evidence``
is a plain join table, same shape as ``preference_fact_evidence``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "predictions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_memory_id", sa.Uuid(), nullable=False),
        sa.Column("media_item_id", sa.Uuid(), nullable=False),
        sa.Column("made_at_ordinal", sa.Integer(), nullable=False),
        sa.Column("resolution_window", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "confirmed",
                "refuted",
                "unresolvable",
                name="prediction_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_prompt_version_id", sa.String(length=100), nullable=True),
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
            ["source_memory_id"],
            ["memories.id"],
            name="fk_predictions_source_memory_id_memories",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["media_item_id"],
            ["media_items.id"],
            name="fk_predictions_media_item_id_media_items",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_predictions"),
        sa.UniqueConstraint("source_memory_id", name="uq_predictions_source_memory_id"),
    )
    op.create_index(
        "ix_predictions_media_item_id_status", "predictions", ["media_item_id", "status"]
    )

    op.create_table(
        "prediction_evidence",
        sa.Column("prediction_id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["prediction_id"],
            ["predictions.id"],
            name="fk_prediction_evidence_prediction_id_predictions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name="fk_prediction_evidence_memory_id_memories",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("prediction_id", "memory_id", name="pk_prediction_evidence"),
    )


def downgrade() -> None:
    op.drop_table("prediction_evidence")
    op.drop_index("ix_predictions_media_item_id_status", table_name="predictions")
    op.drop_table("predictions")
