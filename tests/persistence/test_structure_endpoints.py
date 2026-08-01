"""``GET /books/{id}/structure`` (verification read) and ``GET
/books/{id}/chapters`` (reading read) — split per the ADR-0002 amendment:
the same route used to serve both purposes unfiltered forever, which left
every future chapter's label and up to 240 characters of raw book prose
(``first_lines``) reachable at any point during an active read."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alam.persistence.repositories import (
    MediaItemRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem, User


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner", is_demo=False)


@pytest.fixture
def book(session: Session, owner: User) -> MediaItem:
    return MediaItemRepository(session).create(user_id=owner.id, title="Dune")


class TestVerificationRead:
    def test_returns_the_full_unfiltered_structure_while_unverified(
        self, session: Session, client: TestClient, book: MediaItem
    ) -> None:
        StructureUnitRepository(session).create(
            media_item_id=book.id, ordinal=1, label="Chapter 1", first_lines="It began..."
        )
        StructureUnitRepository(session).create(
            media_item_id=book.id, ordinal=2, label="Chapter 2", first_lines="Later..."
        )

        response = client.get(f"/books/{book.id}/structure")

        assert response.status_code == 200
        body = response.json()
        assert body["structure_verified"] is False
        assert [u["first_lines"] for u in body["units"]] == ["It began...", "Later..."]

    def test_refuses_once_verified(
        self, session: Session, client: TestClient, book: MediaItem
    ) -> None:
        StructureUnitRepository(session).create(
            media_item_id=book.id, ordinal=1, label="Chapter 1", first_lines="It began..."
        )
        MediaItemRepository(session).mark_structure_verified(book)

        response = client.get(f"/books/{book.id}/structure")

        assert response.status_code == 409
        assert "chapters" in response.json()["detail"]

    def test_a_book_belonging_to_someone_else_is_a_404(
        self, session: Session, client: TestClient
    ) -> None:
        UserRepository(session).create(display_name="Owner", is_demo=False)
        someone_else = UserRepository(session).create(display_name="Someone Else", is_demo=False)
        book = MediaItemRepository(session).create(user_id=someone_else.id, title="Not Yours")

        response = client.get(f"/books/{book.id}/structure")

        assert response.status_code == 404


class TestReadingRead:
    def test_first_lines_is_never_present_in_the_response_shape(
        self, session: Session, client: TestClient, book: MediaItem
    ) -> None:
        """Not "empty" or "null" — absent as a key entirely, since the
        reading read's response model has no such field (ADR-0002
        amendment): a filtered value and a missing field look identical on
        the wire, but only one of them is structurally guaranteed."""
        unit = StructureUnitRepository(session).create(
            media_item_id=book.id, ordinal=1, label="Chapter 1", first_lines="It began..."
        )
        ReadingSessionRepository(session).get_or_create_active(
            book.id, structure_unit_id=unit.id, ordinal=1, progress=0.1
        )

        response = client.get(f"/books/{book.id}/chapters")

        assert response.status_code == 200
        [row] = response.json()["units"]
        assert "first_lines" not in row

    def test_only_units_up_to_the_current_ordinal_are_returned(
        self, session: Session, client: TestClient, book: MediaItem
    ) -> None:
        units_repo = StructureUnitRepository(session)
        seen = units_repo.create(media_item_id=book.id, ordinal=1, label="Chapter 1")
        future = units_repo.create(
            media_item_id=book.id, ordinal=5, label="Chapter 5: The Death of Everyone"
        )
        ReadingSessionRepository(session).get_or_create_active(
            book.id, structure_unit_id=seen.id, ordinal=1, progress=0.1
        )

        response = client.get(f"/books/{book.id}/chapters")

        assert response.status_code == 200
        labels = [u["label"] for u in response.json()["units"]]
        assert "Chapter 1" in labels
        assert future.label not in labels

    def test_no_active_session_is_a_404(self, client: TestClient, book: MediaItem) -> None:
        response = client.get(f"/books/{book.id}/chapters")

        assert response.status_code == 404

    def test_available_regardless_of_verification_state(
        self, session: Session, client: TestClient, book: MediaItem
    ) -> None:
        """The reading read isn't gated on verification the way the
        verification read is gated against it — a session existing at all
        is the only precondition, matching GET .../memories."""
        unit = StructureUnitRepository(session).create(
            media_item_id=book.id, ordinal=1, label="Chapter 1"
        )
        ReadingSessionRepository(session).get_or_create_active(
            book.id, structure_unit_id=unit.id, ordinal=1, progress=0.1
        )
        MediaItemRepository(session).mark_structure_verified(book)

        response = client.get(f"/books/{book.id}/chapters")

        assert response.status_code == 200
