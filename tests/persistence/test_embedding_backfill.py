from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.ai.providers.fakes import FakeEmbeddingProvider, ProviderError
from alam.config.settings import get_settings
from alam.jobs.job_types import EMBED_MEMORIES_BACKFILL
from alam.persistence.models.job import Job
from alam.persistence.repositories import (
    CaptureRepository,
    MediaItemRepository,
    MemoryEmbeddingRepository,
    MemoryRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)
from alam.services.embedding_backfill import embed_memories_backfill

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import Memory, User


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner")


def _make_memories(session: Session, owner: User, contents: list[str]) -> list[Memory]:
    book = MediaItemRepository(session).create(user_id=owner.id, title="Dune")
    chapter = StructureUnitRepository(session).create(
        media_item_id=book.id, ordinal=1, label="Chapter 1"
    )
    reading_session = ReadingSessionRepository(session).get_or_create_active(
        book.id, structure_unit_id=chapter.id, ordinal=1, progress=1.0
    )
    capture = CaptureRepository(session).create(
        reading_session_id=reading_session.id,
        media_item_id=book.id,
        structure_unit_id=chapter.id,
        structure_ordinal=1,
        audio_data=b"x",
    )
    return MemoryRepository(session).create_many(
        capture_id=capture.id,
        media_item_id=book.id,
        structure_unit_id=chapter.id,
        structure_ordinal=1,
        prompt_version_id="extract-memories-v1",
        extracted=[
            ExtractedMemory(memory_type=ExtractedMemoryType.OPINION, content=c) for c in contents
        ],
    )


class TestEmbedMemoriesBackfill:
    def test_embeds_every_memory_in_one_batch(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeded = _make_memories(session, owner, ["one", "two", "three"])
        fake = FakeEmbeddingProvider(dimensions_=4)
        monkeypatch.setattr("alam.services.embedding_backfill.get_embedding_provider", lambda: fake)

        embed_memories_backfill(session, {"after_id": None})

        embeddings = MemoryEmbeddingRepository(session)
        for memory in seeded:
            rows = embeddings.list_for_memory(memory.id)
            assert len(rows) == 1
            assert len(rows[0].vector) == 4

    def test_records_the_providers_model_and_version(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeded = _make_memories(session, owner, ["one"])
        fake = FakeEmbeddingProvider()
        monkeypatch.setattr("alam.services.embedding_backfill.get_embedding_provider", lambda: fake)

        embed_memories_backfill(session, {"after_id": None})

        row = MemoryEmbeddingRepository(session).list_for_memory(seeded[0].id)[0]
        assert row.embedding_model == fake.model
        assert row.embedding_version == fake.version

    def test_a_second_call_does_not_re_embed_already_covered_memories(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeded = _make_memories(session, owner, ["one", "two"])
        fake = FakeEmbeddingProvider()
        monkeypatch.setattr("alam.services.embedding_backfill.get_embedding_provider", lambda: fake)

        embed_memories_backfill(session, {"after_id": None})
        embed_memories_backfill(session, {"after_id": None})

        assert len(fake.calls) == 1  # the second run found nothing left to embed
        for memory in seeded:
            assert len(MemoryEmbeddingRepository(session).list_for_memory(memory.id)) == 1

    def test_resumes_from_the_cursor_rather_than_the_start(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulates a kill between two batches: the second call is handed
        the first call's cursor directly, as the re-enqueued job would be."""
        seeded = _make_memories(session, owner, ["one", "two", "three"])
        fake = FakeEmbeddingProvider()
        monkeypatch.setattr("alam.services.embedding_backfill.get_embedding_provider", lambda: fake)

        first_id = seeded[0].id
        embed_memories_backfill(session, {"after_id": None})
        # Simulate only the first memory having been covered by a prior,
        # interrupted run: manually roll the other two back to "uncovered" by
        # deleting their rows, then resume from a cursor past the first.
        embeddings = MemoryEmbeddingRepository(session)
        for memory in seeded[1:]:
            for row in embeddings.list_for_memory(memory.id):
                session.delete(row)
        session.flush()

        embed_memories_backfill(session, {"after_id": str(first_id)})

        for memory in seeded:
            assert len(embeddings.list_for_memory(memory.id)) == 1

    def test_reuses_the_vector_for_identical_content_across_memories(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seeded = _make_memories(session, owner, ["same text", "same text"])
        fake = FakeEmbeddingProvider()
        monkeypatch.setattr("alam.services.embedding_backfill.get_embedding_provider", lambda: fake)

        embed_memories_backfill(session, {"after_id": None})

        assert fake.calls == [["same text"]]  # the second one reused, no second call
        rows = [MemoryEmbeddingRepository(session).list_for_memory(m.id)[0] for m in seeded]
        assert rows[0].vector == rows[1].vector
        assert rows[0].id != rows[1].id

    def test_a_full_batch_chains_the_next_one(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALAM_EMBEDDING_BACKFILL_BATCH_SIZE", "2")
        get_settings.cache_clear()
        seeded = _make_memories(session, owner, ["one", "two", "three"])
        fake = FakeEmbeddingProvider()
        monkeypatch.setattr("alam.services.embedding_backfill.get_embedding_provider", lambda: fake)

        embed_memories_backfill(session, {"after_id": None})

        jobs = session.scalars(select(Job).where(Job.job_type == EMBED_MEMORIES_BACKFILL)).all()
        assert len(jobs) == 1
        assert jobs[0].payload == {"after_id": str(seeded[1].id)}

    def test_a_short_batch_does_not_chain(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALAM_EMBEDDING_BACKFILL_BATCH_SIZE", "10")
        get_settings.cache_clear()
        _make_memories(session, owner, ["one", "two"])
        fake = FakeEmbeddingProvider()
        monkeypatch.setattr("alam.services.embedding_backfill.get_embedding_provider", lambda: fake)

        embed_memories_backfill(session, {"after_id": None})

        jobs = session.scalars(select(Job).where(Job.job_type == EMBED_MEMORIES_BACKFILL)).all()
        assert jobs == []

    def test_no_memories_at_all_is_a_no_op(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeEmbeddingProvider()
        monkeypatch.setattr("alam.services.embedding_backfill.get_embedding_provider", lambda: fake)

        embed_memories_backfill(session, {"after_id": None})  # must not raise

        assert fake.calls == []

    def test_provider_failure_propagates_for_the_runner_to_record(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_memories(session, owner, ["one"])
        fake = FakeEmbeddingProvider(fail_with=ProviderError("rate limited"))
        monkeypatch.setattr("alam.services.embedding_backfill.get_embedding_provider", lambda: fake)

        with pytest.raises(ProviderError):
            embed_memories_backfill(session, {"after_id": None})
