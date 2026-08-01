"""PredictionRepository: creation, lifecycle, and evidence linking (M5
session 1)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import IntegrityError

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.persistence.models.prediction import PredictionStatus
from alam.persistence.repositories import (
    CaptureRepository,
    MediaItemRepository,
    MemoryRepository,
    PredictionRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem, Memory, User

pytestmark = pytest.mark.db

NOW = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner")


@pytest.fixture
def book(session: Session, owner: User) -> MediaItem:
    return MediaItemRepository(session).create(user_id=owner.id, title="Dune")


def _make_memory(
    session: Session,
    book: MediaItem,
    *,
    ordinal: int,
    content: str,
    memory_type: ExtractedMemoryType = ExtractedMemoryType.OPINION,
) -> Memory:
    chapter = StructureUnitRepository(session).create(
        media_item_id=book.id, ordinal=ordinal, label=f"Chapter {ordinal}"
    )
    reading_session = ReadingSessionRepository(session).get_or_create_active(
        book.id, structure_unit_id=chapter.id, ordinal=ordinal, progress=1.0
    )
    capture = CaptureRepository(session).create(
        reading_session_id=reading_session.id,
        media_item_id=book.id,
        structure_unit_id=chapter.id,
        structure_ordinal=ordinal,
        audio_data=b"x",
    )
    [memory] = MemoryRepository(session).create_many(
        capture_id=capture.id,
        media_item_id=book.id,
        structure_unit_id=chapter.id,
        structure_ordinal=ordinal,
        prompt_version_id="extract-memories-v1",
        extracted=[ExtractedMemory(memory_type=memory_type, content=content)],
    )
    return memory


class TestCreate:
    def test_creates_a_pending_prediction(self, session: Session, book: MediaItem) -> None:
        memory = _make_memory(
            session,
            book,
            ordinal=1,
            content="the traitor will be Yueh",
            memory_type=ExtractedMemoryType.PREDICTION,
        )
        predictions = PredictionRepository(session)

        prediction = predictions.create(
            source_memory_id=memory.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=10,
        )

        assert prediction.status is PredictionStatus.PENDING
        assert prediction.resolved_at is None
        assert prediction.made_at_ordinal == 1
        assert prediction.resolution_window == 10

    def test_a_memory_can_only_produce_one_prediction(
        self, session: Session, book: MediaItem
    ) -> None:
        memory = _make_memory(
            session,
            book,
            ordinal=1,
            content="the traitor will be Yueh",
            memory_type=ExtractedMemoryType.PREDICTION,
        )
        predictions = PredictionRepository(session)
        predictions.create(
            source_memory_id=memory.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=10,
        )

        with pytest.raises(IntegrityError):
            predictions.create(
                source_memory_id=memory.id,
                media_item_id=book.id,
                made_at_ordinal=1,
                resolution_window=10,
            )


class TestListPendingForMediaItem:
    def test_only_pending_predictions_are_listed(self, session: Session, book: MediaItem) -> None:
        predictions = PredictionRepository(session)
        still_pending_memory = _make_memory(
            session,
            book,
            ordinal=1,
            content="prediction A",
            memory_type=ExtractedMemoryType.PREDICTION,
        )
        resolved_memory = _make_memory(
            session,
            book,
            ordinal=2,
            content="prediction B",
            memory_type=ExtractedMemoryType.PREDICTION,
        )
        still_pending = predictions.create(
            source_memory_id=still_pending_memory.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=10,
        )
        resolved = predictions.create(
            source_memory_id=resolved_memory.id,
            media_item_id=book.id,
            made_at_ordinal=2,
            resolution_window=10,
        )
        predictions.resolve(
            resolved,
            status=PredictionStatus.CONFIRMED,
            resolved_at=NOW,
            resolution_prompt_version_id="resolve-prediction-v1",
            evidence_memory_ids=[],
        )

        pending = predictions.list_pending_for_media_item(book.id)

        assert [p.id for p in pending] == [still_pending.id]


class TestResolve:
    def test_sets_status_resolved_at_and_prompt_version(
        self, session: Session, book: MediaItem
    ) -> None:
        memory = _make_memory(
            session,
            book,
            ordinal=1,
            content="prediction",
            memory_type=ExtractedMemoryType.PREDICTION,
        )
        predictions = PredictionRepository(session)
        prediction = predictions.create(
            source_memory_id=memory.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=10,
        )

        predictions.resolve(
            prediction,
            status=PredictionStatus.REFUTED,
            resolved_at=NOW,
            resolution_prompt_version_id="resolve-prediction-v1",
            evidence_memory_ids=[],
        )

        assert prediction.status is PredictionStatus.REFUTED
        assert prediction.resolved_at == NOW
        assert prediction.resolution_prompt_version_id == "resolve-prediction-v1"

    def test_links_evidence_memories(self, session: Session, book: MediaItem) -> None:
        source = _make_memory(
            session,
            book,
            ordinal=1,
            content="prediction",
            memory_type=ExtractedMemoryType.PREDICTION,
        )
        evidence = _make_memory(session, book, ordinal=5, content="it happened just like that")
        predictions = PredictionRepository(session)
        prediction = predictions.create(
            source_memory_id=source.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=10,
        )

        predictions.resolve(
            prediction,
            status=PredictionStatus.CONFIRMED,
            resolved_at=NOW,
            resolution_prompt_version_id="resolve-prediction-v1",
            evidence_memory_ids=[evidence.id],
        )

        assert predictions.list_evidence_memory_ids(prediction.id) == [evidence.id]

    def test_unresolvable_needs_no_prompt_version(self, session: Session, book: MediaItem) -> None:
        memory = _make_memory(
            session,
            book,
            ordinal=1,
            content="prediction",
            memory_type=ExtractedMemoryType.PREDICTION,
        )
        predictions = PredictionRepository(session)
        prediction = predictions.create(
            source_memory_id=memory.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=10,
        )

        predictions.resolve(
            prediction,
            status=PredictionStatus.UNRESOLVABLE,
            resolved_at=NOW,
            resolution_prompt_version_id=None,
            evidence_memory_ids=[],
        )

        assert prediction.status is PredictionStatus.UNRESOLVABLE
        assert prediction.resolution_prompt_version_id is None


class TestCascade:
    def test_deleting_the_source_memory_deletes_the_prediction(
        self, session: Session, book: MediaItem
    ) -> None:
        memory = _make_memory(
            session,
            book,
            ordinal=1,
            content="prediction",
            memory_type=ExtractedMemoryType.PREDICTION,
        )
        predictions = PredictionRepository(session)
        prediction = predictions.create(
            source_memory_id=memory.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=10,
        )
        prediction_id = prediction.id

        session.delete(memory)
        session.flush()
        session.expunge_all()

        assert predictions.get(prediction_id) is None

    def test_deleting_an_evidence_memory_removes_the_link_not_the_prediction(
        self, session: Session, book: MediaItem
    ) -> None:
        source = _make_memory(
            session,
            book,
            ordinal=1,
            content="prediction",
            memory_type=ExtractedMemoryType.PREDICTION,
        )
        evidence = _make_memory(session, book, ordinal=5, content="evidence")
        predictions = PredictionRepository(session)
        prediction = predictions.create(
            source_memory_id=source.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=10,
        )
        predictions.resolve(
            prediction,
            status=PredictionStatus.CONFIRMED,
            resolved_at=NOW,
            resolution_prompt_version_id="resolve-prediction-v1",
            evidence_memory_ids=[evidence.id],
        )

        session.delete(evidence)
        session.flush()

        assert predictions.list_evidence_memory_ids(prediction.id) == []
        assert predictions.get(prediction.id) is not None
