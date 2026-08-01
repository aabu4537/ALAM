"""preference_facts and preference_fact_evidence tables (ADR-0001, M4 session 1)

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-31

Hand-written, matching 0001-0005. ``preference_facts`` is ADR-0001's L3
semantic profile tier — no embedding column, loaded wholesale rather than
retrieved. ``preference_fact_evidence`` is a plain join table pointing each
fact back at the memories that produced it, with ``ON DELETE CASCADE`` from
both sides.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "preference_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("base_confidence", sa.Float(), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("last_reinforced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
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
            ["user_id"], ["users.id"], name="fk_preference_facts_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["preference_facts.id"],
            name="fk_preference_facts_supersedes_id",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_preference_facts"),
        sa.CheckConstraint(
            "base_confidence >= 0 AND base_confidence <= 1",
            name="ck_preference_facts_base_confidence_range",
        ),
    )
    op.create_index("ix_preference_facts_user_id", "preference_facts", ["user_id"])
    op.create_index(
        "ix_preference_facts_user_id_superseded_at",
        "preference_facts",
        ["user_id", "superseded_at"],
    )

    op.create_table(
        "preference_fact_evidence",
        sa.Column("preference_fact_id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["preference_fact_id"],
            ["preference_facts.id"],
            name="fk_preference_fact_evidence_preference_fact_id_preference_facts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["memory_id"],
            ["memories.id"],
            name="fk_preference_fact_evidence_memory_id_memories",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "preference_fact_id", "memory_id", name="pk_preference_fact_evidence"
        ),
    )


def downgrade() -> None:
    op.drop_table("preference_fact_evidence")
    op.drop_index("ix_preference_facts_user_id_superseded_at", table_name="preference_facts")
    op.drop_index("ix_preference_facts_user_id", table_name="preference_facts")
    op.drop_table("preference_facts")
