"""llm_calls.provider column (M7 session 1)

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-01

Hand-written, matching 0001-0012. Additive only, per ADR-0011: one
nullable column, nothing else touched. NULL means "recorded before this
column existed" — there is nothing to backfill it from, unlike
``memories.consolidated_at``'s NULL (which a later job run fills in).
``domain/llm_cost.py`` treats a NULL provider as "cannot be priced," never
as a free provider.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("provider", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_calls", "provider")
