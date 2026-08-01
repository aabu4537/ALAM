"""The ``journey_summaries`` table (M6 session 1, ADR-0013).

One row per generated artifact, not one row per book updated in place — a
new generation (because the prior one went stale) is a new row, so a
``blocked_leaked`` draft is never silently discarded and a failed attempt
stays around for retry visibility. ``get_latest_for_media_item`` is what
callers use to find "the current one."

Written ``pending`` (id, ``media_item_id``, ``generated_at_ordinal`` only)
*before* the LLM call, then updated to a terminal status after — the shared
persisted-artifact pattern every M6 synthesis table follows (rule 6, and the
project's "nothing is thrown away" memory philosophy).
"""

from __future__ import annotations

import enum
import uuid
from typing import Any

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class JourneySummaryStatus(enum.StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    FAILED = "failed"
    BLOCKED_LEAKED = "blocked_leaked"
    """Layer 3 flagged the draft. The draft is retained on the row for audit
    but must never be serialized in an API response — see
    ``services/journey_summary.py``."""


class JourneySummary(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "journey_summaries"

    media_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[JourneySummaryStatus] = mapped_column(
        Enum(
            JourneySummaryStatus,
            name="journey_summary_status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=JourneySummaryStatus.PENDING,
    )

    generated_at_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    """The reader's ``current_ordinal`` captured when this row was created —
    what ``domain.synthesis_staleness.is_artifact_stale`` compares the
    reader's *current* position against to decide whether to regenerate."""

    prompt_version_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    """Rule 6. Null until ``status`` reaches a terminal value."""

    model: Mapped[str | None] = mapped_column(String(200), nullable=True)

    draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The generated prose. Set for both ``complete`` and ``blocked_leaked`` —
    a blocked draft is kept for audit, just never returned by the API."""

    layer3_leaked: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    layer3_spans: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    """Verbatim substrings of ``draft`` the Layer 3 classifier flagged.
    ``None`` until the check runs; empty list once it runs clean."""

    excluded_snapshot: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    """The memory ids/content retrieved but excluded by the ordinal filter at
    generation time, recorded for audit even though they are never shown to
    the reader — also what the Layer 3 classifier checks the draft against."""

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Set only when ``status=failed`` (an exception during generation, not a
    Layer 3 block — that has its own status)."""

    __table_args__ = (
        Index("ix_journey_summaries_media_item_id_created_at", "media_item_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<JourneySummary id={self.id} status={self.status.value}>"
