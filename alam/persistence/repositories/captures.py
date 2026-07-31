from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from alam.persistence.models.capture import Capture

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session


class CaptureRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        reading_session_id: uuid.UUID,
        media_item_id: uuid.UUID,
        structure_unit_id: uuid.UUID,
        structure_ordinal: int,
        audio_data: bytes,
    ) -> Capture:
        capture = Capture(
            reading_session_id=reading_session_id,
            media_item_id=media_item_id,
            structure_unit_id=structure_unit_id,
            structure_ordinal=structure_ordinal,
            audio_data=audio_data,
        )
        self._session.add(capture)
        self._session.flush()
        return capture

    def get(self, capture_id: uuid.UUID) -> Capture | None:
        return self._session.get(Capture, capture_id)

    def list_for_media_item(self, media_item_id: uuid.UUID) -> Sequence[Capture]:
        return self._session.scalars(
            select(Capture)
            .where(Capture.media_item_id == media_item_id)
            .order_by(Capture.created_at)
        ).all()
