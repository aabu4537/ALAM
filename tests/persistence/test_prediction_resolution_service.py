"""resolve_due_predictions: which pending predictions get checked, what
evidence they're checked against, and how the LLM's outcome maps onto a
terminal status (M5 session 2, ADR-0009)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.ai.prediction_resolution.outcome import ResolutionError
from alam.ai.providers.fakes import FakeLLM
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
from alam.services.capture_submission import submit_capture
from alam.services.prediction_resolution import resolve_due_predictions

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem, Memory, User

pytestmark = pytest.mark.db


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner")


@pytest.fixture
def book(session: Session, owner: User) -> MediaItem:
    return MediaItemRepository(session).create(user_id=owner.id, title="Dune")


def _chapters(session: Session, book: MediaItem, count: int) -> None:
    repo = StructureUnitRepository(session)
    for i in range(1, count + 1):
        repo.create(media_item_id=book.id, ordinal=i, label=f"Chapter {i}")


def _advance_reading_session(
    session: Session, owner: User, book: MediaItem, *, ordinal: int
) -> None:
    """Puts the book's active reading session at ``ordinal`` by submitting a
    capture there — the same path production traffic takes, and the one that
    enqueues ``RESOLVE_PREDICTIONS``."""
    submit_capture(
        session,
        user_id=owner.id,
        media_item_id=book.id,
        structure_unit_id=StructureUnitRepository(session)
        .list_for_media_item(book.id)[ordinal - 1]
        .id,
        audio=b"x",
    )


def _make_memory(session: Session, book: MediaItem, *, ordinal: int, content: str) -> Memory:
    reading_session = ReadingSessionRepository(session).get_active_for_media_item(book.id)
    assert reading_session is not None
    unit = next(
        u
        for u in StructureUnitRepository(session).list_for_media_item(book.id)
        if u.ordinal == ordinal
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
        extracted=[ExtractedMemory(memory_type=ExtractedMemoryType.OTHER, content=content)],
    )
    return memory


class TestResolveDuePredictions:
    def test_no_active_reading_session_is_a_noop(self, session: Session, book: MediaItem) -> None:
        resolve_due_predictions(session, {"media_item_id": str(book.id)})  # does not raise

    def test_a_prediction_whose_window_has_not_closed_stays_pending(
        self, session: Session, owner: User, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _chapters(session, book, 10)
        _advance_reading_session(session, owner, book, ordinal=1)
        source = _make_memory(session, book, ordinal=1, content="prediction")
        predictions = PredictionRepository(session)
        prediction = predictions.create(
            source_memory_id=source.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=10,
        )
        fake_llm = FakeLLM()
        monkeypatch.setattr(
            "alam.services.prediction_resolution.get_llm_provider", lambda: fake_llm
        )

        resolve_due_predictions(session, {"media_item_id": str(book.id)})

        assert prediction.status is PredictionStatus.PENDING
        assert fake_llm.calls == []

    def test_a_due_prediction_with_no_evidence_resolves_unresolvable_without_an_llm_call(
        self, session: Session, owner: User, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _chapters(session, book, 10)
        _advance_reading_session(session, owner, book, ordinal=1)
        source = _make_memory(session, book, ordinal=1, content="prediction")
        predictions = PredictionRepository(session)
        prediction = predictions.create(
            source_memory_id=source.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=2,
        )
        _advance_reading_session(session, owner, book, ordinal=5)
        fake_llm = FakeLLM()
        monkeypatch.setattr(
            "alam.services.prediction_resolution.get_llm_provider", lambda: fake_llm
        )

        resolve_due_predictions(session, {"media_item_id": str(book.id)})

        assert prediction.status is PredictionStatus.UNRESOLVABLE
        assert prediction.resolution_prompt_version_id is None
        assert fake_llm.calls == []

    def test_a_due_prediction_with_evidence_calls_the_llm_and_applies_the_outcome(
        self, session: Session, owner: User, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _chapters(session, book, 10)
        _advance_reading_session(session, owner, book, ordinal=1)
        source = _make_memory(session, book, ordinal=1, content="the traitor will be Yueh")
        predictions = PredictionRepository(session)
        prediction = predictions.create(
            source_memory_id=source.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=2,
        )
        evidence = _make_memory(session, book, ordinal=2, content="Yueh really did betray them")
        _advance_reading_session(session, owner, book, ordinal=5)
        fake_llm = FakeLLM(responses=['{"outcome": "confirmed"}'])
        monkeypatch.setattr(
            "alam.services.prediction_resolution.get_llm_provider", lambda: fake_llm
        )

        resolve_due_predictions(session, {"media_item_id": str(book.id)})

        assert prediction.status is PredictionStatus.CONFIRMED
        assert prediction.resolution_prompt_version_id == "resolve-prediction-v1"
        assert predictions.list_evidence_memory_ids(prediction.id) == [evidence.id]
        assert len(fake_llm.calls) == 1
        assert "the traitor will be Yueh" in fake_llm.calls[0].prompt
        assert "Yueh really did betray them" in fake_llm.calls[0].prompt

    def test_refuted_outcome_is_applied(
        self, session: Session, owner: User, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _chapters(session, book, 10)
        _advance_reading_session(session, owner, book, ordinal=1)
        source = _make_memory(session, book, ordinal=1, content="prediction")
        predictions = PredictionRepository(session)
        prediction = predictions.create(
            source_memory_id=source.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=2,
        )
        _make_memory(session, book, ordinal=2, content="it did not happen")
        _advance_reading_session(session, owner, book, ordinal=5)
        fake_llm = FakeLLM(responses=['{"outcome": "refuted"}'])
        monkeypatch.setattr(
            "alam.services.prediction_resolution.get_llm_provider", lambda: fake_llm
        )

        resolve_due_predictions(session, {"media_item_id": str(book.id)})

        assert prediction.status is PredictionStatus.REFUTED

    def test_llm_returned_unresolvable_still_records_the_prompt_version(
        self, session: Session, owner: User, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Distinguishes an LLM-adjudicated unresolvable (evidence existed
        but didn't settle it) from the no-evidence short-circuit, which
        never calls the LLM and leaves ``resolution_prompt_version_id``
        null."""
        _chapters(session, book, 10)
        _advance_reading_session(session, owner, book, ordinal=1)
        source = _make_memory(session, book, ordinal=1, content="prediction")
        predictions = PredictionRepository(session)
        prediction = predictions.create(
            source_memory_id=source.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=2,
        )
        _make_memory(session, book, ordinal=2, content="unrelated musing")
        _advance_reading_session(session, owner, book, ordinal=5)
        fake_llm = FakeLLM(responses=['{"outcome": "unresolvable"}'])
        monkeypatch.setattr(
            "alam.services.prediction_resolution.get_llm_provider", lambda: fake_llm
        )

        resolve_due_predictions(session, {"media_item_id": str(book.id)})

        assert prediction.status is PredictionStatus.UNRESOLVABLE
        assert prediction.resolution_prompt_version_id == "resolve-prediction-v1"

    def test_a_malformed_llm_response_fails_the_job(
        self, session: Session, owner: User, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _chapters(session, book, 10)
        _advance_reading_session(session, owner, book, ordinal=1)
        source = _make_memory(session, book, ordinal=1, content="prediction")
        PredictionRepository(session).create(
            source_memory_id=source.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=2,
        )
        _make_memory(session, book, ordinal=2, content="evidence")
        _advance_reading_session(session, owner, book, ordinal=5)
        fake_llm = FakeLLM(responses=["not json"])
        monkeypatch.setattr(
            "alam.services.prediction_resolution.get_llm_provider", lambda: fake_llm
        )

        with pytest.raises(ResolutionError):
            resolve_due_predictions(session, {"media_item_id": str(book.id)})

    def test_evidence_outside_the_window_is_not_scanned(
        self, session: Session, owner: User, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _chapters(session, book, 10)
        _advance_reading_session(session, owner, book, ordinal=1)
        source = _make_memory(session, book, ordinal=1, content="prediction")
        predictions = PredictionRepository(session)
        prediction = predictions.create(
            source_memory_id=source.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=2,
        )
        # Ordinal 4 is outside the (1, 3] window a resolution_window of 2 opens.
        _make_memory(session, book, ordinal=4, content="far-future evidence")
        _advance_reading_session(session, owner, book, ordinal=5)
        fake_llm = FakeLLM()
        monkeypatch.setattr(
            "alam.services.prediction_resolution.get_llm_provider", lambda: fake_llm
        )

        resolve_due_predictions(session, {"media_item_id": str(book.id)})

        # No in-window evidence, so the no-evidence short-circuit applies.
        assert prediction.status is PredictionStatus.UNRESOLVABLE
        assert fake_llm.calls == []
