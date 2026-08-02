"""Shared FastAPI dependencies.

``reader_context_dependency`` is the one production path a *route* uses to
get a ``ReaderContext`` — wiring it through ``Depends`` rather than calling
``services.reading_sessions.get_reader_context`` inline in each route body
means the dependency graph itself records which routes are ordinal-scoped,
which is what ``tests/test_reader_context_coverage.py`` inspects (ADR-0002
amendment: every reader-facing route returning media-derived content must
pass through a ``ReaderContext``, checked rather than remembered).

``require_owner_session`` (M7 session 2, ADR-0017) is the other half of
"who is allowed to ask" versus that dependency's "which position are they
allowed to see" — every owner-scoped router depends on it at the
router level (``tests/test_owner_session_coverage.py`` enforces this the
same way ``test_reader_context_coverage.py`` enforces the ordinal one).
"""

from __future__ import annotations

import datetime as dt

# `uuid`/`Request` stay real imports, not TYPE_CHECKING-only — these are
# dependency callables FastAPI inspects to resolve a path parameter or the
# request itself, same reasoning as `api/routers/captures.py`'s equivalent
# comment: verified empirically that a TYPE_CHECKING-only import here
# raises PydanticUserError on the first request.
import uuid  # noqa: TC003
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, status

from alam.auth.tokens import COOKIE_NAME, signing_key, verify_token
from alam.config.settings import Settings, get_settings
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


def require_owner_session(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Gates every owner-scoped router (M7 session 2, ADR-0017). Fails
    closed when no password is configured, same "unset means refuse, not
    open" idiom every other secret-gated check in this codebase uses — an
    unset environment variable must not leave every owner-scoped route
    reachable to anyone who finds the URL."""
    expected = settings.owner_password
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="owner session auth is not configured",
        )

    token = request.cookies.get(COOKIE_NAME)
    if token is None or not verify_token(
        token, secret=signing_key(expected), now=dt.datetime.now(dt.UTC)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing or invalid session"
        )
