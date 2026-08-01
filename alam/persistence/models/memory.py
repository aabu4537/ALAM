"""The ``memories`` table — ADR-0001's L2 episodic memory tier.

M2 scope only: no embedding or tsvector column yet. Those arrive at M3 (rule 7
— a table carrying an embedding must also carry ``embedding_model`` and
``embedding_version``, and neither exists until M3 actually computes one).

``structure_ordinal`` is denormalized per CLAUDE.md rule 1, inherited from the
capture that produced the memory — every memory one capture fans out into
shares the reader's position at record time.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MemoryType(enum.StrEnum):
    """ADR-0001's fixed enum, plus the ``other`` escape hatch that keeps
    extraction accuracy measurable rather than forcing every memory into a
    category that doesn't fit."""

    PREDICTION = "prediction"
    OPINION = "opinion"
    EMOTIONAL_REACTION = "emotional_reaction"
    CONFUSION = "confusion"
    CHARACTER_JUDGMENT = "character_judgment"
    FAVORITE_MOMENT = "favorite_moment"
    META_COMMENT = "meta_comment"
    OTHER = "other"


class Memory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memories"

    capture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("captures.id", ondelete="CASCADE"), nullable=False, index=True
    )
    media_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    structure_unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_structure_units.id"), nullable=False
    )
    """Not ``ondelete="CASCADE"``, same reasoning as
    ``Capture.structure_unit_id`` — a chapter with memories already extracted
    against it cannot be silently excluded during re-verification."""

    structure_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    """Denormalized so the spoiler filter (ADR-0002 layer 1, built at M3) is
    an index-only predicate. CLAUDE.md rule 1: do not normalize this away."""

    memory_type: Mapped[MemoryType] = mapped_column(
        Enum(
            MemoryType,
            name="memory_type",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)
    """The canonicalized statement, not the raw transcript (ADR-0001) — this
    is what M3 embeds."""

    prompt_version_id: Mapped[str] = mapped_column(String(100), nullable=False)
    """Rule 6: every LLM output records the prompt version that produced it."""

    consolidated_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """M4: set once this memory has been through a consolidation pass,
    whether or not it produced or reinforced a preference fact. Same idiom
    as ``MediaItem.structure_verified_at`` — NULL means "not yet processed,"
    not "processed and rejected." Without this, a memory the LLM correctly
    judged not preference-bearing would resurface in every future run."""

    __table_args__ = (
        Index("ix_memories_media_item_id_structure_ordinal", "media_item_id", "structure_ordinal"),
        # Partial: the consolidation backlog query paginates by id (UUIDv7,
        # time-ordered) over only unprocessed rows, same reasoning as the
        # jobs table's claim indexes.
        Index(
            "ix_memories_unconsolidated",
            "id",
            postgresql_where=text("consolidated_at IS NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<Memory id={self.id} type={self.memory_type.value} content={self.content[:40]!r}>"
