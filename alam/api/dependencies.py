"""Shared FastAPI dependencies.

``reader_context_dependency`` is the one production path a *route* uses to
get a ``ReaderContext`` — wiring it through ``Depends`` rather than calling
``services.reading_sessions.get_reader_context`` inline in each route body
means the dependency graph itself records which routes are ordinal-scoped,
which is what ``tests/test_reader_context_coverage.py`` inspects (ADR-0002
amendment: every reader-facing route returning media-derived content must
pass through a ``ReaderContext``, checked rather than remembered).
"""

from __future__ import annotations

# `uuid` stays a real import, not TYPE_CHECKING-only — this is a dependency
# callable FastAPI inspects to resolve `media_item_id` as a path parameter,
# same reasoning as `api/routers/captures.py`'s equivalent comment: verified
# empirically that a TYPE_CHECKING-only import here raises PydanticUserError
# on the first request.
import uuid  # noqa: TC003
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, status

from alam.persistence.repositories.users import UserRepository
from alam.persistence.session import session_scope
from alam.services.reading_sessions import UnknownReadingSessionError, get_reader_context

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.domain.reader_context import ReaderContext


def reader_context_dependency(
    media_item_id: uuid.UUID, session: Session = Depends(session_scope)
) -> ReaderContext:
    """Resolves ``media_item_id`` against the single owner's active reading
    session. 404s — never a caller-suppliable ordinal, never a distinction
    between "not yours" and "no active session" — for the same reason
    ``get_reader_context`` itself doesn't distinguish them: either way,
    nothing at or past the reader's real position should be reachable."""
    owner = UserRepository(session).get_owner()
    if owner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="book not found")

    try:
        return get_reader_context(session, user_id=owner.id, media_item_id=media_item_id)
    except UnknownReadingSessionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
