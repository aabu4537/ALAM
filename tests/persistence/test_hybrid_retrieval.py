"""Hybrid retrieval (M3): pgvector cosine + Postgres full-text, fused with RRF,
never surfacing anything past the reader's current position (ADR-0002)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.ai.providers.fakes import FakeEmbeddingProvider
from alam.ai.retrieval.hybrid import retrieve_memories
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
    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem, Memory, User


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner")


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


def _embed(session: Session, fake: FakeEmbeddingProvider, memory: Memory) -> None:
    [embedding] = fake.embed([memory.content])
    MemoryEmbeddingRepository(session).create(
        memory_id=memory.id,
        embedding_model=embedding.model,
        embedding_version=embedding.version,
        content_hash=f"test-hash-{memory.id}",
        vector=embedding.vector,
    )


class TestSpoilerContainment:
    def test_never_returns_a_memory_past_the_current_ordinal(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeEmbeddingProvider()
        monkeypatch.setattr("alam.ai.retrieval.hybrid.get_embedding_provider", lambda: fake)

        seen = _memory_at(session, book, ordinal=1, content="the sandworm attacks")
        spoiler = _memory_at(session, book, ordinal=9, content="the sandworm attacks again")
        _embed(session, fake, seen)
        _embed(session, fake, spoiler)

        results = retrieve_memories(
            session, media_item_id=book.id, query="sandworm attacks", current_ordinal=1
        )

        assert seen.id in {m.id for m in results}
        assert spoiler.id not in {m.id for m in results}

    def test_a_memory_exactly_at_the_current_ordinal_is_visible(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeEmbeddingProvider()
        monkeypatch.setattr("alam.ai.retrieval.hybrid.get_embedding_provider", lambda: fake)

        memory = _memory_at(session, book, ordinal=3, content="paul walks the desert")
        _embed(session, fake, memory)

        results = retrieve_memories(
            session, media_item_id=book.id, query="paul walks the desert", current_ordinal=3
        )

        assert memory.id in {m.id for m in results}


class TestScoping:
    def test_never_returns_a_memory_from_a_different_book(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeEmbeddingProvider()
        monkeypatch.setattr("alam.ai.retrieval.hybrid.get_embedding_provider", lambda: fake)

        book_a = MediaItemRepository(session).create(user_id=owner.id, title="Dune")
        book_b = MediaItemRepository(session).create(user_id=owner.id, title="Foundation")

        in_a = _memory_at(session, book_a, ordinal=1, content="hari seldon predicts the future")
        in_b = _memory_at(session, book_b, ordinal=1, content="hari seldon predicts the future")
        _embed(session, fake, in_a)
        _embed(session, fake, in_b)

        results = retrieve_memories(
            session, media_item_id=book_a.id, query="hari seldon predicts", current_ordinal=1
        )

        assert in_a.id in {m.id for m in results}
        assert in_b.id not in {m.id for m in results}

    def test_ignores_embeddings_from_a_different_model_version(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A mid-migration mix of embedding versions must never be compared to
        each other (rule 7) — an old-model row simply isn't a vector-search
        candidate for a query embedded with the current model."""
        current = FakeEmbeddingProvider()
        stale = FakeEmbeddingProvider()
        monkeypatch.setattr("alam.ai.retrieval.hybrid.get_embedding_provider", lambda: current)

        memory = _memory_at(session, book, ordinal=1, content="a lone figure in the desert")
        MemoryEmbeddingRepository(session).create(
            memory_id=memory.id,
            embedding_model=stale.model,
            embedding_version="0-old",
            content_hash=f"stale-{memory.id}",
            vector=stale.embed([memory.content])[0].vector,
        )
        # No row for `current`'s model/version exists, so vector search has
        # nothing to match — only full-text search can find it.

        results = retrieve_memories(
            session, media_item_id=book.id, query="lone figure desert", current_ordinal=1
        )

        assert memory.id in {m.id for m in results}


class TestHybridFusion:
    def test_full_text_finds_what_vector_search_alone_would_miss(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fake embedding provider's vectors carry no semantic meaning —
        a query's vector is close only to the identical text's vector. A
        keyword query that doesn't match any memory verbatim relies entirely
        on the full-text branch, exactly the "invented proper noun" gap
        docs/milestones.md calls out for pure vector search."""
        fake = FakeEmbeddingProvider()
        monkeypatch.setattr("alam.ai.retrieval.hybrid.get_embedding_provider", lambda: fake)

        memory = _memory_at(session, book, ordinal=1, content="Muad'Dib rides the great worm")
        _embed(session, fake, memory)

        results = retrieve_memories(
            session, media_item_id=book.id, query="Muad'Dib worm", current_ordinal=1
        )

        assert memory.id in {m.id for m in results}

    def test_respects_the_requested_limit(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeEmbeddingProvider()
        monkeypatch.setattr("alam.ai.retrieval.hybrid.get_embedding_provider", lambda: fake)

        for i in range(5):
            content = f"the desert stretches on {i}"
            memory = _memory_at(session, book, ordinal=i + 1, content=content)
            _embed(session, fake, memory)

        results = retrieve_memories(
            session, media_item_id=book.id, query="desert stretches", current_ordinal=5, limit=2
        )

        assert len(results) == 2

    def test_no_matches_returns_empty(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeEmbeddingProvider()
        monkeypatch.setattr("alam.ai.retrieval.hybrid.get_embedding_provider", lambda: fake)

        results = retrieve_memories(
            session, media_item_id=book.id, query="anything at all", current_ordinal=1
        )

        assert results == []
