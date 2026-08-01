"""get_or_generate_briefing: the persisted-artifact lifecycle (M6 session
4) — pending row written before generation, fact/catalog-presence snapshot
staleness, and the schema-driven groundedness check (reused unchanged from
recommendations, ADR-0014) that blocks a briefing rather than ever
returning an ungrounded citation.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import TYPE_CHECKING

import pytest

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.ai.providers.fakes import FakeLLM
from alam.persistence.models.briefing import BriefingStatus
from alam.persistence.repositories import (
    BriefingRepository,
    CaptureRepository,
    MediaItemRepository,
    MemoryRepository,
    PreferenceFactRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)
from alam.services.briefing import (
    BriefingBlockedError,
    BriefingGenerationError,
    UnknownMediaItemError,
    get_or_generate_briefing,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem, Memory, PreferenceFact, User

pytestmark = pytest.mark.db


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner", is_demo=False)


def _unstarted_book(session: Session, owner: User, *, title: str = "Case Book") -> MediaItem:
    return MediaItemRepository(session).create(
        user_id=owner.id, title=title, attributes={"author": "Some Author"}
    )


def _unstarted_book_with_catalog(
    session: Session,
    owner: User,
    *,
    title: str = "Case Book",
    subjects: list[str] | None = None,
) -> MediaItem:
    return MediaItemRepository(session).create(
        user_id=owner.id,
        title=title,
        attributes={
            "author": "Some Author",
            "catalog": {
                "blurb": "A desert planet and the boy who would rule it.",
                "subjects": ["Science fiction"] if subjects is None else subjects,
                "series": None,
                "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
            },
        },
    )


def _fact(
    session: Session, owner: User, *, statement: str = "loves unreliable narrators"
) -> PreferenceFact:
    return PreferenceFactRepository(session).create(
        user_id=owner.id,
        statement=statement,
        base_confidence=0.8,
        observed_at=dt.datetime.now(dt.UTC),
        evidence_memory_ids=[],
    )


def _memory(session: Session, book: MediaItem, *, content: str) -> Memory:
    unit = StructureUnitRepository(session).create(media_item_id=book.id, ordinal=1, label="Ch 1")
    reading_session = ReadingSessionRepository(session).get_or_create_active(
        book.id, structure_unit_id=unit.id, ordinal=1, progress=1.0
    )
    capture = CaptureRepository(session).create(
        reading_session_id=reading_session.id,
        media_item_id=book.id,
        structure_unit_id=unit.id,
        structure_ordinal=1,
        audio_data=b"x",
    )
    [memory] = MemoryRepository(session).create_many(
        capture_id=capture.id,
        media_item_id=book.id,
        structure_unit_id=unit.id,
        structure_ordinal=1,
        prompt_version_id="extract-memories-v1",
        extracted=[ExtractedMemory(memory_type=ExtractedMemoryType.OPINION, content=content)],
    )
    return memory


def _cites_fact_response(*, fact_id: object) -> str:
    return '{"cites": [{"type": "preference_fact", "id": "' + str(fact_id) + '"}]}'


def _cites_memory_response(*, memory_id: object) -> str:
    return '{"cites": [{"type": "memory", "id": "' + str(memory_id) + '"}]}'


class TestGetOrGenerateBriefing:
    def test_generates_and_persists_a_complete_briefing_on_first_read(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _unstarted_book(session, owner)
        fact = _fact(session, owner)
        fake_llm = FakeLLM(responses=[_cites_fact_response(fact_id=fact.id)])
        monkeypatch.setattr("alam.services.briefing.get_llm_provider", lambda: fake_llm)

        result = get_or_generate_briefing(session, media_item_id=book.id)

        assert result.status is BriefingStatus.COMPLETE
        assert result.model == fake_llm.model
        assert result.prompt_version_id == "briefing-v1"
        assert result.claims == [
            {"text": fact.statement, "cites_type": "preference_fact", "cites_id": str(fact.id)}
        ]
        assert len(fake_llm.calls) == 1

    def test_claim_text_is_composed_from_the_stored_memory_never_from_the_llm(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _unstarted_book(session, owner)
        source_book = _unstarted_book(session, owner, title="Already Read")
        memory = _memory(session, source_book, content="found-family arcs get me every time")
        fake_llm = FakeLLM(responses=[_cites_memory_response(memory_id=memory.id)])
        monkeypatch.setattr("alam.services.briefing.get_llm_provider", lambda: fake_llm)

        result = get_or_generate_briefing(session, media_item_id=book.id)

        assert result.status is BriefingStatus.COMPLETE
        assert result.claims is not None
        assert result.claims[0]["text"] == "found-family arcs get me every time"

    def test_nothing_citable_short_circuits_to_complete_with_no_llm_call(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _unstarted_book(session, owner)
        fake_llm = FakeLLM()
        monkeypatch.setattr("alam.services.briefing.get_llm_provider", lambda: fake_llm)

        result = get_or_generate_briefing(session, media_item_id=book.id)

        assert result.status is BriefingStatus.COMPLETE
        assert result.claims == []
        assert result.model is None
        assert result.prompt_version_id is None
        assert len(fake_llm.calls) == 0

    def test_a_cached_complete_briefing_is_reused_without_calling_the_llm_again(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _unstarted_book(session, owner)
        fact = _fact(session, owner)
        fake_llm = FakeLLM(responses=[_cites_fact_response(fact_id=fact.id)])
        monkeypatch.setattr("alam.services.briefing.get_llm_provider", lambda: fake_llm)

        first = get_or_generate_briefing(session, media_item_id=book.id)
        second = get_or_generate_briefing(session, media_item_id=book.id)

        assert second.id == first.id
        assert len(fake_llm.calls) == 1  # no new call on the second read

    def test_regenerates_once_the_active_fact_set_changes(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _unstarted_book(session, owner)
        fact = _fact(session, owner)
        fake_llm = FakeLLM(
            responses=[
                _cites_fact_response(fact_id=fact.id),
                _cites_fact_response(fact_id=fact.id),
            ]
        )
        monkeypatch.setattr("alam.services.briefing.get_llm_provider", lambda: fake_llm)

        first = get_or_generate_briefing(session, media_item_id=book.id)
        _fact(session, owner, statement="also loves slow-burn political intrigue")
        second = get_or_generate_briefing(session, media_item_id=book.id)

        assert second.id != first.id
        assert len(fake_llm.calls) == 2

    def test_regenerates_once_catalog_data_arrives_after_generation(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The backfill (ADR-0015) can populate a candidate's catalog entry
        after a briefing was already generated without one."""
        book = _unstarted_book(session, owner)
        fact = _fact(session, owner)
        fake_llm = FakeLLM(
            responses=[
                _cites_fact_response(fact_id=fact.id),
                _cites_fact_response(fact_id=fact.id),
            ]
        )
        monkeypatch.setattr("alam.services.briefing.get_llm_provider", lambda: fake_llm)

        first = get_or_generate_briefing(session, media_item_id=book.id)
        book.attributes = {
            **book.attributes,
            "catalog": {
                "blurb": "A desert planet.",
                "subjects": ["Science fiction"],
                "series": None,
                "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
            },
        }
        session.flush()
        second = get_or_generate_briefing(session, media_item_id=book.id)

        assert second.id != first.id
        assert len(fake_llm.calls) == 2

    def test_regenerates_once_the_prompt_version_changes(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _unstarted_book(session, owner)
        fact = _fact(session, owner)
        fake_llm = FakeLLM(
            responses=[
                _cites_fact_response(fact_id=fact.id),
                _cites_fact_response(fact_id=fact.id),
            ]
        )
        monkeypatch.setattr("alam.services.briefing.get_llm_provider", lambda: fake_llm)

        first = get_or_generate_briefing(session, media_item_id=book.id)
        monkeypatch.setattr("alam.services.briefing.BRIEFING_PROMPT_VERSION_ID", "briefing-v2")
        second = get_or_generate_briefing(session, media_item_id=book.id)

        assert second.id != first.id
        assert len(fake_llm.calls) == 2

    def test_an_ungrounded_citation_is_blocked_and_never_returned(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _unstarted_book(session, owner)
        _fact(session, owner)  # a real fact, never cited below
        bogus_fact_id = "00000000-0000-0000-0000-000000000000"
        fake_llm = FakeLLM(responses=[_cites_fact_response(fact_id=bogus_fact_id)])
        monkeypatch.setattr("alam.services.briefing.get_llm_provider", lambda: fake_llm)

        with pytest.raises(BriefingBlockedError):
            get_or_generate_briefing(session, media_item_id=book.id)

        row = BriefingRepository(session).get_latest_for_media_item(book.id)
        assert row is not None
        assert row.status is BriefingStatus.BLOCKED_UNGROUNDED
        assert row.claims is None
        assert row.ungrounded_citations == [
            {"cites_type": "preference_fact", "cites_id": bogus_fact_id}
        ]

    def test_a_malformed_response_marks_the_row_failed(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _unstarted_book(session, owner)
        _fact(session, owner)
        fake_llm = FakeLLM(responses=["not json"])
        monkeypatch.setattr("alam.services.briefing.get_llm_provider", lambda: fake_llm)

        with pytest.raises(BriefingGenerationError):
            get_or_generate_briefing(session, media_item_id=book.id)

        row = BriefingRepository(session).get_latest_for_media_item(book.id)
        assert row is not None
        assert row.status is BriefingStatus.FAILED
        assert row.error is not None

    def test_the_pending_and_failed_writes_survive_a_later_rollback(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same regression M6 session 1's manual endpoint verification
        caught, re-applied here from the first draft — see the module
        docstring and ADR-0013/ADR-0014."""
        book = _unstarted_book(session, owner)
        _fact(session, owner)
        fake_llm = FakeLLM(responses=["not json"])
        monkeypatch.setattr("alam.services.briefing.get_llm_provider", lambda: fake_llm)

        with pytest.raises(BriefingGenerationError):
            get_or_generate_briefing(session, media_item_id=book.id)

        session.rollback()  # what session_scope does once the HTTPException propagates

        row = BriefingRepository(session).get_latest_for_media_item(book.id)
        assert row is not None
        assert row.status is BriefingStatus.FAILED
        assert row.error is not None

    def test_unknown_media_item_raises(self, session: Session) -> None:
        bogus_id = uuid.uuid4()
        with pytest.raises(UnknownMediaItemError):
            get_or_generate_briefing(session, media_item_id=bogus_id)

    def test_subjects_are_passed_to_the_prompt_when_present(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _unstarted_book_with_catalog(session, owner, subjects=["Politics"])
        fact = _fact(session, owner)
        fake_llm = FakeLLM(responses=[_cites_fact_response(fact_id=fact.id)])
        monkeypatch.setattr("alam.services.briefing.get_llm_provider", lambda: fake_llm)

        get_or_generate_briefing(session, media_item_id=book.id)

        assert "Politics" in fake_llm.calls[0].prompt
