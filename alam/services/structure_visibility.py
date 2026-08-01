"""Reading-time structure listing (ADR-0002 amendment): chapter id, ordinal,
and label up to the reader's current position — never ``first_lines``, the
book's own raw prose. That field is structurally absent from
``VisibleStructureUnit`` rather than present-but-filtered on a shared shape,
so there is no "forgot to strip it for this caller" failure mode; the
verification read (``services/structure_verification.py``'s callers) that
does need ``first_lines`` reads ``MediaStructureUnit`` directly instead of
going through this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from alam.domain.spoiler_filter import is_visible
from alam.persistence.repositories.structure_units import StructureUnitRepository

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from alam.domain.reader_context import ReaderContext


@dataclass(frozen=True)
class VisibleStructureUnit:
    id: uuid.UUID
    ordinal: int
    label: str


def list_visible_structure_units(
    session: Session, *, reader_context: ReaderContext
) -> list[VisibleStructureUnit]:
    units = StructureUnitRepository(session).list_for_media_item(reader_context.media_item_id)
    return [
        VisibleStructureUnit(id=u.id, ordinal=u.ordinal, label=u.label)
        for u in units
        if is_visible(structure_ordinal=u.ordinal, current_ordinal=reader_context.current_ordinal)
    ]
