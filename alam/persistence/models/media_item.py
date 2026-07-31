"""The ``media_items`` table.

One table with a ``media_type`` discriminator and a JSONB ``attributes`` column,
per ADR-0003. No per-type tables — those make every media-agnostic query
polymorphic, and memory, retrieval, profile, and prediction code only ever
touches ordinals and ``media_item_id``.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class MediaType(enum.StrEnum):
    """V1 is books only. Later types are added by ``ALTER TYPE ... ADD VALUE``.

    The point of ADR-0003 is that adding one costs a migration and a
    ``MediaProvider`` implementation, not an architectural change.
    """

    BOOK = "book"


class MediaItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "media_items"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    media_type: Mapped[MediaType] = mapped_column(
        # native_enum=False renders VARCHAR + CHECK rather than a Postgres ENUM
        # type. ADR-0003 expects new media types to be added, and widening a
        # CHECK is an ordinary migration where ALTER TYPE ADD VALUE is not.
        Enum(
            MediaType,
            name="media_type",
            native_enum=False,
            # SQLAlchemy 2.0 defaults this to False, which yields a bare VARCHAR
            # with no validation at all — the enum would be enforced only by the
            # ORM, and any raw SQL or backfill could write nonsense.
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(String(500), nullable=False)

    attributes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    """Type-specific metadata — author, ISBN, page count, publisher for books.

    Unvalidated at the database level by design (ADR-0003). Type safety is the
    Pydantic boundary model's job, and ADR-0003 flags that as the thing most
    likely to slip. Not queried in hot paths.
    """

    structure_verified_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """When a human confirmed this item's structure units.

    NULL means the structure is still a hypothesis. ADR-0004 is explicit that
    spine order is not the answer and that **nothing may be indexed against
    unverified structure** — this column is what makes that checkable rather
    than aspirational.
    """

    __table_args__ = (Index("ix_media_items_user_id_media_type", "user_id", "media_type"),)

    @property
    def structure_is_verified(self) -> bool:
        return self.structure_verified_at is not None

    def __repr__(self) -> str:
        return f"<MediaItem id={self.id} type={self.media_type.value} title={self.title!r}>"
