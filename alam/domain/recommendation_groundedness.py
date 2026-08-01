"""Pure groundedness check for recommendation citations (M6 session 2,
ADR-0014).

No I/O (rule 3) — the DB existence/ownership lookup that produces
``valid_fact_ids``/``valid_memory_ids`` belongs to
``services/recommendations.py``; this module is only the matching logic
against sets already fetched. Deliberately narrow: ADR-0014's response
schema (``ai/synthesis/recommendations.py``) already removes any field an
LLM could write a characterization of a candidate book into, so the only
thing left to check is whether a cited id is real and belongs to the
reader — not whether a claim's *content* is trustworthy, which the schema
change made moot.
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
    """``"preference_fact"`` or ``"memory"``."""
    cites_id: str


def find_ungrounded_citations(
    citations: Sequence[CitationCheck],
    *,
    valid_fact_ids: frozenset[str],
    valid_memory_ids: frozenset[str],
) -> list[CitationCheck]:
    """Every citation whose id doesn't exist in the reader's own valid set
    for its cited type. A non-empty result blocks the whole recommendation
    set (``services/recommendations.py``) — the same all-or-nothing
    severity ``blocked_leaked`` uses today, not a partial response with
    some candidates silently dropped."""
    ungrounded = []
    for citation in citations:
        valid_ids = valid_fact_ids if citation.cites_type == "preference_fact" else valid_memory_ids
        if citation.cites_id not in valid_ids:
            ungrounded.append(citation)
    return ungrounded
