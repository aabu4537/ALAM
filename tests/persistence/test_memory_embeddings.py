from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import IntegrityError

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
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

    from alam.persistence.models import Memory, User


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner")


@pytest.fixture
def memory(session: Session, owner: User) -> Memory:
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
        extracted=[ExtractedMemory(memory_type=ExtractedMemoryType.OPINION, content="x")],
    )[0]


class TestMemoryEmbeddingRepository:
    def test_create_and_round_trip_the_vector(self, session: Session, memory: Memory) -> None:
        repo = MemoryEmbeddingRepository(session)

        row = repo.create(
            memory_id=memory.id,
            embedding_model="fake-embedding-v1",
            embedding_version="1",
            content_hash="a" * 64,
            vector=[0.1, 0.2, 0.3],
        )
        session.expire(row)

        assert row.vector == pytest.approx([0.1, 0.2, 0.3])

    def test_different_dimension_vectors_coexist_in_the_same_table(
        self, session: Session, memory: Memory
    ) -> None:
        """ADR-0008's whole point: no fixed-width column, so a model swap to
        a different dimension is an insert, not a migration."""
        repo = MemoryEmbeddingRepository(session)

        small = repo.create(
            memory_id=memory.id,
            embedding_model="model-a",
            embedding_version="1",
            content_hash="a" * 64,
            vector=[0.1, 0.2],
        )
        large = repo.create(
            memory_id=memory.id,
            embedding_model="model-b",
            embedding_version="1",
            content_hash="b" * 64,
            vector=[0.1, 0.2, 0.3, 0.4, 0.5],
        )

        assert len(small.vector) == 2
        assert len(large.vector) == 5

    def test_get_by_content_hash_finds_an_existing_row(
        self, session: Session, memory: Memory
    ) -> None:
        repo = MemoryEmbeddingRepository(session)
        repo.create(
            memory_id=memory.id,
            embedding_model="fake-embedding-v1",
            embedding_version="1",
            content_hash="c" * 64,
            vector=[0.1],
        )

        assert repo.get_by_content_hash("c" * 64) is not None

    def test_get_by_content_hash_returns_none_when_absent(self, session: Session) -> None:
        assert MemoryEmbeddingRepository(session).get_by_content_hash("d" * 64) is None

    def test_list_for_memory(self, session: Session, memory: Memory) -> None:
        repo = MemoryEmbeddingRepository(session)
        repo.create(
            memory_id=memory.id,
            embedding_model="model-a",
            embedding_version="1",
            content_hash="a" * 64,
            vector=[0.1],
        )
        repo.create(
            memory_id=memory.id,
            embedding_model="model-b",
            embedding_version="1",
            content_hash="b" * 64,
            vector=[0.2],
        )

        assert len(repo.list_for_memory(memory.id)) == 2

    def test_duplicate_natural_key_is_rejected(self, session: Session, memory: Memory) -> None:
        repo = MemoryEmbeddingRepository(session)
        repo.create(
            memory_id=memory.id,
            embedding_model="fake-embedding-v1",
            embedding_version="1",
            content_hash="e" * 64,
            vector=[0.1],
        )

        with pytest.raises(IntegrityError):
            repo.create(
                memory_id=memory.id,
                embedding_model="fake-embedding-v1",
                embedding_version="1",
                content_hash="f" * 64,
                vector=[0.2],
            )

    def test_two_different_memories_can_share_one_content_hash(
        self, session: Session, owner: User, memory: Memory
    ) -> None:
        """The reason content_hash is an index, not a unique constraint —
        two memories with identical text (duplicate demo data, a repeated
        phrase) each still need their own row, keyed on their own
        memory_id, even though they'd hash identically."""
        other_book = MediaItemRepository(session).create(user_id=owner.id, title="x")
        chapter = StructureUnitRepository(session).create(
            media_item_id=other_book.id, ordinal=1, label="Chapter 1"
        )
        reading_session = ReadingSessionRepository(session).get_or_create_active(
            other_book.id, structure_unit_id=chapter.id, ordinal=1, progress=1.0
        )
        capture = CaptureRepository(session).create(
            reading_session_id=reading_session.id,
            media_item_id=other_book.id,
            structure_unit_id=chapter.id,
            structure_ordinal=1,
            audio_data=b"x",
        )
        other_memory = MemoryRepository(session).create_many(
            capture_id=capture.id,
            media_item_id=other_book.id,
            structure_unit_id=chapter.id,
            structure_ordinal=1,
            prompt_version_id="extract-memories-v1",
            extracted=[ExtractedMemory(memory_type=ExtractedMemoryType.OPINION, content="x")],
        )[0]

        repo = MemoryEmbeddingRepository(session)
        first = repo.create(
            memory_id=memory.id,
            embedding_model="model-a",
            embedding_version="1",
            content_hash="g" * 64,
            vector=[0.1],
        )
        second = repo.create(
            memory_id=other_memory.id,
            embedding_model="model-a",
            embedding_version="1",
            content_hash="g" * 64,
            vector=[0.1],
        )

        assert first.id != second.id
        assert first.memory_id != second.memory_id

    def test_deleting_the_memory_cascades(self, session: Session, memory: Memory) -> None:
        repo = MemoryEmbeddingRepository(session)
        repo.create(
            memory_id=memory.id,
            embedding_model="fake-embedding-v1",
            embedding_version="1",
            content_hash="h" * 64,
            vector=[0.1],
        )

        session.delete(memory)
        session.flush()

        assert repo.list_for_memory(memory.id) == []
