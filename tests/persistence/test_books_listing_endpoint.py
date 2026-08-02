"""``GET /books`` (M7 session 3): the owner's whole library, backing the
frontend's home page. Mirrors ``test_recommendations_endpoint.py``'s
no-owner-renders-empty-list precedent, and separately confirms the demo
persona's own books never leak into this response (CLAUDE.md rule 9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.reading_sessions import ReadingSessionRepository
from alam.persistence.repositories.structure_units import StructureUnitRepository
from alam.persistence.repositories.users import UserRepository

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from alam.persistence.models import User


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner", is_demo=False)


def test_no_owner_returns_an_empty_list_not_a_404(client: TestClient) -> None:
    response = client.get("/books")

    assert response.status_code == 200
    assert response.json() == {"books": []}


def test_lists_the_owners_books_with_status_fields(
    session: Session, client: TestClient, owner: User
) -> None:
    item = MediaItemRepository(session).create(
        user_id=owner.id,
        title="Dune",
        attributes={"author": "Frank Herbert", "my_rating": 5, "exclusive_shelf": "to-read"},
    )
    StructureUnitRepository(session).create(media_item_id=item.id, ordinal=1, label="Chapter 1")
    StructureUnitRepository(session).create(media_item_id=item.id, ordinal=2, label="Chapter 2")

    response = client.get("/books")

    assert response.status_code == 200
    body = response.json()
    assert body["books"] == [
        {
            "id": str(item.id),
            "title": "Dune",
            "author": "Frank Herbert",
            "my_rating": 5,
            "exclusive_shelf": "to-read",
            "structure_verified": False,
            "has_active_reading_session": False,
            "chapter_count": 2,
        }
    ]


def test_a_book_with_an_active_reading_session_is_flagged(
    session: Session, client: TestClient, owner: User
) -> None:
    item = MediaItemRepository(session).create(user_id=owner.id, title="Dune", attributes={})
    unit = StructureUnitRepository(session).create(
        media_item_id=item.id, ordinal=1, label="Chapter 1"
    )
    MediaItemRepository(session).mark_structure_verified(item)
    ReadingSessionRepository(session).get_or_create_active(
        item.id, structure_unit_id=unit.id, ordinal=1, progress=0.0
    )

    response = client.get("/books")

    body = response.json()
    assert body["books"][0]["structure_verified"] is True
    assert body["books"][0]["has_active_reading_session"] is True


def test_the_demo_personas_books_never_appear(
    session: Session, client: TestClient, owner: User
) -> None:
    MediaItemRepository(session).create(user_id=owner.id, title="Owner's Book", attributes={})
    demo_user = UserRepository(session).create(display_name="Demo Reader", is_demo=True)
    MediaItemRepository(session).create(user_id=demo_user.id, title="Demo Book", attributes={})

    response = client.get("/books")

    titles = [b["title"] for b in response.json()["books"]]
    assert titles == ["Owner's Book"]
