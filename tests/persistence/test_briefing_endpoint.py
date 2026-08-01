"""``GET /books/{id}/briefing`` (M6 session 4): exercises the whole path —
router, owner resolution, the active-reading-session refusal,
``get_or_generate_briefing`` — rather than the service function in
isolation, same reasoning ``test_journey_summary_endpoint.py`` gives.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

import pytest

from alam.ai.providers.fakes import FakeLLM
from alam.persistence.repositories import (
    MediaItemRepository,
    PreferenceFactRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem, PreferenceFact, User


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner", is_demo=False)


def _unstarted_book(session: Session, owner: User, *, title: str = "Dune") -> MediaItem:
    return MediaItemRepository(session).create(
        user_id=owner.id, title=title, attributes={"author": "Frank Herbert"}
    )


def _unstarted_book_with_catalog(
    session: Session, owner: User, *, title: str = "Dune"
) -> MediaItem:
    return MediaItemRepository(session).create(
        user_id=owner.id,
        title=title,
        attributes={
            "author": "Frank Herbert",
            "catalog": {
                "blurb": "A desert planet and the boy who would rule it.",
                "subjects": ["Science fiction"],
                "series": None,
                "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
            },
        },
    )


def _fact(session: Session, owner: User) -> PreferenceFact:
    return PreferenceFactRepository(session).create(
        user_id=owner.id,
        statement="loves unreliable narrators",
        base_confidence=0.8,
        observed_at=dt.datetime.now(dt.UTC),
        evidence_memory_ids=[],
    )


def test_generates_and_returns_a_briefing_with_teaser_and_claim(
    session: Session, client: TestClient, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = _unstarted_book_with_catalog(session, owner)
    fact = _fact(session, owner)
    canned = '{"cites": [{"type": "preference_fact", "id": "' + str(fact.id) + '"}]}'
    monkeypatch.setattr(
        "alam.services.briefing.get_llm_provider", lambda: FakeLLM(responses=[canned])
    )

    response = client.get(f"/books/{book.id}/briefing")

    assert response.status_code == 200
    body = response.json()
    assert body["media_item_id"] == str(book.id)
    assert body["title"] == "Dune"
    assert body["author"] == "Frank Herbert"
    assert body["blurb"] == "A desert planet and the boy who would rule it."
    assert body["subjects"] == ["Science fiction"]
    assert body["claims"] == [
        {"text": fact.statement, "cites_type": "preference_fact", "cites_id": str(fact.id)}
    ]


def test_a_book_with_no_catalog_data_still_returns_a_briefing_with_no_teaser(
    session: Session, client: TestClient, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = _unstarted_book(session, owner)
    fact = _fact(session, owner)
    canned = '{"cites": [{"type": "preference_fact", "id": "' + str(fact.id) + '"}]}'
    monkeypatch.setattr(
        "alam.services.briefing.get_llm_provider", lambda: FakeLLM(responses=[canned])
    )

    response = client.get(f"/books/{book.id}/briefing")

    assert response.status_code == 200
    body = response.json()
    assert body["blurb"] is None
    assert body["subjects"] == []
    assert body["claims"][0]["cites_type"] == "preference_fact"


def test_an_ungrounded_citation_returns_503_not_the_claims(
    session: Session, client: TestClient, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = _unstarted_book(session, owner)
    _fact(session, owner)  # a real fact, never cited below
    bogus_fact_id = "00000000-0000-0000-0000-000000000000"
    canned = '{"cites": [{"type": "preference_fact", "id": "' + bogus_fact_id + '"}]}'
    monkeypatch.setattr(
        "alam.services.briefing.get_llm_provider", lambda: FakeLLM(responses=[canned])
    )

    response = client.get(f"/books/{book.id}/briefing")

    assert response.status_code == 503
    assert book.title not in response.text


def test_unknown_book_is_a_404(client: TestClient, owner: User) -> None:
    bogus_id = uuid.uuid4()
    response = client.get(f"/books/{bogus_id}/briefing")

    assert response.status_code == 404


def test_no_owner_at_all_is_a_404(client: TestClient) -> None:
    response = client.get(f"/books/{uuid.uuid4()}/briefing")

    assert response.status_code == 404


def test_a_book_belonging_to_someone_else_is_a_404(session: Session, client: TestClient) -> None:
    UserRepository(session).create(display_name="Owner", is_demo=False)
    someone_else = UserRepository(session).create(display_name="Someone Else", is_demo=False)
    book = _unstarted_book(session, someone_else)

    response = client.get(f"/books/{book.id}/briefing")

    assert response.status_code == 404


def test_a_book_with_an_active_reading_session_is_a_409(
    session: Session, client: TestClient, owner: User
) -> None:
    book = _unstarted_book(session, owner)
    unit = StructureUnitRepository(session).create(media_item_id=book.id, ordinal=1, label="Ch 1")
    ReadingSessionRepository(session).get_or_create_active(
        book.id, structure_unit_id=unit.id, ordinal=1, progress=0.1
    )

    response = client.get(f"/books/{book.id}/briefing")

    assert response.status_code == 409
    assert "journey-summary" in response.text
