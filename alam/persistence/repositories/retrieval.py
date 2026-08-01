"""The two branches hybrid retrieval fuses (docs/milestones.md, M3).

Both queries filter with ``Memory.structure_ordinal <= current_ordinal`` —
ADR-0002 Layer 1, an index-only predicate backed by
``ix_memories_media_item_id_structure_ordinal``. This is the primary
enforcement; ``domain/spoiler_filter.py`` re-checks the merged result as a
second, independent layer rather than trusting every caller to remember this
clause.

Neither query is backed by an ANN or GIN index, matching ADR-0008's reasoning
for ``memory_embeddings``: a personal library tops out at a few thousand
memories, and an index that returns approximate or stale results is the wrong
trade for a corpus this small.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from alam.persistence.models.memory import Memory
from alam.persistence.models.memory_embedding import MemoryEmbedding

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session


class RetrievalRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def vector_search(
        self,
        *,
        media_item_id: uuid.UUID,
        embedding_model: str,
        embedding_version: str,
        query_vector: list[float],
        current_ordinal: int,
        limit: int,
    ) -> Sequence[Memory]:
        """Nearest neighbors by cosine distance, exact scan. Scoped to one
        model/version (rule 7) so a mid-migration mix of old- and
        new-dimension vectors never gets compared to each other."""
        stmt = (
            select(Memory)
            .join(MemoryEmbedding, MemoryEmbedding.memory_id == Memory.id)
            .where(
                Memory.media_item_id == media_item_id,
                Memory.structure_ordinal <= current_ordinal,
                MemoryEmbedding.embedding_model == embedding_model,
                MemoryEmbedding.embedding_version == embedding_version,
            )
            .order_by(MemoryEmbedding.vector.cosine_distance(query_vector))
            .limit(limit)
        )
        return self._session.scalars(stmt).all()

    def full_text_search(
        self,
        *,
        media_item_id: uuid.UUID,
        query: str,
        current_ordinal: int,
        limit: int,
    ) -> Sequence[Memory]:
        """Postgres full-text search over ``memories.content``.

        Catches what the vector branch structurally cannot: an invented
        proper noun a fake or real embedding model has never seen has no
        learned representation, but it is still just a token to full-text
        search.
        """
        tsvector = func.to_tsvector("english", Memory.content)
        tsquery = func.plainto_tsquery("english", query)
        stmt = (
            select(Memory)
            .where(
                Memory.media_item_id == media_item_id,
                Memory.structure_ordinal <= current_ordinal,
                tsvector.op("@@")(tsquery),
            )
            .order_by(func.ts_rank(tsvector, tsquery).desc())
            .limit(limit)
        )
        return self._session.scalars(stmt).all()
