"""ADR-0002 Layer 1: the deterministic ordinal containment rule.

The primary enforcement is an index-only SQL predicate in
``persistence/repositories/retrieval.py`` — that is what makes it cheap enough
to run on every query. This module is the source of truth for what that
predicate *means*, tested in milliseconds without a database, and callers that
assemble results from more than one query (e.g. hybrid retrieval's fusion
step) re-apply it here as a defense-in-depth check rather than trusting that
every branch remembered the SQL filter.
"""

from __future__ import annotations

from typing import Protocol


class HasStructureOrdinal(Protocol):
    structure_ordinal: int


def is_visible(*, structure_ordinal: int, current_ordinal: int) -> bool:
    """A unit at ``structure_ordinal`` is visible once the reader has reached
    it — equal counts as visible, since the reader is currently in it."""
    return structure_ordinal <= current_ordinal


def filter_visible[T: HasStructureOrdinal](items: list[T], *, current_ordinal: int) -> list[T]:
    """Order-preserving filter. Built for re-checking already-ranked results,
    where dropping an item must not disturb the relative order of the rest."""
    return [
        item
        for item in items
        if is_visible(structure_ordinal=item.structure_ordinal, current_ordinal=current_ordinal)
    ]
