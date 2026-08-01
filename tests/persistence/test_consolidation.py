"""consolidate_preferences: applying LLM-decided actions to the profile,
resumable batching across a user's backlog and across users (ADR-0001, M4
session 2)."""

from __future__ import annotations

import datetime as dt
import json
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.ai.providers.fakes import FakeLLM
from alam.config.settings import get_settings
from alam.jobs.job_types import CONSOLIDATE_PREFERENCES
from alam.persistence.models.job import Job
from alam.persistence.repositories import (
    CaptureRepository,
    MediaItemRepository,
    MemoryRepository,
    PreferenceFactRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)
from alam.services.consolidation import ConsolidationActionError, consolidate_preferences

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import Memory, User

pytestmark = pytest.mark.db


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


class TestActions:
    def test_new_action_creates_a_fact_and_marks_memories_consolidated(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        [memory] = _make_memories(session, owner, ["loved the unreliable narrator"])
        response = json.dumps(
            [
                {
                    "action": "new",
                    "statement": "prefers unreliable narrators",
                    "memory_ids": [str(memory.id)],
                }
            ]
        )
        fake = FakeLLM(responses=[response])
        monkeypatch.setattr("alam.services.consolidation.get_llm_provider", lambda: fake)

        consolidate_preferences(session, {"user_id": str(owner.id)})

        facts = PreferenceFactRepository(session).list_active_for_user(owner.id)
        assert [f.statement for f in facts] == ["prefers unreliable narrators"]
        assert facts[0].observation_count == 1

        reloaded = MemoryRepository(session).get(memory.id)
        assert reloaded is not None
        assert reloaded.consolidated_at is not None

    def test_reinforce_action_updates_the_existing_fact_without_a_new_row(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        facts_repo = PreferenceFactRepository(session)

        existing = facts_repo.create(
            user_id=owner.id,
            statement="prefers unreliable narrators",
            base_confidence=0.5,
            observed_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            evidence_memory_ids=[],
        )
        [memory] = _make_memories(session, owner, ["another unreliable narrator moment"])
        response = json.dumps(
            [{"action": "reinforce", "fact_id": str(existing.id), "memory_ids": [str(memory.id)]}]
        )
        fake = FakeLLM(responses=[response])
        monkeypatch.setattr("alam.services.consolidation.get_llm_provider", lambda: fake)

        consolidate_preferences(session, {"user_id": str(owner.id)})

        active = facts_repo.list_active_for_user(owner.id)
        assert [f.id for f in active] == [existing.id]
        assert existing.observation_count == 2
        assert existing.base_confidence > 0.5
        assert memory.id in facts_repo.list_evidence_memory_ids(existing.id)

    def test_supersede_action_retires_the_old_fact_and_creates_a_new_one(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        facts_repo = PreferenceFactRepository(session)

        old = facts_repo.create(
            user_id=owner.id,
            statement="dislikes slow openings",
            base_confidence=0.6,
            observed_at=dt.datetime(2020, 1, 1, tzinfo=dt.UTC),
            evidence_memory_ids=[],
        )
        [memory] = _make_memories(session, owner, ["actually loved this slow opening"])
        response = json.dumps(
            [
                {
                    "action": "supersede",
                    "fact_id": str(old.id),
                    "statement": "has come to appreciate slow openings",
                    "memory_ids": [str(memory.id)],
                }
            ]
        )
        fake = FakeLLM(responses=[response])
        monkeypatch.setattr("alam.services.consolidation.get_llm_provider", lambda: fake)

        consolidate_preferences(session, {"user_id": str(owner.id)})

        assert old.superseded_at is not None
        active = facts_repo.list_active_for_user(owner.id)
        assert [f.statement for f in active] == ["has come to appreciate slow openings"]
        assert active[0].supersedes_id == old.id

    def test_a_hallucinated_fact_id_raises(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        [memory] = _make_memories(session, owner, ["some reflection"])
        response = json.dumps(
            [
                {
                    "action": "reinforce",
                    "fact_id": "019fbb00-0000-7000-8000-000000000000",
                    "memory_ids": [str(memory.id)],
                }
            ]
        )
        fake = FakeLLM(responses=[response])
        monkeypatch.setattr("alam.services.consolidation.get_llm_provider", lambda: fake)

        with pytest.raises(ConsolidationActionError):
            consolidate_preferences(session, {"user_id": str(owner.id)})

    def test_an_empty_action_list_still_marks_memories_consolidated(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not every memory reveals a preference; those must not resurface in
        every future run just because nothing was said about them."""
        [memory] = _make_memories(session, owner, ["I wonder what happens next"])
        fake = FakeLLM(responses=["[]"])
        monkeypatch.setattr("alam.services.consolidation.get_llm_provider", lambda: fake)

        consolidate_preferences(session, {"user_id": str(owner.id)})

        reloaded = MemoryRepository(session).get(memory.id)
        assert reloaded is not None
        assert reloaded.consolidated_at is not None
        assert PreferenceFactRepository(session).list_active_for_user(owner.id) == []


class TestChaining:
    def test_a_full_batch_chains_to_the_same_user(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ALAM_CONSOLIDATION_BATCH_SIZE", "1")
        get_settings.cache_clear()
        [first, _second] = _make_memories(session, owner, ["one", "two"])
        fake = FakeLLM(responses=["[]"])
        monkeypatch.setattr("alam.services.consolidation.get_llm_provider", lambda: fake)

        consolidate_preferences(session, {"user_id": str(owner.id)})

        jobs = session.scalars(select(Job).where(Job.job_type == CONSOLIDATE_PREFERENCES)).all()
        assert len(jobs) == 1
        assert jobs[0].payload == {"user_id": str(owner.id)}
        reloaded_first = MemoryRepository(session).get(first.id)
        assert reloaded_first is not None
        assert reloaded_first.consolidated_at is not None

    def test_a_short_batch_moves_to_the_next_user(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        other = UserRepository(session).create(display_name="Other")
        # Ensure a deterministic ordering regardless of which UUID sorts first.
        after_id = owner.id if owner.id < other.id else other.id
        second_user = other if after_id == owner.id else owner

        _make_memories(session, owner, ["one"])
        _make_memories(session, other, ["two"])
        fake = FakeLLM(responses=["[]"])
        monkeypatch.setattr("alam.services.consolidation.get_llm_provider", lambda: fake)

        consolidate_preferences(session, {"user_id": str(after_id)})

        jobs = session.scalars(select(Job).where(Job.job_type == CONSOLIDATE_PREFERENCES)).all()
        assert len(jobs) == 1
        assert jobs[0].payload == {"user_id": str(second_user.id)}

    def test_the_last_user_does_not_chain(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_memories(session, owner, ["one"])
        fake = FakeLLM(responses=["[]"])
        monkeypatch.setattr("alam.services.consolidation.get_llm_provider", lambda: fake)

        consolidate_preferences(session, {"user_id": str(owner.id)})

        jobs = session.scalars(select(Job).where(Job.job_type == CONSOLIDATE_PREFERENCES)).all()
        assert jobs == []

    def test_no_user_id_picks_the_oldest_backlog(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        [memory] = _make_memories(session, owner, ["one"])
        fake = FakeLLM(responses=["[]"])
        monkeypatch.setattr("alam.services.consolidation.get_llm_provider", lambda: fake)

        consolidate_preferences(session, {"user_id": None})

        reloaded = MemoryRepository(session).get(memory.id)
        assert reloaded is not None
        assert reloaded.consolidated_at is not None

    def test_nothing_needing_consolidation_is_a_no_op(
        self, session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeLLM()
        monkeypatch.setattr("alam.services.consolidation.get_llm_provider", lambda: fake)

        consolidate_preferences(session, {"user_id": None})  # must not raise

        assert fake.calls == []

    def test_a_second_call_does_not_reprocess_consolidated_memories(
        self, session: Session, owner: User, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _make_memories(session, owner, ["one"])
        fake = FakeLLM(responses=["[]", "[]"])
        monkeypatch.setattr("alam.services.consolidation.get_llm_provider", lambda: fake)

        consolidate_preferences(session, {"user_id": str(owner.id)})
        consolidate_preferences(session, {"user_id": str(owner.id)})

        assert len(fake.calls) == 1  # the second call found nothing left to weigh
