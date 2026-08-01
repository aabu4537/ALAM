from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from alam.persistence.models.memory_embedding import MemoryEmbedding

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session


class MemoryEmbeddingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_content_hash(self, content_hash: str) -> MemoryEmbedding | None:
        """The idempotency check (ADR-0008): called before an embedding
        provider ever runs, so a re-run of an interrupted backfill costs a
        single indexed lookup per already-embedded memory, not a provider
        call."""
        return self._session.scalars(
            select(MemoryEmbedding).where(MemoryEmbedding.content_hash == content_hash)
        ).first()

    def create(
        self,
        *,
        memory_id: uuid.UUID,
        embedding_model: str,
        embedding_version: str,
        content_hash: str,
        vector: list[float],
    ) -> MemoryEmbedding:
        row = MemoryEmbedding(
            memory_id=memory_id,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
            content_hash=content_hash,
            vector=vector,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def list_for_memory(self, memory_id: uuid.UUID) -> Sequence[MemoryEmbedding]:
        return self._session.scalars(
            select(MemoryEmbedding).where(MemoryEmbedding.memory_id == memory_id)
        ).all()
