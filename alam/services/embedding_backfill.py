"""Resumable, cursor-based embedding backfill (ADR-0008): one bounded batch
per job invocation, chained via re-enqueue with an advancing cursor.

Safe to be killed mid-run. The job runner commits a whole invocation's work
— every embedding it inserts plus the next job's enqueue — or none of it
(``jobs/handlers.py``); there is no partially-written batch to reconcile. A
killed invocation simply never advanced the cursor, so the next claim of
this job type re-derives the same batch from ``list_needing_embedding`` and
tries again.

Triggered on demand (``POST /internal/embeddings/backfill``), not chained
from extraction — this is a one-time catch-up over existing memories, not
the steady-state embedding of new ones. See ``jobs/job_types.py``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from alam.ai.providers import get_embedding_provider
from alam.config.settings import get_settings
from alam.domain.embedding_hash import embedding_content_hash
from alam.jobs.job_types import EMBED_MEMORIES_BACKFILL
from alam.jobs.queue import JobQueue
from alam.persistence.repositories.memories import MemoryRepository
from alam.persistence.repositories.memory_embeddings import MemoryEmbeddingRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def embed_memories_backfill(session: Session, payload: dict[str, Any]) -> None:
    settings = get_settings()
    after_id_raw = payload.get("after_id")
    after_id = uuid.UUID(after_id_raw) if after_id_raw else None

    provider = get_embedding_provider()
    memories = MemoryRepository(session)
    embeddings = MemoryEmbeddingRepository(session)

    batch = memories.list_needing_embedding(
        embedding_model=provider.model,
        embedding_version=provider.version,
        after_id=after_id,
        limit=settings.embedding_backfill_batch_size,
    )
    if not batch:
        return

    hashes = [
        embedding_content_hash(
            content=memory.content,
            embedding_model=provider.model,
            embedding_version=provider.version,
        )
        for memory in batch
    ]

    # A content_hash hit means identical text was already embedded — either
    # by an earlier run (a row already committed), or by another memory
    # earlier in *this same batch*. The latter is why resolution happens by
    # first-occurrence index rather than checking the database per item:
    # nothing in this batch is inserted (or visible to get_by_content_hash)
    # until the loop below, so two duplicates in one batch must be
    # deduplicated against each other before any of them exist as rows.
    first_index_for_hash: dict[str, int] = {}
    for i, content_hash in enumerate(hashes):
        first_index_for_hash.setdefault(content_hash, i)

    vectors: dict[int, list[float]] = {}
    needs_provider_call: list[int] = []
    for content_hash, i in first_index_for_hash.items():
        existing = embeddings.get_by_content_hash(content_hash)
        if existing is not None:
            vectors[i] = existing.vector
        else:
            needs_provider_call.append(i)

    if needs_provider_call:
        results = provider.embed([batch[i].content for i in needs_provider_call])
        for i, embedding in zip(needs_provider_call, results, strict=True):
            vectors[i] = embedding.vector

    for i, memory in enumerate(batch):
        canonical = first_index_for_hash[hashes[i]]
        embeddings.create(
            memory_id=memory.id,
            embedding_model=provider.model,
            embedding_version=provider.version,
            content_hash=hashes[i],
            vector=vectors[canonical],
        )

    if len(batch) == settings.embedding_backfill_batch_size:
        # A full batch means more may remain; a short one means this was the
        # last. Stopping here avoids one guaranteed-empty extra job per run.
        JobQueue(session).enqueue(
            job_type=EMBED_MEMORIES_BACKFILL, payload={"after_id": str(batch[-1].id)}
        )
