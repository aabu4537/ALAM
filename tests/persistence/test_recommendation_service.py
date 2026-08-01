"""get_or_generate_recommendations: the persisted-artifact lifecycle (M6
session 2, ADR-0014; widened M6 session 3, ADR-0015) — pending row written
before generation, shelf/fact snapshot staleness, and the schema-driven
groundedness check that blocks a set rather than ever returning an
ungrounded citation.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.ai.providers.fakes import FakeLLM
from alam.persistence.models.recommendation import RecommendationStatus
from alam.persistence.repositories import (
    CaptureRepository,
    MediaItemRepository,
    MemoryRepository,
    PreferenceFactRepository,
    ReadingSessionRepository,
    RecommendationRepository,
    StructureUnitRepository,
    UserRepository,
)
from alam.services.recommendations import (
    RecommendationsBlockedError,
    RecommendationsGenerationError,
    get_or_generate_recommendations,
)

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem, Memory, PreferenceFact, User

pytestmark = pytest.mark.db


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner", is_demo=False)


def _to_read_book(session: Session, owner: User, *, title: str = "Case Book") -> MediaItem:
    return MediaItemRepository(session).create(
        user_id=owner.id,
        title=title,
        attributes={"exclusive_shelf": "to-read", "author": "Some Author"},
    )


def _to_read_book_with_catalog(
    session: Session,
    owner: User,
    *,
    title: str = "Case Book",
    blurb: str | None = "A desert planet and the boy who would rule it.",
    subjects: list[str] | None = None,
) -> MediaItem:
    return MediaItemRepository(session).create(
        user_id=owner.id,
        title=title,
        attributes={
            "exclusive_shelf": "to-read",
            "author": "Some Author",
            "catalog": {
                "blurb": blurb,
                "subjects": ["Science fiction"] if subjects is None else subjects,
                "series": None,
                "fetched_at": dt.datetime.now(dt.UTC).isoformat(),
            },
        },
    )


def _cites_catalog_response(*, media_item_id: uuid.UUID) -> str:
    return (
        '{"recommendations": [{"media_item_id": "'
        + str(media_item_id)
        + '", "cites": [{"type": "catalog", "id": "'
        + str(media_item_id)
        + '"}]}]}'
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


def _cites_fact_response(*, media_item_id: uuid.UUID, fact_id: uuid.UUID) -> str:
    return (
        '{"recommendations": [{"media_item_id": "'
        + str(media_item_id)
        + '", "cites": [{"type": "preference_fact", "id": "'
        + str(fact_id)
        + '"}]}]}'
    )


class TestGetOrGenerateRecommendations:
    def test_generates_and_persists_a_complete_set_on_first_read(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _to_read_book(session, owner, title="Dune")
        fact = _fact(session, owner)
        fake_llm = FakeLLM(responses=[_cites_fact_response(media_item_id=book.id, fact_id=fact.id)])
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        result = get_or_generate_recommendations(session, user_id=owner.id)

        assert result.status is RecommendationStatus.COMPLETE
        assert result.model == fake_llm.model
        assert result.prompt_version_id == "recommendations-v2"
        assert result.candidates == [
            {
                "media_item_id": str(book.id),
                "title": "Dune",
                "claims": [
                    {
                        "text": fact.statement,
                        "cites_type": "preference_fact",
                        "cites_id": str(fact.id),
                    }
                ],
            }
        ]
        assert len(fake_llm.calls) == 1

    def test_claim_text_is_composed_from_the_stored_memory_never_from_the_llm(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _to_read_book(session, owner)
        source_book = _to_read_book(session, owner, title="Already Read")
        memory = _memory(session, source_book, content="found-family arcs get me every time")
        response = (
            '{"recommendations": [{"media_item_id": "'
            + str(book.id)
            + '", "cites": [{"type": "memory", "id": "'
            + str(memory.id)
            + '"}]}]}'
        )
        fake_llm = FakeLLM(responses=[response])
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        result = get_or_generate_recommendations(session, user_id=owner.id)

        assert result.status is RecommendationStatus.COMPLETE
        assert result.candidates is not None
        assert result.candidates[0]["claims"][0]["text"] == "found-family arcs get me every time"

    def test_empty_shelf_short_circuits_to_complete_with_no_llm_call(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_llm = FakeLLM()
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        result = get_or_generate_recommendations(session, user_id=owner.id)

        assert result.status is RecommendationStatus.COMPLETE
        assert result.candidates == []
        assert result.model is None
        assert result.prompt_version_id is None
        assert len(fake_llm.calls) == 0

    def test_a_cached_complete_set_is_reused_without_calling_the_llm_again(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _to_read_book(session, owner)
        fact = _fact(session, owner)
        fake_llm = FakeLLM(responses=[_cites_fact_response(media_item_id=book.id, fact_id=fact.id)])
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        first = get_or_generate_recommendations(session, user_id=owner.id)
        second = get_or_generate_recommendations(session, user_id=owner.id)

        assert second.id == first.id
        assert len(fake_llm.calls) == 1  # no new call on the second read

    def test_regenerates_once_the_shelf_changes(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _to_read_book(session, owner)
        fact = _fact(session, owner)
        fake_llm = FakeLLM(
            responses=[
                _cites_fact_response(media_item_id=book.id, fact_id=fact.id),
                _cites_fact_response(media_item_id=book.id, fact_id=fact.id),
            ]
        )
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        first = get_or_generate_recommendations(session, user_id=owner.id)
        _to_read_book(session, owner, title="A New Candidate")
        second = get_or_generate_recommendations(session, user_id=owner.id)

        assert second.id != first.id
        assert len(fake_llm.calls) == 2

    def test_regenerates_once_the_active_fact_set_changes(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _to_read_book(session, owner)
        fact = _fact(session, owner)
        fake_llm = FakeLLM(
            responses=[
                _cites_fact_response(media_item_id=book.id, fact_id=fact.id),
                _cites_fact_response(media_item_id=book.id, fact_id=fact.id),
            ]
        )
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        first = get_or_generate_recommendations(session, user_id=owner.id)
        _fact(session, owner, statement="also loves slow-burn political intrigue")
        second = get_or_generate_recommendations(session, user_id=owner.id)

        assert second.id != first.id
        assert len(fake_llm.calls) == 2

    def test_regenerates_once_the_prompt_version_changes(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _to_read_book(session, owner)
        fact = _fact(session, owner)
        fake_llm = FakeLLM(
            responses=[
                _cites_fact_response(media_item_id=book.id, fact_id=fact.id),
                _cites_fact_response(media_item_id=book.id, fact_id=fact.id),
            ]
        )
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        first = get_or_generate_recommendations(session, user_id=owner.id)
        monkeypatch.setattr(
            "alam.services.recommendations.RECOMMENDATIONS_PROMPT_VERSION_ID",
            "recommendations-v3",
        )
        second = get_or_generate_recommendations(session, user_id=owner.id)

        assert second.id != first.id
        assert len(fake_llm.calls) == 2

    def test_an_ungrounded_citation_is_blocked_and_never_returned(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _to_read_book(session, owner)
        bogus_fact_id = "00000000-0000-0000-0000-000000000000"
        response = (
            '{"recommendations": [{"media_item_id": "'
            + str(book.id)
            + '", "cites": [{"type": "preference_fact", "id": "'
            + bogus_fact_id
            + '"}]}]}'
        )
        fake_llm = FakeLLM(responses=[response])
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        with pytest.raises(RecommendationsBlockedError):
            get_or_generate_recommendations(session, user_id=owner.id)

        row = RecommendationRepository(session).get_latest_for_user(owner.id)
        assert row is not None
        assert row.status is RecommendationStatus.BLOCKED_UNGROUNDED
        assert row.candidates is None
        assert row.ungrounded_citations == [
            {
                "media_item_id": str(book.id),
                "cites_type": "preference_fact",
                "cites_id": bogus_fact_id,
            }
        ]

    def test_a_hallucinated_media_item_id_is_dropped_not_surfaced(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _to_read_book(session, owner)  # a real candidate, never cited below
        fact = _fact(session, owner)
        bogus_media_item_id = "00000000-0000-0000-0000-000000000000"
        response = (
            '{"recommendations": [{"media_item_id": "'
            + bogus_media_item_id
            + '", "cites": [{"type": "preference_fact", "id": "'
            + str(fact.id)
            + '"}]}]}'
        )
        fake_llm = FakeLLM(responses=[response])
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        result = get_or_generate_recommendations(session, user_id=owner.id)

        assert result.status is RecommendationStatus.COMPLETE
        assert result.candidates == []

    def test_a_malformed_response_marks_the_row_failed(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _to_read_book(session, owner)
        fake_llm = FakeLLM(responses=["not json"])
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        with pytest.raises(RecommendationsGenerationError):
            get_or_generate_recommendations(session, user_id=owner.id)

        row = RecommendationRepository(session).get_latest_for_user(owner.id)
        assert row is not None
        assert row.status is RecommendationStatus.FAILED
        assert row.error is not None

    def test_the_pending_and_failed_writes_survive_a_later_rollback(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same regression M6 session 1's manual endpoint verification
        caught (``test_journey_summary_service.py``'s test of the same
        name): ``session_scope`` (the real, production dependency) rolls
        back the whole request session on any exception that reaches it,
        including an ``HTTPException`` the router raises after translating
        this service's own error. Without an explicit ``session.commit()``
        inside the service (see the module docstring), that outer rollback
        would silently take the ``pending``/``failed`` row down with it.
        Built in from the first draft this time rather than found after
        the fact — see the module's own docstring and ADR-0013/ADR-0014."""
        _to_read_book(session, owner)
        fake_llm = FakeLLM(responses=["not json"])
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        with pytest.raises(RecommendationsGenerationError):
            get_or_generate_recommendations(session, user_id=owner.id)

        session.rollback()  # what session_scope does once the HTTPException propagates

        row = RecommendationRepository(session).get_latest_for_user(owner.id)
        assert row is not None
        assert row.status is RecommendationStatus.FAILED
        assert row.error is not None

    def test_a_catalog_citation_resolves_to_the_stored_blurb(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _to_read_book_with_catalog(session, owner, title="Dune")
        fake_llm = FakeLLM(responses=[_cites_catalog_response(media_item_id=book.id)])
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        result = get_or_generate_recommendations(session, user_id=owner.id)

        assert result.status is RecommendationStatus.COMPLETE
        assert result.candidates == [
            {
                "media_item_id": str(book.id),
                "title": "Dune",
                "claims": [
                    {
                        "text": "A desert planet and the boy who would rule it.",
                        "cites_type": "catalog",
                        "cites_id": str(book.id),
                    }
                ],
            }
        ]

    def test_a_catalog_citation_falls_back_to_subjects_when_there_is_no_blurb(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _to_read_book_with_catalog(
            session, owner, blurb=None, subjects=["Science fiction", "Politics"]
        )
        fake_llm = FakeLLM(responses=[_cites_catalog_response(media_item_id=book.id)])
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        result = get_or_generate_recommendations(session, user_id=owner.id)

        assert result.status is RecommendationStatus.COMPLETE
        assert result.candidates is not None
        assert result.candidates[0]["claims"][0]["text"] == "Subjects: Science fiction, Politics."

    def test_a_catalog_citation_for_a_candidate_never_backfilled_is_ungrounded(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        book = _to_read_book(session, owner)  # no attributes["catalog"] at all
        fake_llm = FakeLLM(responses=[_cites_catalog_response(media_item_id=book.id)])
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        with pytest.raises(RecommendationsBlockedError):
            get_or_generate_recommendations(session, user_id=owner.id)

        row = RecommendationRepository(session).get_latest_for_user(owner.id)
        assert row is not None
        assert row.status is RecommendationStatus.BLOCKED_UNGROUNDED

    def test_a_catalog_citation_for_a_found_nothing_result_is_ungrounded(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A definite "checked, found nothing" catalog entry (blurb=None,
        subjects=[]) has nothing a catalog citation could reference —
        distinct from never having been backfilled, but still ungrounded."""
        book = _to_read_book_with_catalog(session, owner, blurb=None, subjects=[])
        fake_llm = FakeLLM(responses=[_cites_catalog_response(media_item_id=book.id)])
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        with pytest.raises(RecommendationsBlockedError):
            get_or_generate_recommendations(session, user_id=owner.id)

    def test_a_candidate_with_no_catalog_data_still_works_taste_only(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Session 2's behavior is unchanged for a candidate the backfill
        hasn't reached yet — taste-only citations still work exactly as
        they did before this session."""
        book = _to_read_book(session, owner)
        fact = _fact(session, owner)
        fake_llm = FakeLLM(responses=[_cites_fact_response(media_item_id=book.id, fact_id=fact.id)])
        monkeypatch.setattr("alam.services.recommendations.get_llm_provider", lambda: fake_llm)

        result = get_or_generate_recommendations(session, user_id=owner.id)

        assert result.status is RecommendationStatus.COMPLETE
        assert result.candidates is not None
        assert result.candidates[0]["claims"][0]["cites_type"] == "preference_fact"
