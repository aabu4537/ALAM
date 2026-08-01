"""Assembles taste-drift chains for one user (ADR-0001, M4 session 3): the
repository's flat fact list, grouped into lineages by
``domain/taste_drift.py``, with decay (``domain/preference_decay.py``)
applied to each chain's active head so the confidence shown is current, not
whatever it was the moment the fact was last written.

A superseded entry's confidence is left as its stored ``base_confidence`` —
frozen at retirement, not decayed further. Decay models a live belief fading
from neglect; a superseded fact isn't neglected, it's retired, and its
recorded confidence is a historical fact about what was believed at the time.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

from alam.domain.preference_decay import effective_confidence
from alam.domain.taste_drift import group_into_chains
from alam.persistence.repositories.preference_facts import PreferenceFactRepository

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from alam.persistence.models.preference_fact import PreferenceFact


@dataclass(frozen=True)
class TasteDriftEntry:
    fact: PreferenceFact
    confidence: float
    """Decayed, for the active entry; frozen at retirement, for a superseded
    one."""
    active: bool


def get_taste_drift(
    session: Session, *, user_id: uuid.UUID, now: dt.datetime | None = None
) -> list[list[TasteDriftEntry]]:
    """One list per independent preference lineage, each ordered oldest to
    newest. ``now`` is injectable for tests; production callers leave it
    unset."""
    resolved_now = now or dt.datetime.now(dt.UTC)
    facts = PreferenceFactRepository(session).list_all_for_user(user_id)

    chains = []
    for chain in group_into_chains(list(facts)):
        entries = []
        for fact in chain:
            active = fact.superseded_at is None
            confidence = (
                effective_confidence(
                    base_confidence=fact.base_confidence,
                    last_reinforced_at=fact.last_reinforced_at,
                    now=resolved_now,
                )
                if active
                else fact.base_confidence
            )
            entries.append(TasteDriftEntry(fact=fact, confidence=confidence, active=active))
        chains.append(entries)
    return chains
