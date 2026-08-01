"""``GET /books/{media_item_id}/memories`` (M3's first production caller of
``retrieve_memories``): the endpoint never accepts an ordinal from the
request, so this exercises the whole path — router, ``get_reader_context``,
``retrieve_memories`` — rather than the function in isolation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.ai.providers.fakes import FakeEmbeddingProvider
from alam.persistence.repositories import (
    CaptureRepository,
    MediaItemRepository,
    MemoryEmbeddingRepository,
    MemoryRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem, Memory, User


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
    fake = FakeEmbeddingProvider()
    [embedding] = fake.embed([content])
    MemoryEmbeddingRepository(session).create(
        memory_id=memory.id,
        embedding_model=embedding.model,
        embedding_version=embedding.version,
        content_hash=f"test-hash-{memory.id}",
        vector=embedding.vector,
    )
    return memory


def test_returns_visible_memories_for_the_owners_active_session(
    session: Session, client: TestClient, book: MediaItem, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeEmbeddingProvider()
    monkeypatch.setattr("alam.ai.retrieval.hybrid.get_embedding_provider", lambda: fake)

    memory = _memory_at(session, book, ordinal=1, content="the sandworm attacks the harvester")

    response = client.get(f"/books/{book.id}/memories", params={"query": "sandworm attacks"})

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert str(memory.id) in ids


def test_never_leaks_a_memory_past_the_active_sessions_ordinal(
    session: Session, client: TestClient, book: MediaItem, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The endpoint never takes an ordinal from the request — it reads
    ``current_ordinal`` off the active reading session, which ``_memory_at``
    repositions with each call. Seeding the spoiler (ordinal 9) before the
    seen memory (ordinal 1) leaves the session at ordinal 1, so a request
    against this book must not surface ordinal 9 even though it exists —
    this proves the ordinal actually enforced is the session's current
    position, not something a caller could raise by asking nicely."""
    fake = FakeEmbeddingProvider()
    monkeypatch.setattr("alam.ai.retrieval.hybrid.get_embedding_provider", lambda: fake)

    spoiler = _memory_at(
        session, book, ordinal=9, content="the sandworm attacks the harvester again"
    )
    seen = _memory_at(session, book, ordinal=1, content="the sandworm attacks the harvester")

    response = client.get(f"/books/{book.id}/memories", params={"query": "sandworm attacks"})

    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert str(seen.id) in ids
    assert str(spoiler.id) not in ids


def test_no_active_session_is_a_404(
    client: TestClient, book: MediaItem, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeEmbeddingProvider()
    monkeypatch.setattr("alam.ai.retrieval.hybrid.get_embedding_provider", lambda: fake)

    response = client.get(f"/books/{book.id}/memories", params={"query": "anything"})

    assert response.status_code == 404


def test_a_book_belonging_to_someone_else_is_a_404(
    session: Session, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``get_owner()`` resolves whichever non-demo user the request's session
    belongs to; a book owned by a different user id must 404 rather than
    leak, even though this app's bootstrap never produces two such users in
    practice — the ownership check inside ``get_reader_context`` is what's
    under test here, not the single-owner invariant."""
    fake = FakeEmbeddingProvider()
    monkeypatch.setattr("alam.ai.retrieval.hybrid.get_embedding_provider", lambda: fake)

    UserRepository(session).create(display_name="Owner", is_demo=False)
    someone_else = UserRepository(session).create(display_name="Someone Else", is_demo=False)
    book = MediaItemRepository(session).create(user_id=someone_else.id, title="Not Yours")
    _memory_at(session, book, ordinal=1, content="irrelevant")

    response = client.get(f"/books/{book.id}/memories", params={"query": "anything"})

    assert response.status_code == 404
