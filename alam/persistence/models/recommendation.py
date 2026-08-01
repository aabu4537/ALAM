"""The ``recommendations`` table (M6 session 2, ADR-0014).

One row per generation, latest-wins per user — library-wide, not per media
item, since a recommendation set isn't tied to one book's ``ReaderContext``
(same shape difference ``taste_drift`` already has from ``journey_summary``).
``candidates`` holds ALAM-composed claim text (copied from the cited
``preference_fact``/``memory``'s own stored text), never text the LLM wrote
directly — see ``services/recommendations.py``.
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Enum, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RecommendationStatus(enum.StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED_UNGROUNDED = "blocked_ungrounded"
    """A cited ``preference_fact``/``memory`` id didn't exist or didn't
    belong to the reader (``domain.recommendation_groundedness``). Never
    returned by the API — see ``services/recommendations.py``."""


class Recommendation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "recommendations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[RecommendationStatus] = mapped_column(
        Enum(
            RecommendationStatus,
            name="recommendation_status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=RecommendationStatus.PENDING,
    )

    generated_shelf_snapshot: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    """The to-read shelf's media_item ids, as strings, at generation time —
    what ``domain.synthesis_staleness.is_recommendation_set_stale`` compares
    against the current shelf to decide whether the candidate pool changed."""

    generated_fact_snapshot: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    """The reader's active preference_fact ids, as strings, at generation
    time — same staleness comparison, for whether the reader's taste
    profile has changed since."""

    prompt_version_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    """Rule 6. Null until an LLM call actually ran — an empty candidate
    shelf short-circuits to ``complete`` with no LLM call at all, so this
    stays null even on some ``complete`` rows (see the service)."""

    model: Mapped[str | None] = mapped_column(String(200), nullable=True)

    candidates: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    """Set only for ``complete`` rows. Each claim's ``text`` is copied
    verbatim from the cited ``preference_fact``/``memory`` row — composed by
    ALAM after the LLM call returns, never written by the LLM (ADR-0014)."""

    ungrounded_citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    """Set only for ``blocked_ungrounded`` rows: which cited ids failed the
    existence/ownership check."""

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Set only when ``status=failed``."""

    __table_args__ = (Index("ix_recommendations_user_id_created_at", "user_id", "created_at"),)

    def __repr__(self) -> str:
        return f"<Recommendation id={self.id} status={self.status.value}>"
