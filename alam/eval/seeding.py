"""Seeds one throwaway book + memories per case, for the retrieval and
spoiler harnesses. Not reused for extraction — that harness never touches the
database (transcript in, memories out)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.ai.providers import get_embedding_provider
from alam.persistence.repositories import (
    CaptureRepository,
    MediaItemRepository,
    MemoryEmbeddingRepository,
    MemoryRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from alam.eval.models import SeedMemory
    from alam.persistence.models import Memory

_EXTRACTION_PROMPT_VERSION_ID = "eval-seed-v1"
"""Not a real extraction — the harness writes canonical content directly. A
distinct id keeps seeded rows identifiable as such if anyone ever queries
``memories.prompt_version_id`` looking for real extraction output."""


def seed_case_memories(
    session: Session,
    memories: Sequence[SeedMemory],
    *,
    owner_id: uuid.UUID | None = None,
    current_ordinal: int | None = None,
) -> tuple[uuid.UUID, uuid.UUID, dict[str, Memory]]:
    """Creates a fresh book (and, unless ``owner_id`` is given, a fresh owner)
    so cases never share ordinal space, then one structure unit + capture +
    memory per ``SeedMemory``, embedded with whatever provider
    ``ALAM_EMBEDDING_PROVIDER`` currently resolves to — the same provider
    ``retrieve_memories`` will use to embed the query, so the two vectors are
    comparable.

    ``owner_id`` reuses an existing owner instead of creating a new one.
    Needed when a caller runs several cases through the real API in one
    session: ``UserRepository.get_owner()`` resolves the single owner account
    without taking an id (CLAUDE.md rule 9), so every case in that run must
    share one owner or every book after the first would 404 as belonging to
    someone else.

    ``current_ordinal``, if given, repositions the active session there after
    seeding — even to an ordinal with no ``SeedMemory`` of its own (a
    structure unit is created for it if needed) — so a caller that resolves
    the reader's position from the session (rather than being handed
    ``case.current_ordinal`` directly) sees the ordinal the case intends.

    Returns the book's id, the owner's id (needed to build a
    ``ReaderContext``), and a label -> persisted ``Memory`` map, so a case's
    ``relevant_labels`` / leakage check can be resolved back to real rows.
    """
    resolved_owner_id = owner_id or UserRepository(session).create(display_name="Eval").id
    book = MediaItemRepository(session).create(user_id=resolved_owner_id, title="Eval Book")

    provider = get_embedding_provider()
    embeddings = MemoryEmbeddingRepository(session)
    structure_units = StructureUnitRepository(session)
    reading_sessions = ReadingSessionRepository(session)

    units_by_ordinal: dict[int, uuid.UUID] = {}
    by_label: dict[str, Memory] = {}
    for seed in memories:
        if seed.structure_ordinal not in units_by_ordinal:
            unit = structure_units.create(
                media_item_id=book.id,
                ordinal=seed.structure_ordinal,
                label=f"Unit {seed.structure_ordinal}",
            )
            units_by_ordinal[seed.structure_ordinal] = unit.id
        unit_id = units_by_ordinal[seed.structure_ordinal]

        reading_session = reading_sessions.get_or_create_active(
            book.id,
            structure_unit_id=unit_id,
            ordinal=seed.structure_ordinal,
            progress=1.0,
        )
        capture = CaptureRepository(session).create(
            reading_session_id=reading_session.id,
            media_item_id=book.id,
            structure_unit_id=unit_id,
            structure_ordinal=seed.structure_ordinal,
            audio_data=b"x",
        )
        [memory] = MemoryRepository(session).create_many(
            capture_id=capture.id,
            media_item_id=book.id,
            structure_unit_id=unit_id,
            structure_ordinal=seed.structure_ordinal,
            prompt_version_id=_EXTRACTION_PROMPT_VERSION_ID,
            extracted=[
                ExtractedMemory(memory_type=ExtractedMemoryType.OTHER, content=seed.content)
            ],
        )
        [embedding] = provider.embed([seed.content])
        embeddings.create(
            memory_id=memory.id,
            embedding_model=embedding.model,
            embedding_version=embedding.version,
            content_hash=f"eval-{memory.id}",
            vector=embedding.vector,
        )
        by_label[seed.label] = memory

    if current_ordinal is not None:
        if current_ordinal not in units_by_ordinal:
            unit = structure_units.create(
                media_item_id=book.id, ordinal=current_ordinal, label=f"Unit {current_ordinal}"
            )
            units_by_ordinal[current_ordinal] = unit.id
        reading_sessions.get_or_create_active(
            book.id,
            structure_unit_id=units_by_ordinal[current_ordinal],
            ordinal=current_ordinal,
            progress=1.0,
        )

    return book.id, resolved_owner_id, by_label
