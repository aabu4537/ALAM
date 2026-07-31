from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from alam.persistence.models.media_item import MediaItem, MediaType

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session


class MediaItemRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        user_id: uuid.UUID,
        title: str,
        media_type: MediaType = MediaType.BOOK,
        attributes: dict[str, Any] | None = None,
    ) -> MediaItem:
        item = MediaItem(
            user_id=user_id,
            title=title,
            media_type=media_type,
            attributes=attributes or {},
        )
        self._session.add(item)
        self._session.flush()
        return item

    def get(self, media_item_id: uuid.UUID) -> MediaItem | None:
        return self._session.get(MediaItem, media_item_id)

    def list_for_user(
        self, user_id: uuid.UUID, *, media_type: MediaType | None = None
    ) -> Sequence[MediaItem]:
        stmt = select(MediaItem).where(MediaItem.user_id == user_id)
        if media_type is not None:
            stmt = stmt.where(MediaItem.media_type == media_type)
        return self._session.scalars(stmt.order_by(MediaItem.title)).all()

    def mark_structure_verified(
        self, item: MediaItem, *, at: dt.datetime | None = None
    ) -> MediaItem:
        """Record that a human confirmed this item's structure.

        ADR-0004 step 5: only after this may content be indexed against the
        structure. Callers that index should check, not assume.
        """
        item.structure_verified_at = at or dt.datetime.now(dt.UTC)
        self._session.flush()
        return item

    def delete(self, item: MediaItem) -> None:
        self._session.delete(item)
