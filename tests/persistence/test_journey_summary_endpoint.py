"""``GET /books/{media_item_id}/journey-summary`` (M6 session 1): exercises
the whole path — router, ``reader_context_dependency``,
``get_or_generate_journey_summary`` — rather than the service function in
isolation, same reasoning ``test_memory_search_endpoint.py`` gives.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.ai.providers.fakes import FakeLLM
from alam.persistence.repositories import (
    CaptureRepository,
    MediaItemRepository,
    MemoryRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem, Memory, User

_SUMMARY_OK = '{"narrative": "They loved the opening chapters."}'
_LEAK_CLEAN = '{"leaked": false, "spans": []}'
_LEAK_DIRTY = '{"leaked": true, "spans": ["Paul becomes emperor"]}'


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner", is_demo=False)


@pytest.fixture
def book(session: Session, owner: User) -> MediaItem:
    return MediaItemRepository(session).create(user_id=owner.id, title="Dune")


def _memory_at(session: Session, book: MediaItem, *, ordinal: int, content: str) -> Memory:
    unit = StructureUnitRepository(session).create(
        media_item_id=book.id, ordinal=ordinal, label=f"Chapter {ordinal}"
    )
    reading_session = ReadingSessionRepository(session).get_or_create_active(
        book.id, structure_unit_id=unit.id, ordinal=ordinal, progress=1.0
    )
    capture = CaptureRepository(session).create(
        reading_session_id=reading_session.id,
        media_item_id=book.id,
        structure_unit_id=unit.id,
        structure_ordinal=ordinal,
        audio_data=b"x",
    )
    [memory] = MemoryRepository(session).create_many(
        capture_id=capture.id,
        media_item_id=book.id,
        structure_unit_id=unit.id,
        structure_ordinal=ordinal,
        prompt_version_id="extract-memories-v1",
        extracted=[ExtractedMemory(memory_type=ExtractedMemoryType.OPINION, content=content)],
    )
    return memory


def test_generates_and_returns_a_journey_summary(
    session: Session, client: TestClient, book: MediaItem, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_llm = FakeLLM(responses=[_SUMMARY_OK, _LEAK_CLEAN])
    monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: fake_llm)
    _memory_at(session, book, ordinal=1, content="I loved the opening")

    response = client.get(f"/books/{book.id}/journey-summary")

    assert response.status_code == 200
    body = response.json()
    assert body["narrative"] == "They loved the opening chapters."
    assert body["media_item_id"] == str(book.id)
    assert body["prompt_version_id"] == "journey-summary-v1"


def test_a_leaked_draft_returns_503_not_the_draft(
    session: Session, client: TestClient, book: MediaItem, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_llm = FakeLLM(responses=[_SUMMARY_OK, _LEAK_DIRTY])
    monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: fake_llm)
    _memory_at(session, book, ordinal=1, content="I loved the opening")

    response = client.get(f"/books/{book.id}/journey-summary")

    assert response.status_code == 503
    assert "Paul becomes emperor" not in response.text


def test_no_active_session_is_a_404(
    client: TestClient, book: MediaItem, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: FakeLLM())

    response = client.get(f"/books/{book.id}/journey-summary")

    assert response.status_code == 404


def test_never_leaks_future_content_into_the_generated_narrative_context(
    session: Session, client: TestClient, book: MediaItem, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The endpoint never takes an ordinal from the request — it reads
    ``current_ordinal`` off the active reading session, same invariant
    ``test_memory_search_endpoint.py`` checks for ``.../memories``."""
    fake_llm = FakeLLM(responses=[_SUMMARY_OK, _LEAK_CLEAN])
    monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: fake_llm)
    _memory_at(session, book, ordinal=9, content="Paul becomes the emperor")
    _memory_at(session, book, ordinal=1, content="the sandworm attacks")

    response = client.get(f"/books/{book.id}/journey-summary")

    assert response.status_code == 200
    assert "Paul becomes the emperor" not in fake_llm.calls[0].prompt
