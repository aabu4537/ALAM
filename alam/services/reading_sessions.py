"""Reading session lifecycle outside of capture submission — currently just
ending one. Starting/advancing a session happens implicitly as a side effect
of ``services.capture_submission.submit_capture``, per ADR-0004: there is no
separate "start reading" step to forget about.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.reading_sessions import ReadingSessionRepository

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from alam.persistence.models import ReadingSession, ReadingSessionStatus


class UnknownReadingSessionError(ValueError):
    """``reading_session_id`` doesn't resolve to this user's session."""


def end_reading_session(
    session: Session,
    *,
    user_id: uuid.UUID,
    media_item_id: uuid.UUID,
    reading_session_id: uuid.UUID,
    status: ReadingSessionStatus,
) -> ReadingSession:
    sessions = ReadingSessionRepository(session)
    reading_session = sessions.get(reading_session_id)
    if reading_session is None or reading_session.media_item_id != media_item_id:
        raise UnknownReadingSessionError(f"no reading session {reading_session_id}")

    item = MediaItemRepository(session).get(reading_session.media_item_id)
    if item is None or item.user_id != user_id:
        raise UnknownReadingSessionError(f"no reading session {reading_session_id} for this user")

    return sessions.end(reading_session, status=status)
