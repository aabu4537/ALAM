"""The ``reading_sessions`` table (ADR-0004).

Progress lives here, not on ``media_items`` — sessions are many-to-one so a
re-read gets its own history instead of overwriting the first one. ``status``
carries ``abandoned`` as a first-class value: a DNF is one of the strongest
preference signals available and must never be deleted.

``current_ordinal`` is denormalized from ``current_structure_unit_id`` for the
same reason ``structure_ordinal`` is denormalized onto ``memories`` (CLAUDE.md
rule 1) — an index-only read of "where is the reader now" rather than a join.
Structure verification (ADR-0004 step 3) is the one thing that can move a unit's
ordinal out from under a session; ``services/structure_plan.py`` resyncs it
when that happens.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import CheckConstraint, DateTime, Enum, Float, ForeignKey, Index, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ReadingSessionStatus(enum.StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class ReadingSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "reading_sessions"

    media_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[ReadingSessionStatus] = mapped_column(
        Enum(
            ReadingSessionStatus,
            name="reading_session_status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ReadingSessionStatus.ACTIVE,
    )

    current_structure_unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_structure_units.id"), nullable=False
    )
    """Deliberately not ``ondelete="CASCADE"``. Excluding a chapter that a
    session has already progressed through must fail loudly — an
    ``IntegrityError`` — rather than silently orphan the session's position."""

    current_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    current_progress: Mapped[float] = mapped_column(Float, nullable=False)
    """0-1, display only. See ``domain/reading_progress.py``."""

    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "current_progress >= 0 AND current_progress <= 1",
            name="current_progress_range",
        ),
        Index("ix_reading_sessions_media_item_id_status", "media_item_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<ReadingSession id={self.id} media_item_id={self.media_item_id} "
            f"status={self.status.value}>"
        )
