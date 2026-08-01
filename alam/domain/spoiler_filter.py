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

from alam.domain.prediction_resolution import is_due_for_resolution


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


def visible_prediction_status(
    *, status: str, made_at_ordinal: int, resolution_window: int, current_ordinal: int
) -> str:
    """The status safe to show a reader at ``current_ordinal`` — not
    necessarily the prediction's real, stored ``status`` (ADR-0012).

    A prediction's real status is itself a spoiler until the reader's own
    position reaches the ordinal its resolution window closes at
    (``made_at_ordinal + resolution_window`` — the same threshold
    ``prediction_resolution.is_due_for_resolution`` uses to decide when to
    actually run resolution). This matters most on a re-read: a prediction
    resolved during an earlier, further-along session stays real-status-only
    in the database — nothing re-runs resolution against the new session's
    lower ordinal — so without this check a re-reader would see "confirmed"
    or "refuted" the moment the prediction's *statement* becomes visible,
    long before their own re-read has reached the outcome. Below that
    ordinal this always reports ``"pending"``, the one status that carries
    no outcome information, regardless of what the stored status is; at or
    past it, the real status is safe to reveal.
    """
    if is_due_for_resolution(
        made_at_ordinal=made_at_ordinal,
        resolution_window=resolution_window,
        current_ordinal=current_ordinal,
    ):
        return status
    return "pending"
