"""``GET /books/{id}/captures/{capture_id}`` — same missing-ordinal-check
pattern as predictions and structure (ADR-0002 amendment), narrower
reachability (a specific capture id must already be known to the caller),
but closed in the same pass rather than left to re-derive later."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from alam.persistence.repositories import (
    CaptureRepository,
    MediaItemRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from alam.persistence.models import Capture, MediaItem, User


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner", is_demo=False)


@pytest.fixture
def book(session: Session, owner: User) -> MediaItem:
    return MediaItemRepository(session).create(user_id=owner.id, title="Dune")


def _capture_at(session: Session, book: MediaItem, *, ordinal: int) -> Capture:
    unit = StructureUnitRepository(session).create(
        media_item_id=book.id, ordinal=ordinal, label=f"Chapter {ordinal}"
    )
    reading_session = ReadingSessionRepository(session).get_or_create_active(
        book.id, structure_unit_id=unit.id, ordinal=ordinal, progress=1.0
    )
    return CaptureRepository(session).create(
        reading_session_id=reading_session.id,
        media_item_id=book.id,
        structure_unit_id=unit.id,
        structure_ordinal=ordinal,
        audio_data=b"x",
    )


def test_a_capture_at_or_before_the_current_ordinal_is_visible(
    session: Session, client: TestClient, book: MediaItem
) -> None:
    capture = _capture_at(session, book, ordinal=1)

    response = client.get(f"/books/{book.id}/captures/{capture.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(capture.id)


def test_a_capture_past_the_current_ordinal_is_a_404(
    session: Session, client: TestClient, book: MediaItem
) -> None:
    """The re-read hazard: a capture id from a prior, further-along read
    must not be fetchable directly once the active session is back at a
    lower ordinal, even though the caller already knows the exact id."""
    spoiler = _capture_at(session, book, ordinal=9)
    _capture_at(session, book, ordinal=1)  # repositions the active session to 1

    response = client.get(f"/books/{book.id}/captures/{spoiler.id}")

    assert response.status_code == 404


def test_no_active_session_is_a_404(client: TestClient, book: MediaItem) -> None:
    response = client.get(f"/books/{book.id}/captures/{uuid.uuid4()}")

    assert response.status_code == 404
