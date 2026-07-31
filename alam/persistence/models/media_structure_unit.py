"""The ``media_structure_units`` table — the real abstraction in this schema.

A chapter for books, an episode for TV, a scene or timestamp bucket for film.
``ordinal`` is the universal ordering key, and every spoiler, timeline, and
prediction query operates on it (ADR-0003). Everything else here is bookkeeping.

``id`` is stable across renumbering and is what later tables key referential
integrity on, while ``ordinal`` is what they denormalize for filtering. See
ADR-0006.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class StructureUnitType(enum.StrEnum):
    CHAPTER = "chapter"
    EPISODE = "episode"
    SCENE = "scene"
    SEGMENT = "segment"


class MediaStructureUnit(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "media_structure_units"

    media_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"), nullable=False
    )

    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    """Position within the media item. The universal ordering key.

    Not stable — verification may merge, split, or exclude units and renumber
    what remains (ADR-0004). Anything needing a durable reference points at
    ``id`` instead and recomputes this value.
    """

    unit_type: Mapped[StructureUnitType] = mapped_column(
        Enum(
            StructureUnitType,
            name="unit_type",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=StructureUnitType.CHAPTER,
    )

    label: Mapped[str] = mapped_column(String(500), nullable=False)
    """Human-facing name — "Chapter 7", "The Bear Comes Home"."""

    first_lines: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Opening text, shown in the verification preview so a human can tell
    front matter from a real chapter (ADR-0004 step 2)."""

    __table_args__ = (
        # DEFERRABLE is load-bearing, not decoration. Postgres checks uniqueness
        # per row, so a bulk renumber such as `SET ordinal = ordinal + 1`
        # transiently collides and aborts under an immediate constraint.
        # Deferring inside the renumbering transaction lets the intermediate
        # state exist and be validated once, at commit. See ADR-0006.
        UniqueConstraint(
            "media_item_id",
            "ordinal",
            name="uq_media_structure_units_media_item_id_ordinal",
            deferrable=True,
            initially="IMMEDIATE",
        ),
        # Covers the ordering read and the `ordinal <= :current` range scan the
        # spoiler filter will issue once memories exist (ADR-0002 layer 1).
        Index("ix_media_structure_units_media_item_id_ordinal", "media_item_id", "ordinal"),
    )

    def __repr__(self) -> str:
        return f"<MediaStructureUnit id={self.id} ordinal={self.ordinal} label={self.label!r}>"
