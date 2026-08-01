"""Pure groundedness check for recommendation citations (M6 session 2,
ADR-0014; widened M6 session 3, ADR-0015).

No I/O (rule 3) — the DB existence/ownership lookup that produces
``valid_fact_ids``/``valid_memory_ids``/``valid_catalog_media_item_ids``
belongs to ``services/recommendations.py``; this module is only the
matching logic against sets already fetched. Deliberately narrow:
ADR-0014's response schema (``ai/synthesis/recommendations.py``) already
removes any field an LLM could write a characterization of a candidate
book into, so the only thing left to check is whether a cited id is real
(and, for a ``"catalog"`` citation, that the candidate actually has a
fetched entry to cite) — not whether a claim's *content* is trustworthy,
which the schema change made moot for every citation type, not just the
two session 2 shipped with.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class CitationCheck:
    media_item_id: str
    cites_type: str
    """``"preference_fact"``, ``"memory"``, or ``"catalog"``."""
    cites_id: str
    """For ``"catalog"``, this is expected to equal ``media_item_id`` —
    checked against ``valid_catalog_media_item_ids`` regardless, so a
    mismatched id (were one ever produced) fails the same as any other
    ungrounded citation, not silently accepted."""


def find_ungrounded_citations(
    citations: Sequence[CitationCheck],
    *,
    valid_fact_ids: frozenset[str],
    valid_memory_ids: frozenset[str],
    valid_catalog_media_item_ids: frozenset[str] = frozenset(),
) -> list[CitationCheck]:
    """Every citation whose id doesn't exist in the reader's own valid set
    for its cited type. A non-empty result blocks the whole recommendation
    set (``services/recommendations.py``) — the same all-or-nothing
    severity ``blocked_leaked`` uses today, not a partial response with
    some candidates silently dropped.

    ``valid_catalog_media_item_ids`` defaults to empty so session 2's
    callers (and tests) that only ever cite facts/memories don't need to
    pass a third, always-empty set."""
    valid_ids_by_type = {
        "preference_fact": valid_fact_ids,
        "memory": valid_memory_ids,
        "catalog": valid_catalog_media_item_ids,
    }
    return [c for c in citations if c.cites_id not in valid_ids_by_type[c.cites_type]]
