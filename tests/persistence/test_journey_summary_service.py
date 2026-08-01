"""get_or_generate_journey_summary: the persisted-artifact lifecycle (M6
session 1, ADR-0013) — pending row written before generation, ordinal-scoped
prompt content, staleness-gated regeneration, and the Layer 3 leak check
that blocks a draft rather than ever returning it.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.ai.providers.fakes import FakeLLM
from alam.domain.reader_context import ReaderContext
from alam.persistence.models.journey_summary import JourneySummaryStatus
from alam.persistence.repositories import (
    CaptureRepository,
    JourneySummaryRepository,
    MediaItemRepository,
    MemoryRepository,
    PredictionRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)
from alam.services.journey_summary import (
    JourneySummaryBlockedError,
    JourneySummaryGenerationError,
    UnknownMediaItemError,
    get_or_generate_journey_summary,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem, Memory, User

pytestmark = pytest.mark.db

_SUMMARY_OK = '{"narrative": "They loved the opening chapters."}'
_LEAK_CLEAN = '{"leaked": false, "spans": []}'


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


def _reader_context(book: MediaItem, *, current_ordinal: int) -> ReaderContext:
    return ReaderContext(
        media_item_id=book.id, user_id=book.user_id, current_ordinal=current_ordinal
    )


class TestGetOrGenerateJourneySummary:
    def test_generates_and_persists_a_complete_summary_on_first_read(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _memory_at(session, book, ordinal=1, content="I loved the opening")
        fake_llm = FakeLLM(responses=[_SUMMARY_OK, _LEAK_CLEAN])
        monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: fake_llm)

        summary = get_or_generate_journey_summary(
            session, reader_context=_reader_context(book, current_ordinal=1)
        )

        assert summary.status is JourneySummaryStatus.COMPLETE
        assert summary.draft == "They loved the opening chapters."
        assert summary.model == fake_llm.model
        assert summary.prompt_version_id == "journey-summary-v1"
        assert summary.generated_at_ordinal == 1
        assert len(fake_llm.calls) == 2

    def test_a_cached_complete_summary_is_reused_without_calling_the_llm_again(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _memory_at(session, book, ordinal=1, content="I loved the opening")
        fake_llm = FakeLLM(responses=[_SUMMARY_OK, _LEAK_CLEAN])
        monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: fake_llm)
        reader_context = _reader_context(book, current_ordinal=1)

        first = get_or_generate_journey_summary(session, reader_context=reader_context)
        second = get_or_generate_journey_summary(session, reader_context=reader_context)

        assert second.id == first.id
        assert len(fake_llm.calls) == 2  # no new calls on the second read

    def test_regenerates_once_progress_crosses_the_ordinal_threshold(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _memory_at(session, book, ordinal=1, content="I loved the opening")
        fake_llm = FakeLLM(responses=[_SUMMARY_OK, _LEAK_CLEAN, _SUMMARY_OK, _LEAK_CLEAN])
        monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: fake_llm)

        first = get_or_generate_journey_summary(
            session, reader_context=_reader_context(book, current_ordinal=1)
        )
        # ORDINAL_THRESHOLD is 5 — current_ordinal=6 is 5 past generated_at_ordinal=1.
        second = get_or_generate_journey_summary(
            session, reader_context=_reader_context(book, current_ordinal=6)
        )

        assert second.id != first.id
        assert second.generated_at_ordinal == 6
        assert len(fake_llm.calls) == 4

    def test_regenerates_once_the_prompt_version_changes(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _memory_at(session, book, ordinal=1, content="I loved the opening")
        fake_llm = FakeLLM(responses=[_SUMMARY_OK, _LEAK_CLEAN, _SUMMARY_OK, _LEAK_CLEAN])
        monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: fake_llm)
        reader_context = _reader_context(book, current_ordinal=1)

        first = get_or_generate_journey_summary(session, reader_context=reader_context)
        monkeypatch.setattr(
            "alam.services.journey_summary.JOURNEY_SUMMARY_PROMPT_VERSION_ID", "journey-summary-v2"
        )
        second = get_or_generate_journey_summary(session, reader_context=reader_context)

        assert second.id != first.id
        assert len(fake_llm.calls) == 4

    def test_excludes_memories_past_the_current_ordinal_from_the_summary_prompt(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _memory_at(session, book, ordinal=1, content="the sandworm was terrifying")
        spoiler = _memory_at(session, book, ordinal=9, content="Paul becomes the emperor")
        fake_llm = FakeLLM(responses=[_SUMMARY_OK, _LEAK_CLEAN])
        monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: fake_llm)

        summary = get_or_generate_journey_summary(
            session, reader_context=_reader_context(book, current_ordinal=1)
        )

        summary_prompt = fake_llm.calls[0].prompt
        leak_prompt = fake_llm.calls[1].prompt
        assert "the sandworm was terrifying" in summary_prompt
        assert "Paul becomes the emperor" not in summary_prompt
        # Layer 3 is checked *against* the excluded content, so it must see it.
        assert "Paul becomes the emperor" in leak_prompt
        assert summary.excluded_snapshot == [
            {
                "memory_id": str(spoiler.id),
                "structure_ordinal": 9,
                "content": "Paul becomes the emperor",
            }
        ]

    def test_a_leaked_draft_is_blocked_and_never_returned(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _memory_at(session, book, ordinal=1, content="I loved the opening")
        leaked = '{"leaked": true, "spans": ["Paul becomes emperor"]}'
        fake_llm = FakeLLM(responses=[_SUMMARY_OK, leaked])
        monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: fake_llm)

        with pytest.raises(JourneySummaryBlockedError):
            get_or_generate_journey_summary(
                session, reader_context=_reader_context(book, current_ordinal=1)
            )

        row = JourneySummaryRepository(session).get_latest_for_media_item(book.id)
        assert row is not None
        assert row.status is JourneySummaryStatus.BLOCKED_LEAKED
        assert row.layer3_leaked is True
        assert row.layer3_spans == ["Paul becomes emperor"]
        # The draft is retained for audit but this test never sees it served
        # by anything the caller-facing surface returns.
        assert row.draft == "They loved the opening chapters."

    def test_a_malformed_summary_response_marks_the_row_failed(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _memory_at(session, book, ordinal=1, content="I loved the opening")
        fake_llm = FakeLLM(responses=["not json"])
        monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: fake_llm)

        with pytest.raises(JourneySummaryGenerationError):
            get_or_generate_journey_summary(
                session, reader_context=_reader_context(book, current_ordinal=1)
            )

        row = JourneySummaryRepository(session).get_latest_for_media_item(book.id)
        assert row is not None
        assert row.status is JourneySummaryStatus.FAILED
        assert row.error is not None

    def test_the_pending_and_failed_writes_survive_a_later_rollback(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reproduces a bug the manual endpoint verification caught that no
        other test here could: ``session_scope`` (the real, production
        dependency, not the test `client` fixture's un-wrapped override)
        rolls back the whole request session on any exception that reaches
        it — including an ``HTTPException`` the router raises after
        translating this service's own error. Without an explicit
        ``session.commit()`` inside the service itself (see the module
        docstring), that outer rollback would silently take the
        ``pending``/``failed`` row down with it, defeating the entire
        point of persisting a retryable row. This simulates that outer
        rollback directly against the same session."""
        _memory_at(session, book, ordinal=1, content="I loved the opening")
        fake_llm = FakeLLM(responses=["not json"])
        monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: fake_llm)

        with pytest.raises(JourneySummaryGenerationError):
            get_or_generate_journey_summary(
                session, reader_context=_reader_context(book, current_ordinal=1)
            )

        session.rollback()  # what session_scope does once the HTTPException propagates

        row = JourneySummaryRepository(session).get_latest_for_media_item(book.id)
        assert row is not None
        assert row.status is JourneySummaryStatus.FAILED
        assert row.error is not None

    def test_a_malformed_leak_check_response_marks_the_row_failed(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _memory_at(session, book, ordinal=1, content="I loved the opening")
        fake_llm = FakeLLM(responses=[_SUMMARY_OK, "not json"])
        monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: fake_llm)

        with pytest.raises(JourneySummaryGenerationError):
            get_or_generate_journey_summary(
                session, reader_context=_reader_context(book, current_ordinal=1)
            )

        row = JourneySummaryRepository(session).get_latest_for_media_item(book.id)
        assert row is not None
        assert row.status is JourneySummaryStatus.FAILED

    def test_includes_predictions_in_the_summary_prompt(
        self, session: Session, book: MediaItem, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = _memory_at(session, book, ordinal=1, content="I bet Paul kills the Baron")
        PredictionRepository(session).create(
            source_memory_id=source.id,
            media_item_id=book.id,
            made_at_ordinal=1,
            resolution_window=10,
        )
        fake_llm = FakeLLM(responses=[_SUMMARY_OK, _LEAK_CLEAN])
        monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: fake_llm)

        get_or_generate_journey_summary(
            session, reader_context=_reader_context(book, current_ordinal=1)
        )

        assert "I bet Paul kills the Baron" in fake_llm.calls[0].prompt

    def test_an_unknown_media_item_raises(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_llm = FakeLLM()
        monkeypatch.setattr("alam.services.journey_summary.get_llm_provider", lambda: fake_llm)
        bogus_id = uuid.uuid4()

        with pytest.raises(UnknownMediaItemError):
            get_or_generate_journey_summary(
                session,
                reader_context=ReaderContext(
                    media_item_id=bogus_id, user_id=owner.id, current_ordinal=1
                ),
            )
