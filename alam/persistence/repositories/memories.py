from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from alam.persistence.models.media_item import MediaItem
from alam.persistence.models.memory import Memory, MemoryType
from alam.persistence.models.memory_embedding import MemoryEmbedding

if TYPE_CHECKING:
    import datetime as dt
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from alam.ai.extraction.memories import ExtractedMemory


class MemoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_many(
        self,
        *,
        capture_id: uuid.UUID,
        media_item_id: uuid.UUID,
        structure_unit_id: uuid.UUID,
        structure_ordinal: int,
        prompt_version_id: str,
        extracted: Sequence[ExtractedMemory],
    ) -> list[Memory]:
        """One capture fans out to many memories (ADR-0001), all sharing the
        capture's position — that is what makes them one extraction call
        rather than N."""
        rows = [
            Memory(
                capture_id=capture_id,
                media_item_id=media_item_id,
                structure_unit_id=structure_unit_id,
                structure_ordinal=structure_ordinal,
                memory_type=MemoryType(item.memory_type.value),
                content=item.content,
                prompt_version_id=prompt_version_id,
            )
            for item in extracted
        ]
        self._session.add_all(rows)
        self._session.flush()
        return rows

    def get(self, memory_id: uuid.UUID) -> Memory | None:
        return self._session.get(Memory, memory_id)

    def list_for_capture(self, capture_id: uuid.UUID) -> Sequence[Memory]:
        return self._session.scalars(
            select(Memory).where(Memory.capture_id == capture_id).order_by(Memory.created_at)
        ).all()

    def list_for_media_item(self, media_item_id: uuid.UUID) -> Sequence[Memory]:
        return self._session.scalars(
            select(Memory)
            .where(Memory.media_item_id == media_item_id)
            .order_by(Memory.structure_ordinal, Memory.created_at)
        ).all()

    def list_in_ordinal_range(
        self, *, media_item_id: uuid.UUID, from_ordinal: int, to_ordinal: int
    ) -> Sequence[Memory]:
        """A prediction's evidence window (M5, ADR-0009): every memory for
        this book between two ordinals, inclusive on both ends. Bounded, not
        open-ended — ``domain.prediction_resolution.evidence_window``
        computes the range."""
        return self._session.scalars(
            select(Memory)
            .where(
                Memory.media_item_id == media_item_id,
                Memory.structure_ordinal >= from_ordinal,
                Memory.structure_ordinal <= to_ordinal,
            )
            .order_by(Memory.structure_ordinal, Memory.created_at)
        ).all()

    def resync_ordinal(self, *, structure_unit_id: uuid.UUID, ordinal: int) -> None:
        """Repairs the denormalized ordinal after structure re-verification
        renumbers the unit these memories were extracted at (CLAUDE.md rule 1,
        ADR-0006). Called from ``services/structure_plan.py``."""
        for memory in self._session.scalars(
            select(Memory).where(Memory.structure_unit_id == structure_unit_id)
        ):
            memory.structure_ordinal = ordinal
        self._session.flush()

    def list_needing_embedding(
        self,
        *,
        embedding_model: str,
        embedding_version: str,
        after_id: uuid.UUID | None,
        limit: int,
    ) -> Sequence[Memory]:
        """The backfill's batch query (ADR-0008): memories with no
        ``memory_embeddings`` row yet for this exact model/version, ordered
        by id — UUIDv7 is time-ordered, so ``id`` doubles as a stable,
        resumable cursor without a separate sequence column."""
        missing = ~(
            select(MemoryEmbedding.id)
            .where(
                MemoryEmbedding.memory_id == Memory.id,
                MemoryEmbedding.embedding_model == embedding_model,
                MemoryEmbedding.embedding_version == embedding_version,
            )
            .exists()
        )
        stmt = select(Memory).where(missing).order_by(Memory.id).limit(limit)
        if after_id is not None:
            stmt = stmt.where(Memory.id > after_id)
        return self._session.scalars(stmt).all()

    def list_needing_consolidation(self, *, user_id: uuid.UUID, limit: int) -> Sequence[Memory]:
        """M4's consolidation backlog: this user's memories with no
        consolidation pass recorded yet, oldest first (id is UUIDv7,
        time-ordered — the same cursor idiom ``list_needing_embedding``
        uses, though here the whole batch is reprocessed per call rather
        than paginated with an explicit cursor, since a batch is marked
        ``consolidated_at`` before the next one is fetched)."""
        return self._session.scalars(
            select(Memory)
            .join(MediaItem, MediaItem.id == Memory.media_item_id)
            .where(MediaItem.user_id == user_id, Memory.consolidated_at.is_(None))
            .order_by(Memory.id)
            .limit(limit)
        ).all()

    def next_user_id_needing_consolidation(
        self, *, after_user_id: uuid.UUID | None
    ) -> uuid.UUID | None:
        """Which user the consolidation job should move to next, once the
        current one's backlog is empty. Ordered by user id so a full sweep
        of all users terminates rather than cycling."""
        stmt = (
            select(MediaItem.user_id)
            .join(Memory, Memory.media_item_id == MediaItem.id)
            .where(Memory.consolidated_at.is_(None))
            .order_by(MediaItem.user_id)
            .limit(1)
        )
        if after_user_id is not None:
            stmt = stmt.where(MediaItem.user_id > after_user_id)
        return self._session.scalars(stmt).first()

    def mark_consolidated(
        self, memory_ids: Sequence[uuid.UUID], *, consolidated_at: dt.datetime
    ) -> None:
        for memory in self._session.scalars(select(Memory).where(Memory.id.in_(memory_ids))):
            memory.consolidated_at = consolidated_at
        self._session.flush()
