"""list_predictions_for_book: joins predictions back to their source and
evidence memories' text for display (M5 session 3), ordinal-scoped by
ReaderContext rather than by which reading session made or resolved a
prediction (ADR-0012)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.domain.reader_context import ReaderContext
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
from alam.services.predictions import list_predictions_for_book

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


def _make_memory(session: Session, book: MediaItem, *, ordinal: int, content: str) -> Memory:
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
        extracted=[ExtractedMemory(memory_type=ExtractedMemoryType.OTHER, content=content)],
    )
    return memory


def _reader_context(book: MediaItem, *, current_ordinal: int) -> ReaderContext:
    return ReaderContext(
        media_item_id=book.id, user_id=book.user_id, current_ordinal=current_ordinal
    )


class TestListPredictionsForBook:
    def test_no_predictions_is_an_empty_list(self, session: Session, book: MediaItem) -> None:
        reader_context = _reader_context(book, current_ordinal=10)

        assert list_predictions_for_book(session, reader_context=reader_context) == []

    def test_a_pending_prediction_has_no_evidence_yet(
        self, session: Session, book: MediaItem
    ) -> None:
        source = _make_memory(session, book, ordinal=1, content="the traitor will be Yueh")
        PredictionRepository(session).create(
            source_memory_id=source.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=10,
        )
        reader_context = _reader_context(book, current_ordinal=5)

        [view] = list_predictions_for_book(session, reader_context=reader_context)

        assert view.statement == "the traitor will be Yueh"
        assert view.status is PredictionStatus.PENDING
        assert view.resolved_at is None
        assert view.evidence == []

    def test_a_resolved_predictions_evidence_is_included_once_the_window_closes(
        self, session: Session, book: MediaItem
    ) -> None:
        source = _make_memory(session, book, ordinal=1, content="the traitor will be Yueh")
        evidence_memory = _make_memory(
            session, book, ordinal=2, content="Yueh really did betray them"
        )
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
            evidence_memory_ids=[evidence_memory.id],
        )
        reader_context = _reader_context(book, current_ordinal=11)  # made_at (1) + window (10)

        [view] = list_predictions_for_book(session, reader_context=reader_context)

        assert view.status is PredictionStatus.CONFIRMED
        assert view.resolved_at == NOW
        assert view.evidence == ["Yueh really did betray them"]

    def test_a_resolved_prediction_stays_pending_before_the_window_closes(
        self, session: Session, book: MediaItem
    ) -> None:
        """The re-read hazard (ADR-0012): resolved during an earlier,
        further-along session, but this reader's own position hasn't
        reached the window's close yet — the real outcome must not leak."""
        source = _make_memory(session, book, ordinal=1, content="the traitor will be Yueh")
        evidence_memory = _make_memory(
            session, book, ordinal=2, content="Yueh really did betray them"
        )
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
            evidence_memory_ids=[evidence_memory.id],
        )
        reader_context = _reader_context(book, current_ordinal=3)  # short of made_at (1) + 10

        [view] = list_predictions_for_book(session, reader_context=reader_context)

        assert view.statement == "the traitor will be Yueh"  # made_at (1) is visible
        assert view.status is PredictionStatus.PENDING
        assert view.resolved_at is None
        assert view.evidence == []

    def test_a_prediction_made_past_the_current_ordinal_is_omitted_entirely(
        self, session: Session, book: MediaItem
    ) -> None:
        source = _make_memory(session, book, ordinal=8, content="the emperor will abdicate")
        PredictionRepository(session).create(
            source_memory_id=source.id,
            media_item_id=book.id,
            made_at_ordinal=8,
            resolution_window=2,
        )
        reader_context = _reader_context(book, current_ordinal=3)

        assert list_predictions_for_book(session, reader_context=reader_context) == []

    def test_ordered_oldest_prediction_first(self, session: Session, book: MediaItem) -> None:
        first_source = _make_memory(session, book, ordinal=1, content="first prediction")
        second_source = _make_memory(session, book, ordinal=3, content="second prediction")
        predictions = PredictionRepository(session)
        predictions.create(
            source_memory_id=second_source.id,
            media_item_id=book.id,
            made_at_ordinal=3,
            resolution_window=10,
        )
        predictions.create(
            source_memory_id=first_source.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=10,
        )
        reader_context = _reader_context(book, current_ordinal=5)

        views = list_predictions_for_book(session, reader_context=reader_context)

        assert [v.statement for v in views] == ["first prediction", "second prediction"]

    def test_only_this_books_predictions_are_listed(
        self, session: Session, owner: User, book: MediaItem
    ) -> None:
        other_book = MediaItemRepository(session).create(user_id=owner.id, title="Another")
        this_source = _make_memory(session, book, ordinal=1, content="this book's prediction")
        other_source = _make_memory(
            session, other_book, ordinal=1, content="the other book's prediction"
        )
        predictions = PredictionRepository(session)
        predictions.create(
            source_memory_id=this_source.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=10,
        )
        predictions.create(
            source_memory_id=other_source.id,
            media_item_id=other_book.id,
            made_at_ordinal=1,
            resolution_window=10,
        )
        reader_context = _reader_context(book, current_ordinal=5)

        views = list_predictions_for_book(session, reader_context=reader_context)

        assert [v.statement for v in views] == ["this book's prediction"]
