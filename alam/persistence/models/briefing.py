"""The ``briefings`` table (M6 session 4).

One row per generation, latest-wins per media item — book-scoped like
journey summaries, but pre-book: a briefing is only generated for a book
with no active ``ReadingSession`` yet (``services/briefing.py``), so unlike
``journey_summaries`` there is no ordinal to key staleness off of
(``domain.synthesis_staleness.is_briefing_stale``). ``claims`` holds
ALAM-composed claim text (copied from the cited ``preference_fact``/
``memory``'s own stored text), never text the LLM wrote directly — same
discipline ADR-0014 established for ``recommendations.candidates``.

Deliberately no ``blurb``/``subjects`` columns: the teaser shown alongside
``claims`` is read live from ``media_items.attributes["catalog"]`` at
response time (ADR-0015 already gives that its own durable cache with no
staleness needed), not duplicated onto this row.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BriefingStatus(enum.StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED_UNGROUNDED = "blocked_ungrounded"
    """A cited ``preference_fact``/``memory`` id didn't exist or didn't
    belong to the reader (``domain.recommendation_groundedness``, reused
    unchanged). Never returned by the API — see ``services/briefing.py``."""


class Briefing(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "briefings"

    media_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[BriefingStatus] = mapped_column(
        Enum(
            BriefingStatus,
            name="briefing_status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=BriefingStatus.PENDING,
    )

    generated_fact_snapshot: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    """The reader's active preference_fact ids, as strings, at generation
    time — what ``domain.synthesis_staleness.is_briefing_stale`` compares
    against the current set to decide whether the taste profile changed."""

    generated_catalog_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    """Whether the candidate had a non-empty catalog entry at generation
    time. If the backfill (ADR-0015) populates one later, this flips and
    the next read regenerates to surface the teaser."""

    prompt_version_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    """Rule 6. Null until an LLM call actually ran — nothing to
    personalize from short-circuits to ``complete`` with no LLM call at
    all, so this stays null even on some ``complete`` rows (see the
    service)."""

    model: Mapped[str | None] = mapped_column(String(200), nullable=True)

    claims: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    """Set only for ``complete`` rows. Each claim's ``text`` is copied
    verbatim from the cited ``preference_fact``/``memory`` row — composed by
    ALAM after the LLM call returns, never written by the LLM."""

    ungrounded_citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    """Set only for ``blocked_ungrounded`` rows: which cited ids failed the
    existence/ownership check."""

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Set only when ``status=failed``."""

    __table_args__ = (
        Index("ix_briefings_media_item_id_created_at", "media_item_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Briefing id={self.id} status={self.status.value}>"
