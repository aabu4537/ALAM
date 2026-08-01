"""memory_embeddings table (ADR-0008, M3 session 1)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-31

Hand-written, matching 0001-0004. The ``vector`` column is intentionally
declared with no fixed dimension (``VECTOR`` bare, not ``VECTOR(N)``) — see
ADR-0008. A same-table ``vector(N)`` column would fix the dimension for every
row at migration time; this side table lets rows from different-dimension
models coexist for the same memory, distinguished by the
``(memory_id, embedding_model, embedding_version)`` unique constraint.

``content_hash`` is indexed, not unique — two different memories can
legitimately share identical content and each still needs its own row.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_embeddings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("embedding_version", sa.String(length=50), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("vector", Vector(), nullable=False),
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
            ["memory_id"],
            ["memories.id"],
            name="fk_memory_embeddings_memory_id_memories",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memory_embeddings"),
    )
    op.create_index("ix_memory_embeddings_memory_id", "memory_embeddings", ["memory_id"])
    op.create_index("ix_memory_embeddings_content_hash", "memory_embeddings", ["content_hash"])
    op.create_unique_constraint(
        "uq_memory_embeddings_memory_model_version",
        "memory_embeddings",
        ["memory_id", "embedding_model", "embedding_version"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_embeddings_content_hash", table_name="memory_embeddings")
    op.drop_index("ix_memory_embeddings_memory_id", table_name="memory_embeddings")
    op.drop_table("memory_embeddings")
