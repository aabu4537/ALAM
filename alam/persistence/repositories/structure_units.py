from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select, text

from alam.persistence.models.media_structure_unit import (
    MediaStructureUnit,
    StructureUnitType,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session


class StructureUnitRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        media_item_id: uuid.UUID,
        ordinal: int,
        label: str,
        unit_type: StructureUnitType = StructureUnitType.CHAPTER,
        first_lines: str | None = None,
    ) -> MediaStructureUnit:
        unit = MediaStructureUnit(
            media_item_id=media_item_id,
            ordinal=ordinal,
            label=label,
            unit_type=unit_type,
            first_lines=first_lines,
        )
        self._session.add(unit)
        self._session.flush()
        return unit

    def get(self, unit_id: uuid.UUID) -> MediaStructureUnit | None:
        return self._session.get(MediaStructureUnit, unit_id)

    def list_for_media_item(self, media_item_id: uuid.UUID) -> Sequence[MediaStructureUnit]:
        return self._session.scalars(
            select(MediaStructureUnit)
            .where(MediaStructureUnit.media_item_id == media_item_id)
            .order_by(MediaStructureUnit.ordinal)
        ).all()

    def get_by_ordinal(self, media_item_id: uuid.UUID, ordinal: int) -> MediaStructureUnit | None:
        return self._session.scalars(
            select(MediaStructureUnit).where(
                MediaStructureUnit.media_item_id == media_item_id,
                MediaStructureUnit.ordinal == ordinal,
            )
        ).first()

    def list_up_to_ordinal(
        self, media_item_id: uuid.UUID, current_ordinal: int
    ) -> Sequence[MediaStructureUnit]:
        """Units at or before the reader's current position.

        The shape the spoiler filter uses — ``ordinal <= :current``, served by
        the composite index, no join (ADR-0002 layer 1). Present here so the
        access pattern is exercised before ``memories`` exists to depend on it.
        """
        return self._session.scalars(
            select(MediaStructureUnit)
            .where(
                MediaStructureUnit.media_item_id == media_item_id,
                MediaStructureUnit.ordinal <= current_ordinal,
            )
            .order_by(MediaStructureUnit.ordinal)
        ).all()

    def renumber(
        self, media_item_id: uuid.UUID, new_ordinals: dict[uuid.UUID, int]
    ) -> Sequence[MediaStructureUnit]:
        """Reassign ordinals by unit id, keyed on the stable identifier.

        Defers the uniqueness check to commit so an intermediate state that
        transiently duplicates an ordinal — which any non-trivial reshuffle
        produces — does not abort the transaction. See ADR-0006.

        The caller's transaction must still commit for the constraint to be
        validated; a duplicate in ``new_ordinals`` surfaces as an
        ``IntegrityError`` at that point rather than here.
        """
        self._session.execute(
            text("SET CONSTRAINTS uq_media_structure_units_media_item_id_ordinal DEFERRED")
        )

        units = {u.id: u for u in self.list_for_media_item(media_item_id)}
        unknown = set(new_ordinals) - set(units)
        if unknown:
            raise ValueError(
                f"unit ids do not belong to media item {media_item_id}: {sorted(map(str, unknown))}"
            )

        for unit_id, ordinal in new_ordinals.items():
            units[unit_id].ordinal = ordinal

        self._session.flush()
        return self.list_for_media_item(media_item_id)

    def delete(self, unit: MediaStructureUnit) -> None:
        self._session.delete(unit)
