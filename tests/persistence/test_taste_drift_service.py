"""get_taste_drift: chains assembled from real persisted facts, with decay
applied to the active head of each (ADR-0001, M4 session 3)."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

import pytest

from alam.domain.preference_decay import HALF_LIFE_DAYS
from alam.persistence.repositories import PreferenceFactRepository, UserRepository
from alam.services.taste_drift import get_taste_drift

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import User

pytestmark = pytest.mark.db

NOW = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner")


class TestGetTasteDrift:
    def test_a_single_fact_is_one_chain_of_one(self, session: Session, owner: User) -> None:
        facts = PreferenceFactRepository(session)
        facts.create(
            user_id=owner.id,
            statement="prefers unreliable narrators",
            base_confidence=0.6,
            observed_at=NOW,
            evidence_memory_ids=[],
        )

        chains = get_taste_drift(session, user_id=owner.id, now=NOW)

        assert len(chains) == 1
        assert len(chains[0]) == 1
        assert chains[0][0].active is True

    def test_a_supersede_chain_orders_oldest_to_newest(self, session: Session, owner: User) -> None:
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

        [chain] = get_taste_drift(session, user_id=owner.id, now=NOW + dt.timedelta(days=200))

        assert [entry.fact.statement for entry in chain] == [
            "dislikes slow openings",
            "has come to appreciate slow openings",
        ]
        assert [entry.active for entry in chain] == [False, True]

    def test_the_active_entrys_confidence_is_decayed(self, session: Session, owner: User) -> None:
        facts = PreferenceFactRepository(session)
        fact = facts.create(
            user_id=owner.id,
            statement="prefers unreliable narrators",
            base_confidence=0.8,
            observed_at=NOW,
            evidence_memory_ids=[],
        )

        [chain] = get_taste_drift(
            session, user_id=owner.id, now=NOW + dt.timedelta(days=HALF_LIFE_DAYS)
        )

        assert chain[0].fact.id == fact.id
        assert chain[0].confidence == pytest.approx(0.4)

    def test_a_superseded_entrys_confidence_is_frozen_not_decayed(
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
        facts.supersede(
            old,
            statement="has come to appreciate slow openings",
            base_confidence=0.5,
            observed_at=NOW + dt.timedelta(days=10),
            evidence_memory_ids=[],
        )

        # Read long after retirement — the retired entry's confidence must
        # not have decayed in the meantime.
        [chain] = get_taste_drift(
            session, user_id=owner.id, now=NOW + dt.timedelta(days=10 + 5 * HALF_LIFE_DAYS)
        )

        assert chain[0].confidence == 0.6

    def test_independent_preferences_are_separate_chains(
        self, session: Session, owner: User
    ) -> None:
        facts = PreferenceFactRepository(session)
        facts.create(
            user_id=owner.id,
            statement="prefers unreliable narrators",
            base_confidence=0.6,
            observed_at=NOW,
            evidence_memory_ids=[],
        )
        facts.create(
            user_id=owner.id,
            statement="dislikes slow openings",
            base_confidence=0.6,
            observed_at=NOW,
            evidence_memory_ids=[],
        )

        chains = get_taste_drift(session, user_id=owner.id, now=NOW)

        assert len(chains) == 2

    def test_no_facts_is_an_empty_list(self, session: Session, owner: User) -> None:
        assert get_taste_drift(session, user_id=owner.id, now=NOW) == []
