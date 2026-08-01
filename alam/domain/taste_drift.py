"""Grouping preference facts into supersede chains (ADR-0001, M4 session 3).

Pure — no I/O, no ORM. Reasons about plain fact rows via the
``HasSupersedeLink`` Protocol only, the same structural-typing pattern
``domain/spoiler_filter.py`` uses for ``HasStructureOrdinal`` — a repository
hands over ORM rows, and this module never needs to know they're ORM rows to
group them.

Chains exist because ADR-0001 never overwrites a fact: a contradiction writes
a new row with ``supersedes_id`` pointing at the old one. Taste drift is that
lineage read back in order — "through 2024 you bounced off slow openings;
since March you've come to appreciate them."
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import uuid


class HasSupersedeLink(Protocol):
    id: uuid.UUID
    supersedes_id: uuid.UUID | None


def group_into_chains[T: HasSupersedeLink](facts: list[T]) -> list[list[T]]:
    """One chain per root fact (``supersedes_id is None``), each ordered
    oldest to newest. ``facts`` should be one user's facts, sorted with the
    oldest first — the order roots appear in the output follows their order
    in ``facts``, so callers control chain ordering by how they sort the
    input.

    Assumes at most one direct successor per fact — true as long as
    ``PreferenceFactRepository.supersede`` is the only way a fact gets
    superseded, since it refuses a fact that is already retired. A fact with
    two would-be successors isn't a data shape this function tries to
    represent; the second is silently dropped from its parent's chain rather
    than raised, since grouping for display is not the place to enforce a
    write-time invariant.
    """
    by_id = {fact.id: fact for fact in facts}
    successor_of: dict[uuid.UUID, T] = {}
    for fact in facts:
        if fact.supersedes_id is not None and fact.supersedes_id in by_id:
            successor_of.setdefault(fact.supersedes_id, fact)

    chains: list[list[T]] = []
    for fact in facts:
        is_root = fact.supersedes_id is None or fact.supersedes_id not in by_id
        if not is_root:
            continue  # reached as part of its root's chain below
        chain = [fact]
        current = fact
        while current.id in successor_of:
            current = successor_of[current.id]
            chain.append(current)
        chains.append(chain)

    return chains
