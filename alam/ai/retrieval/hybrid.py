"""Hybrid retrieval (M3): pgvector cosine + Postgres full-text, fused with RRF.

docs/milestones.md, M3: "Pure vector search misses invented proper nouns."
This is the orchestration point — embed the query, run both repository
branches, fuse, and re-apply ADR-0002 Layer 1 as a defense-in-depth check
before anything leaves this function.

Scoped to ``memories`` only. ``content_chunks`` (chapter-text search) was
explicitly deferred in the M3 session that built ``memory_embeddings`` —
CLAUDE.md rule 2 requires chunks to respect structure-unit boundaries, and no
chunking pipeline exists yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.ai.providers import get_embedding_provider
from alam.config.settings import get_settings
from alam.domain.rank_fusion import reciprocal_rank_fusion
from alam.domain.spoiler_filter import filter_visible
from alam.persistence.repositories.retrieval import RetrievalRepository

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from alam.persistence.models.memory import Memory

DEFAULT_LIMIT = 10


def retrieve_memories(
    session: Session,
    *,
    media_item_id: uuid.UUID,
    query: str,
    current_ordinal: int,
    limit: int = DEFAULT_LIMIT,
) -> list[Memory]:
    """Spoiler-safe hybrid search over one book's memories.

    ``current_ordinal`` comes from the reader's ``ReadingSession`` — nothing
    at or past it is eligible, enforced twice: once as a SQL predicate in
    each repository branch (the cheap, primary layer) and again here after
    fusion (the defense-in-depth layer, ADR-0002).
    """
    settings = get_settings()
    provider = get_embedding_provider()
    repo = RetrievalRepository(session)

    [query_embedding] = provider.embed([query])

    vector_results = repo.vector_search(
        media_item_id=media_item_id,
        embedding_model=provider.model,
        embedding_version=provider.version,
        query_vector=query_embedding.vector,
        current_ordinal=current_ordinal,
        limit=settings.retrieval_candidate_limit,
    )
    text_results = repo.full_text_search(
        media_item_id=media_item_id,
        query=query,
        current_ordinal=current_ordinal,
        limit=settings.retrieval_candidate_limit,
    )

    by_id = {memory.id: memory for memory in (*vector_results, *text_results)}
    fused_ids = reciprocal_rank_fusion(
        [
            [memory.id for memory in vector_results],
            [memory.id for memory in text_results],
        ]
    )
    fused = [by_id[memory_id] for memory_id in fused_ids]

    visible = filter_visible(fused, current_ordinal=current_ordinal)
    return visible[:limit]
