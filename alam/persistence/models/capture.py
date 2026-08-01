"""The ``captures`` table — one voice reflection, moving through the M2
pipeline (transcribe -> correct -> extract) as its ``status`` advances.

``structure_ordinal`` is denormalized from ``structure_unit_id`` for the same
reason ``memories`` will denormalize it (CLAUDE.md rule 1): it is what an
ordinal-ordered read needs, and a join is not.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Index, Integer, LargeBinary, Text
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CaptureStatus(enum.StrEnum):
    PENDING = "pending"
    TRANSCRIBED = "transcribed"
    CORRECTED = "corrected"
    EXTRACTED = "extracted"
    FAILED = "failed"


class Capture(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "captures"

    reading_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reading_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    media_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    structure_unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_structure_units.id"), nullable=False
    )
    """Not ``ondelete="CASCADE"``, same reasoning as
    ``ReadingSession.current_structure_unit_id`` — a chapter with recorded
    reflections against it cannot be silently excluded during
    re-verification."""

    structure_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)

    audio_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, deferred=True)
    """Raw audio bytes. No blob store exists yet (no caller needs one) — short
    voice reflections fit comfortably in a bytea column.

    ``deferred=True``: a plain ``select(Capture)`` / ``session.get(Capture,
    id)`` does not fetch this column. Every status/transcript read path
    (list-for-book, capture-detail, the transcribe/correct/extract handlers'
    own lookups before they need the bytes) would otherwise pull the blob
    across the wire for rows that never touch it. Accessing the attribute
    still works — SQLAlchemy issues a second query lazily the first time it's
    read — this only changes what an ordinary read pulls by default."""

    status: Mapped[CaptureStatus] = mapped_column(
        Enum(
            CaptureStatus,
            name="status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=CaptureStatus.PENDING,
    )

    raw_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_captures_media_item_id_structure_ordinal", "media_item_id", "structure_ordinal"),
    )

    def __repr__(self) -> str:
        return (
            f"<Capture id={self.id} media_item_id={self.media_item_id} status={self.status.value}>"
        )
