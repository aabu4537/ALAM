from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from alam.domain.preference_decay import reinforce as compute_reinforcement
from alam.persistence.models.preference_fact import PreferenceFact
from alam.persistence.models.preference_fact_evidence import PreferenceFactEvidence

if TYPE_CHECKING:
    import datetime as dt
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session


class AlreadySupersededError(ValueError):
    """Raised by ``supersede`` when the fact it was handed is already
    retired. Without this guard, superseding the same fact twice would give
    it two direct successors — a branch, not the linear chain
    ``domain/taste_drift.py`` assumes and the taste-drift view renders."""


class PreferenceFactRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        user_id: uuid.UUID,
        statement: str,
        base_confidence: float,
        observed_at: dt.datetime,
        evidence_memory_ids: Sequence[uuid.UUID],
    ) -> PreferenceFact:
        fact = PreferenceFact(
            user_id=user_id,
            statement=statement,
            base_confidence=base_confidence,
            observation_count=1,
            last_reinforced_at=observed_at,
        )
        self._session.add(fact)
        self._session.flush()
        self._link_evidence(fact.id, evidence_memory_ids)
        return fact

    def get(self, fact_id: uuid.UUID) -> PreferenceFact | None:
        return self._session.get(PreferenceFact, fact_id)

    def list_active_for_user(self, user_id: uuid.UUID) -> Sequence[PreferenceFact]:
        """L3 loaded wholesale (ADR-0001) — every fact not yet superseded,
        oldest first. Callers apply ``domain.preference_decay`` themselves;
        this returns the stored ``base_confidence``, not a decayed value."""
        return self._session.scalars(
            select(PreferenceFact)
            .where(PreferenceFact.user_id == user_id, PreferenceFact.superseded_at.is_(None))
            .order_by(PreferenceFact.created_at)
        ).all()

    def list_all_for_user(self, user_id: uuid.UUID) -> Sequence[PreferenceFact]:
        """Active and superseded facts alike, oldest first — the raw
        material ``domain.taste_drift.group_into_chains`` groups into
        lineages for display. ``list_active_for_user`` is for callers that
        only care about the profile as it stands right now."""
        return self._session.scalars(
            select(PreferenceFact)
            .where(PreferenceFact.user_id == user_id)
            .order_by(PreferenceFact.created_at)
        ).all()

    def reinforce(
        self,
        fact: PreferenceFact,
        *,
        reinforced_at: dt.datetime,
        additional_evidence_memory_ids: Sequence[uuid.UUID] = (),
    ) -> PreferenceFact:
        """A new observation of an already-known preference: moves confidence
        toward 1 asymptotically and resets the decay clock (ADR-0001,
        ``domain.preference_decay.reinforce``). Does not write a new row —
        that is ``supersede``'s job, for when the new observation
        contradicts rather than confirms."""
        new_confidence, new_count = compute_reinforcement(
            base_confidence=fact.base_confidence, observation_count=fact.observation_count
        )
        fact.base_confidence = new_confidence
        fact.observation_count = new_count
        fact.last_reinforced_at = reinforced_at
        self._session.flush()
        if additional_evidence_memory_ids:
            self._link_evidence(fact.id, additional_evidence_memory_ids)
        return fact

    def supersede(
        self,
        old_fact: PreferenceFact,
        *,
        statement: str,
        base_confidence: float,
        observed_at: dt.datetime,
        evidence_memory_ids: Sequence[uuid.UUID],
    ) -> PreferenceFact:
        """A new observation contradicts ``old_fact``: writes a new row
        rather than overwriting it. ``old_fact`` is retained with
        ``superseded_at`` set, never deleted — this is what makes taste
        drift queryable (ADR-0001)."""
        if old_fact.superseded_at is not None:
            raise AlreadySupersededError(
                f"preference fact {old_fact.id} was already superseded at {old_fact.superseded_at}"
            )
        old_fact.superseded_at = observed_at
        new_fact = PreferenceFact(
            user_id=old_fact.user_id,
            statement=statement,
            base_confidence=base_confidence,
            observation_count=1,
            last_reinforced_at=observed_at,
            supersedes_id=old_fact.id,
        )
        self._session.add(new_fact)
        self._session.flush()
        self._link_evidence(new_fact.id, evidence_memory_ids)
        return new_fact

    def list_evidence_memory_ids(self, fact_id: uuid.UUID) -> Sequence[uuid.UUID]:
        return self._session.scalars(
            select(PreferenceFactEvidence.memory_id).where(
                PreferenceFactEvidence.preference_fact_id == fact_id
            )
        ).all()

    def _link_evidence(self, fact_id: uuid.UUID, memory_ids: Sequence[uuid.UUID]) -> None:
        for memory_id in memory_ids:
            self._session.add(
                PreferenceFactEvidence(preference_fact_id=fact_id, memory_id=memory_id)
            )
        self._session.flush()
