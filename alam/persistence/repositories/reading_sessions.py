from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from sqlalchemy import select

from alam.domain.reading_progress import compute_progress
from alam.persistence.models.reading_session import ReadingSession, ReadingSessionStatus

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session


class ReadingSessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, session_id: uuid.UUID) -> ReadingSession | None:
        return self._session.get(ReadingSession, session_id)

    def get_active_for_media_item(self, media_item_id: uuid.UUID) -> ReadingSession | None:
        return self._session.scalars(
            select(ReadingSession)
            .where(
                ReadingSession.media_item_id == media_item_id,
                ReadingSession.status == ReadingSessionStatus.ACTIVE,
            )
            .order_by(ReadingSession.started_at.desc())
        ).first()

    def get_or_create_active(
        self,
        media_item_id: uuid.UUID,
        *,
        structure_unit_id: uuid.UUID,
        ordinal: int,
        progress: float,
    ) -> ReadingSession:
        """Resumes the media item's active session at the given position, or
        starts one. Re-reads are a new session by construction (ADR-0004) —
        this only ever touches the current active one, created lazily on the
        first capture rather than through a separate "start reading" step."""
        existing = self.get_active_for_media_item(media_item_id)
        if existing is not None:
            return self.advance(
                existing, structure_unit_id=structure_unit_id, ordinal=ordinal, progress=progress
            )

        reading_session = ReadingSession(
            media_item_id=media_item_id,
            status=ReadingSessionStatus.ACTIVE,
            current_structure_unit_id=structure_unit_id,
            current_ordinal=ordinal,
            current_progress=progress,
        )
        self._session.add(reading_session)
        self._session.flush()
        return reading_session

    def advance(
        self,
        reading_session: ReadingSession,
        *,
        structure_unit_id: uuid.UUID,
        ordinal: int,
        progress: float,
    ) -> ReadingSession:
        reading_session.current_structure_unit_id = structure_unit_id
        reading_session.current_ordinal = ordinal
        reading_session.current_progress = progress
        self._session.flush()
        return reading_session

    def end(
        self, reading_session: ReadingSession, *, status: ReadingSessionStatus
    ) -> ReadingSession:
        reading_session.status = status
        reading_session.ended_at = dt.datetime.now(dt.UTC)
        self._session.flush()
        return reading_session

    def resync_position(
        self, *, structure_unit_id: uuid.UUID, ordinal: int, total_units: int
    ) -> None:
        """Repairs a session's denormalized position after structure
        re-verification renumbers the unit it currently points at (ADR-0004,
        ADR-0006). Called from ``services/structure_plan.py``. Recomputes
        ``current_progress`` too, since ``total_units`` can itself change in
        the same re-verification."""
        progress = compute_progress(ordinal, total_units)
        for reading_session in self._session.scalars(
            select(ReadingSession).where(
                ReadingSession.current_structure_unit_id == structure_unit_id
            )
        ):
            reading_session.current_ordinal = ordinal
            reading_session.current_progress = progress
        self._session.flush()
