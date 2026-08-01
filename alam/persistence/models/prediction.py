"""The ``predictions`` table (M5, ADR-0009).

A prediction is derived 1:1 from a ``memory_type=prediction`` memory at
extraction time — its text lives on that memory (``source_memory_id``), not
duplicated here. What this table adds is the lifecycle the memory itself
doesn't carry: whether the prediction has since been checked against what
happened next, and what was found.

``resolution_window`` is captured per row from settings at creation time
rather than read fresh at resolution time — a later change to the configured
default must not retroactively change what an already-pending prediction is
waiting for.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PredictionStatus(enum.StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    UNRESOLVABLE = "unresolvable"
    """A real outcome, not a failure mode (docs/milestones.md, M5) — some
    predictions are too vague for the evidence window to confirm or refute
    one way or the other, and forcing a side manufactures false precision."""


class Prediction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "predictions"

    source_memory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("memories.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    """``ondelete="CASCADE"``, unlike most FKs in this schema — a prediction
    has no existence independent of the memory that stated it. ``unique``
    because a prediction is derived from its source memory exactly once."""

    media_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), nullable=False
    )
    """Denormalized from the source memory so the resolution job can scope a
    query to one book without joining through ``memories`` (CLAUDE.md rule 1)."""

    made_at_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    """Denormalized from the source memory's ``structure_ordinal`` — the
    reader's position when the prediction was made."""

    resolution_window: Mapped[int] = mapped_column(Integer, nullable=False)
    """How many ordinals of progress must pass before this prediction is
    checked. Resolution fires once the reader's current ordinal reaches
    ``made_at_ordinal + resolution_window``."""

    status: Mapped[PredictionStatus] = mapped_column(
        Enum(
            PredictionStatus,
            name="prediction_status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PredictionStatus.PENDING,
    )

    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    resolution_prompt_version_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    """Rule 6. Null while ``status`` is still ``pending``; set the moment an
    LLM call decides the outcome. Stays null for a window that resolved
    ``unresolvable`` via the no-evidence short-circuit, since no LLM ran."""

    __table_args__ = (Index("ix_predictions_media_item_id_status", "media_item_id", "status"),)

    def __repr__(self) -> str:
        return f"<Prediction id={self.id} status={self.status.value}>"
