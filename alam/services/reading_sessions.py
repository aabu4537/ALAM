"""Reading session lifecycle outside of capture submission, plus
``ReaderContext`` construction. Starting/advancing a session happens
implicitly as a side effect of ``services.capture_submission.submit_capture``,
per ADR-0004: there is no separate "start reading" step to forget about.

``get_reader_context`` is the one production path that produces a
``domain.reader_context.ReaderContext`` — it reads ``current_ordinal`` off
the media item's active ``ReadingSession`` rather than accepting one from a
caller, so a retrieval request can name a book and a user but never an
ordinal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.domain.reader_context import ReaderContext
from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.reading_sessions import ReadingSessionRepository

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from alam.persistence.models import ReadingSession, ReadingSessionStatus


class UnknownReadingSessionError(ValueError):
    """``reading_session_id`` doesn't resolve to this user's session, or the
    media item has no active reading session at all."""


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


def get_reader_context(
    session: Session, *, user_id: uuid.UUID, media_item_id: uuid.UUID
) -> ReaderContext:
    """Builds a ``ReaderContext`` from the media item's active reading
    session. Raises rather than defaulting an ordinal if the book doesn't
    belong to this user or has no active session — there is no ordinal that
    would be correct to substitute."""
    item = MediaItemRepository(session).get(media_item_id)
    if item is None or item.user_id != user_id:
        raise UnknownReadingSessionError(f"no reading session for media item {media_item_id}")

    reading_session = ReadingSessionRepository(session).get_active_for_media_item(media_item_id)
    if reading_session is None:
        raise UnknownReadingSessionError(
            f"no active reading session for media item {media_item_id}"
        )

    return ReaderContext(
        media_item_id=media_item_id,
        user_id=user_id,
        current_ordinal=reading_session.current_ordinal,
    )
