"""Applies a `domain.structure_review.StructurePlan` to persisted structure
units. Shared by EPUB ingestion (replaces the whole structure with a fresh
proposal) and structure verification (applies the human's corrections) —
both are the same operation against different `desired` lists.

Also the one place that resyncs the denormalized ordinal columns on
``reading_sessions``, ``captures``, and ``memories`` (CLAUDE.md rule 1,
ADR-0006) after a renumber. Excluding or merging away a unit that already has
one of those rows against it is not handled here — the FK on
``structure_unit_id`` has no ``ondelete`` cascade, so that fails loudly with
an ``IntegrityError`` instead, a known and documented M2 limitation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.persistence.repositories.captures import CaptureRepository
from alam.persistence.repositories.memories import MemoryRepository
from alam.persistence.repositories.reading_sessions import ReadingSessionRepository
from alam.persistence.repositories.structure_units import StructureUnitRepository

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from alam.domain.structure_review import StructurePlan, UnitToUpdate
    from alam.persistence.models import MediaStructureUnit


def apply_structure_plan(
    session: Session, *, media_item_id: uuid.UUID, plan: StructurePlan
) -> Sequence[MediaStructureUnit]:
    units = StructureUnitRepository(session)

    for unit_id in plan.to_delete:
        unit = units.get(unit_id)
        if unit is not None:
            units.delete(unit)
    session.flush()

    if plan.to_update:
        # Renumbering first (and only first) means every `to_create` ordinal
        # below is already free — `desired` assigns 1..N as a permutation
        # across both lists, so nothing here can collide. `renumber` sets the
        # unique constraint DEFERRED for the transaction regardless (ADR-0006),
        # which is what makes the reassignment itself safe.
        units.renumber(media_item_id, {u.id: u.ordinal for u in plan.to_update})
        for update in plan.to_update:
            unit = units.get(update.id)
            if unit is None:
                raise RuntimeError(f"structure unit {update.id} vanished mid-update")
            unit.label = update.label
            unit.first_lines = update.first_lines
        session.flush()

    for create in plan.to_create:
        units.create(
            media_item_id=media_item_id,
            ordinal=create.ordinal,
            label=create.label,
            first_lines=create.first_lines,
        )

    result = units.list_for_media_item(media_item_id)

    if plan.to_update:
        _resync_denormalized_ordinals(session, plan.to_update, total_units=len(result))

    return result


def _resync_denormalized_ordinals(
    session: Session, updates: Sequence[UnitToUpdate], *, total_units: int
) -> None:
    reading_sessions = ReadingSessionRepository(session)
    captures = CaptureRepository(session)
    memories = MemoryRepository(session)

    for update in updates:
        reading_sessions.resync_position(
            structure_unit_id=update.id, ordinal=update.ordinal, total_units=total_units
        )
        captures.resync_ordinal(structure_unit_id=update.id, ordinal=update.ordinal)
        memories.resync_ordinal(structure_unit_id=update.id, ordinal=update.ordinal)
