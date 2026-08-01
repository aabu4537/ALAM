"""memories.consolidated_at column (M4 session 2)

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-31

Hand-written, matching 0001-0006. NULL means "not yet run through
consolidation" — same idiom as ``media_items.structure_verified_at``. The
partial index backs the consolidation job's backlog query, which only ever
scans unprocessed rows, same reasoning as the ``jobs`` table's claim indexes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memories", sa.Column("consolidated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_memories_unconsolidated",
        "memories",
        ["id"],
        postgresql_where=sa.text("consolidated_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_memories_unconsolidated", table_name="memories")
    op.drop_column("memories", "consolidated_at")
