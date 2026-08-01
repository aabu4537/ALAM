"""The ``preference_facts`` table — ADR-0001's L3 semantic profile tier.

Low-cardinality, human-readable, always loaded wholesale rather than
retrieved (no embedding column — ADR-0001 rejects that explicitly). Produced
by the M4 consolidation job (not yet built — this session is the storage
layer only).

Contradictions never overwrite: a new row is written with ``supersedes_id``
pointing at the old one, and the old row's ``superseded_at`` is set. Nothing
is deleted, which is what makes taste drift queryable later.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PreferenceFact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "preference_facts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    statement: Mapped[str] = mapped_column(Text, nullable=False)
    """Human-readable, e.g. "prefers unreliable narrators" (ADR-0001) — this
    is what gets loaded wholesale into every prompt, not summarized further."""

    base_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    """Combined with ``last_reinforced_at`` via
    ``domain.preference_decay.effective_confidence`` at read time — decay is
    never written back to this column, only computed."""

    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    last_reinforced_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("preference_facts.id", name="fk_preference_facts_supersedes_id"),
        nullable=True,
    )
    """Not ``ondelete="CASCADE"`` — same reasoning as
    ``ReadingSession.current_structure_unit_id``. Facts are never deleted in
    V1 (only marked superseded), so this never fires in practice; it exists
    so a future deletion path fails loudly rather than silently orphaning a
    supersede chain."""

    superseded_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "base_confidence >= 0 AND base_confidence <= 1",
            name="base_confidence_range",
        ),
        Index("ix_preference_facts_user_id_superseded_at", "user_id", "superseded_at"),
    )

    @property
    def is_active(self) -> bool:
        return self.superseded_at is None

    def __repr__(self) -> str:
        return f"<PreferenceFact id={self.id} statement={self.statement[:40]!r}>"
