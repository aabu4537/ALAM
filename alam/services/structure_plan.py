"""Applies a `domain.structure_review.StructurePlan` to persisted structure
units. Shared by EPUB ingestion (replaces the whole structure with a fresh
proposal) and structure verification (applies the human's corrections) —
both are the same operation against different `desired` lists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.persistence.repositories.structure_units import StructureUnitRepository

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from alam.domain.structure_review import StructurePlan
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

    return units.list_for_media_item(media_item_id)
