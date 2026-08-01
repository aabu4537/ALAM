"""``GET /recommendations`` (M6 session 2): exercises the whole path —
router, owner resolution, ``get_or_generate_recommendations`` — rather than
the service function in isolation, same reasoning
``test_journey_summary_endpoint.py`` gives.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest

from alam.ai.providers.fakes import FakeLLM
from alam.persistence.repositories import (
    MediaItemRepository,
    PreferenceFactRepository,
    UserRepository,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem, PreferenceFact, User


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner", is_demo=False)


def _to_read_book(session: Session, owner: User, *, title: str = "Dune") -> MediaItem:
    return MediaItemRepository(session).create(
        user_id=owner.id,
        title=title,
        attributes={"exclusive_shelf": "to-read", "author": "Frank Herbert"},
    )


def _fact(session: Session, owner: User) -> PreferenceFact:
    return PreferenceFactRepository(session).create(
        user_id=owner.id,
        statement="loves unreliable narrators",
        base_confidence=0.8,
        observed_at=dt.datetime.now(dt.UTC),
        evidence_memory_ids=[],
    )


def _to_read_book_with_catalog(session: Session, owner: User, *, title: str = "Dune") -> MediaItem:
    return MediaItemRepository(session).create(
        user_id=owner.id,
        title=title,
        attributes={
            "exclusive_shelf": "to-read",
            "author": "Frank Herbert",
            "catalog": {
                "blurb": "A desert planet and the boy who would rule it.",
                "subjects": ["Science fiction"],
                "series": None,
                "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
            },
        },
    )


def test_generates_and_returns_recommendations(
    session: Session, client: TestClient, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = _to_read_book(session, owner)
    fact = _fact(session, owner)
    canned = (
        '{"recommendations": [{"media_item_id": "'
        + str(book.id)
        + '", "cites": [{"type": "preference_fact", "id": "'
        + str(fact.id)
        + '"}]}]}'
    )
    monkeypatch.setattr(
        "alam.services.recommendations.get_llm_provider", lambda: FakeLLM(responses=[canned])
    )

    response = client.get("/recommendations")

    assert response.status_code == 200
    body = response.json()
    assert len(body["recommendations"]) == 1
    assert body["recommendations"][0]["media_item_id"] == str(book.id)
    assert body["recommendations"][0]["title"] == "Dune"
    assert body["recommendations"][0]["claims"] == [
        {"text": fact.statement, "cites_type": "preference_fact", "cites_id": str(fact.id)}
    ]


def test_an_ungrounded_citation_returns_503_not_the_candidates(
    session: Session, client: TestClient, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    book = _to_read_book(session, owner)
    bogus_fact_id = "00000000-0000-0000-0000-000000000000"
    canned = (
        '{"recommendations": [{"media_item_id": "'
        + str(book.id)
        + '", "cites": [{"type": "preference_fact", "id": "'
        + bogus_fact_id
        + '"}]}]}'
    )
    monkeypatch.setattr(
        "alam.services.recommendations.get_llm_provider", lambda: FakeLLM(responses=[canned])
    )

    response = client.get("/recommendations")

    assert response.status_code == 503
    assert book.title not in response.text


def test_no_owner_returns_an_empty_list_not_a_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: FakeLLM())

    response = client.get("/recommendations")

    assert response.status_code == 200
    assert response.json() == {"id": None, "generated_at": None, "recommendations": []}


def test_an_empty_to_read_shelf_returns_an_empty_list_with_no_llm_call(
    client: TestClient, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_llm = FakeLLM()
    monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

    response = client.get("/recommendations")

    assert response.status_code == 200
    assert response.json()["recommendations"] == []
    assert len(fake_llm.calls) == 0


def test_a_catalog_citation_produces_a_blurb_backed_claim(
    session: Session, client: TestClient, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M6 session 3, ADR-0015: a candidate CatalogProvider has already
    fetched can be recommended with a claim grounded in its own real,
    catalog-sourced description — not the reader's taste alone."""
    book = _to_read_book_with_catalog(session, owner)
    canned = (
        '{"recommendations": [{"media_item_id": "'
        + str(book.id)
        + '", "cites": [{"type": "catalog", "id": "'
        + str(book.id)
        + '"}]}]}'
    )
    monkeypatch.setattr(
        "alam.services.recommendations.get_llm_provider", lambda: FakeLLM(responses=[canned])
    )

    response = client.get("/recommendations")

    assert response.status_code == 200
    body = response.json()
    assert body["recommendations"][0]["claims"] == [
        {
            "text": "A desert planet and the boy who would rule it.",
            "cites_type": "catalog",
            "cites_id": str(book.id),
        }
    ]
