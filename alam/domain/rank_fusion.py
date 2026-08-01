"""Reciprocal Rank Fusion — combines several ranked id lists into one.

docs/milestones.md, M3: "Pure vector search misses invented proper nouns."
Hybrid retrieval runs a cosine search and a full-text search separately and
needs a single ordering out of both; RRF is the standard way to do that
without trying to make the two branches' raw scores (a distance, a ts_rank)
commensurable. An id's fused score is the sum, across every list it appears
in, of ``1 / (k + rank)`` — so ranking well on either axis matters, and
ranking well on both compounds rather than averaging away.
"""

from __future__ import annotations

DEFAULT_K = 60
"""The constant from the original RRF paper. Larger k flattens the difference
between a rank-1 and a rank-10 hit; smaller k rewards a top rank more sharply.
Nothing about this project's retrieval needs a different value."""


def reciprocal_rank_fusion[Id](ranked_lists: list[list[Id]], *, k: int = DEFAULT_K) -> list[Id]:
    """Each inner list is one branch's results, best match first. Returns the
    fused ordering, best match first. An id absent from a list simply doesn't
    contribute a term for that list — it is not penalized beyond that."""
    scores: dict[Id, float] = {}
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)

    unique_ids = dict.fromkeys(item_id for ranked in ranked_lists for item_id in ranked)
    return sorted(unique_ids, key=lambda item_id: scores[item_id], reverse=True)
