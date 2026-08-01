"""PreferenceFactRepository: creation, reinforcement, supersede chains, and
evidence linking (ADR-0001, M4 session 1)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.persistence.models.preference_fact_evidence import PreferenceFactEvidence
from alam.persistence.repositories import (
    CaptureRepository,
    MediaItemRepository,
    MemoryRepository,
    PreferenceFactRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)
from alam.persistence.repositories.preference_facts import AlreadySupersededError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import Memory, User

pytestmark = pytest.mark.db

NOW = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner")


def _make_memory(session: Session, owner: User, content: str) -> Memory:
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
    [memory] = MemoryRepository(session).create_many(
        capture_id=capture.id,
        media_item_id=book.id,
        structure_unit_id=chapter.id,
        structure_ordinal=1,
        prompt_version_id="extract-memories-v1",
        extracted=[ExtractedMemory(memory_type=ExtractedMemoryType.OPINION, content=content)],
    )
    return memory


class TestCreate:
    def test_creates_a_fact_with_its_evidence(self, session: Session, owner: User) -> None:
        memory = _make_memory(session, owner, "loved the unreliable narrator")
        facts = PreferenceFactRepository(session)

        fact = facts.create(
            user_id=owner.id,
            statement="prefers unreliable narrators",
            base_confidence=0.6,
            observed_at=NOW,
            evidence_memory_ids=[memory.id],
        )

        assert fact.observation_count == 1
        assert fact.superseded_at is None
        assert facts.list_evidence_memory_ids(fact.id) == [memory.id]

    def test_is_active_by_default(self, session: Session, owner: User) -> None:
        facts = PreferenceFactRepository(session)
        fact = facts.create(
            user_id=owner.id,
            statement="prefers slow openings",
            base_confidence=0.5,
            observed_at=NOW,
            evidence_memory_ids=[],
        )

        assert fact in facts.list_active_for_user(owner.id)


class TestReinforce:
    def test_increments_observation_count_and_confidence(
        self, session: Session, owner: User
    ) -> None:
        facts = PreferenceFactRepository(session)
        fact = facts.create(
            user_id=owner.id,
            statement="prefers unreliable narrators",
            base_confidence=0.5,
            observed_at=NOW,
            evidence_memory_ids=[],
        )

        facts.reinforce(fact, reinforced_at=NOW + dt.timedelta(days=7))

        assert fact.observation_count == 2
        assert fact.base_confidence > 0.5
        assert fact.last_reinforced_at == NOW + dt.timedelta(days=7)

    def test_links_additional_evidence(self, session: Session, owner: User) -> None:
        first = _make_memory(session, owner, "loved the unreliable narrator")
        second = _make_memory(session, owner, "another unreliable narrator moment")
        facts = PreferenceFactRepository(session)
        fact = facts.create(
            user_id=owner.id,
            statement="prefers unreliable narrators",
            base_confidence=0.5,
            observed_at=NOW,
            evidence_memory_ids=[first.id],
        )

        facts.reinforce(
            fact,
            reinforced_at=NOW + dt.timedelta(days=7),
            additional_evidence_memory_ids=[second.id],
        )

        assert set(facts.list_evidence_memory_ids(fact.id)) == {first.id, second.id}

    def test_does_not_write_a_new_row(self, session: Session, owner: User) -> None:
        facts = PreferenceFactRepository(session)
        fact = facts.create(
            user_id=owner.id,
            statement="prefers unreliable narrators",
            base_confidence=0.5,
            observed_at=NOW,
            evidence_memory_ids=[],
        )

        facts.reinforce(fact, reinforced_at=NOW + dt.timedelta(days=7))

        assert len(facts.list_active_for_user(owner.id)) == 1


class TestSupersede:
    def test_old_fact_is_marked_superseded_not_deleted(self, session: Session, owner: User) -> None:
        facts = PreferenceFactRepository(session)
        old = facts.create(
            user_id=owner.id,
            statement="dislikes slow openings",
            base_confidence=0.6,
            observed_at=NOW,
            evidence_memory_ids=[],
        )

        facts.supersede(
            old,
            statement="has come to appreciate slow openings",
            base_confidence=0.5,
            observed_at=NOW + dt.timedelta(days=200),
            evidence_memory_ids=[],
        )

        assert old.superseded_at == NOW + dt.timedelta(days=200)
        reloaded = facts.get(old.id)
        assert reloaded is not None  # retained, never deleted

    def test_new_fact_points_back_at_the_old_one(self, session: Session, owner: User) -> None:
        facts = PreferenceFactRepository(session)
        old = facts.create(
            user_id=owner.id,
            statement="dislikes slow openings",
            base_confidence=0.6,
            observed_at=NOW,
            evidence_memory_ids=[],
        )

        new = facts.supersede(
            old,
            statement="has come to appreciate slow openings",
            base_confidence=0.5,
            observed_at=NOW + dt.timedelta(days=200),
            evidence_memory_ids=[],
        )

        assert new.supersedes_id == old.id

    def test_only_the_new_fact_is_active(self, session: Session, owner: User) -> None:
        facts = PreferenceFactRepository(session)
        old = facts.create(
            user_id=owner.id,
            statement="dislikes slow openings",
            base_confidence=0.6,
            observed_at=NOW,
            evidence_memory_ids=[],
        )

        new = facts.supersede(
            old,
            statement="has come to appreciate slow openings",
            base_confidence=0.5,
            observed_at=NOW + dt.timedelta(days=200),
            evidence_memory_ids=[],
        )

        active = facts.list_active_for_user(owner.id)
        assert [f.id for f in active] == [new.id]

    def test_a_chain_of_supersedes_is_walkable(self, session: Session, owner: User) -> None:
        facts = PreferenceFactRepository(session)
        v1 = facts.create(
            user_id=owner.id,
            statement="bounces off slow openings",
            base_confidence=0.6,
            observed_at=NOW,
            evidence_memory_ids=[],
        )
        v2 = facts.supersede(
            v1,
            statement="neutral on slow openings",
            base_confidence=0.5,
            observed_at=NOW + dt.timedelta(days=100),
            evidence_memory_ids=[],
        )
        v3 = facts.supersede(
            v2,
            statement="seeks out slow openings",
            base_confidence=0.7,
            observed_at=NOW + dt.timedelta(days=300),
            evidence_memory_ids=[],
        )

        assert v3.supersedes_id == v2.id
        assert v2.supersedes_id == v1.id
        assert v1.supersedes_id is None

    def test_superseding_an_already_superseded_fact_raises(
        self, session: Session, owner: User
    ) -> None:
        """Otherwise the same fact could end up with two direct successors —
        a branch, not the linear chain the taste-drift view assumes."""
        facts = PreferenceFactRepository(session)
        old = facts.create(
            user_id=owner.id,
            statement="dislikes slow openings",
            base_confidence=0.6,
            observed_at=NOW,
            evidence_memory_ids=[],
        )
        facts.supersede(
            old,
            statement="neutral on slow openings",
            base_confidence=0.5,
            observed_at=NOW + dt.timedelta(days=100),
            evidence_memory_ids=[],
        )

        with pytest.raises(AlreadySupersededError):
            facts.supersede(
                old,
                statement="a second, conflicting successor",
                base_confidence=0.5,
                observed_at=NOW + dt.timedelta(days=200),
                evidence_memory_ids=[],
            )

    def test_list_all_for_user_includes_active_and_superseded(
        self, session: Session, owner: User
    ) -> None:
        facts = PreferenceFactRepository(session)
        old = facts.create(
            user_id=owner.id,
            statement="dislikes slow openings",
            base_confidence=0.6,
            observed_at=NOW,
            evidence_memory_ids=[],
        )
        new = facts.supersede(
            old,
            statement="neutral on slow openings",
            base_confidence=0.5,
            observed_at=NOW + dt.timedelta(days=100),
            evidence_memory_ids=[],
        )

        all_facts = facts.list_all_for_user(owner.id)

        assert {f.id for f in all_facts} == {old.id, new.id}


class TestEvidenceCascade:
    def test_deleting_a_memory_removes_its_evidence_link_not_the_fact(
        self, session: Session, owner: User
    ) -> None:
        memory = _make_memory(session, owner, "loved the unreliable narrator")
        facts = PreferenceFactRepository(session)
        fact = facts.create(
            user_id=owner.id,
            statement="prefers unreliable narrators",
            base_confidence=0.6,
            observed_at=NOW,
            evidence_memory_ids=[memory.id],
        )

        session.delete(memory)
        session.flush()

        assert facts.list_evidence_memory_ids(fact.id) == []
        assert facts.get(fact.id) is not None

    def test_deleting_a_user_cascades_to_their_facts(self, session: Session, owner: User) -> None:
        facts = PreferenceFactRepository(session)
        fact = facts.create(
            user_id=owner.id,
            statement="prefers unreliable narrators",
            base_confidence=0.6,
            observed_at=NOW,
            evidence_memory_ids=[],
        )
        fact_id = fact.id

        session.delete(owner)
        session.flush()
        session.expunge_all()  # forces the next get() past the identity map

        remaining = session.scalars(
            select(PreferenceFactEvidence).where(
                PreferenceFactEvidence.preference_fact_id == fact_id
            )
        ).all()
        assert remaining == []
        assert facts.get(fact_id) is None
