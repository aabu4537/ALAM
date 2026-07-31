"""Applies the human's corrected structure (ADR-0004 verification) and marks
the item verified. This is the only place that flips
``media_items.structure_verified_at`` off of null — nothing may index against
unverified structure, so that flip is deliberately not incidental to any
other write path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.domain.structure_review import ExistingUnit, plan_structure
from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.structure_units import StructureUnitRepository
from alam.services.epub_ingestion import UnknownMediaItemError
from alam.services.structure_plan import apply_structure_plan

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from alam.domain.structure_review import DesiredUnit
    from alam.persistence.models import MediaItem, MediaStructureUnit


def verify_structure(
    session: Session,
    *,
    media_item_id: uuid.UUID,
    user_id: uuid.UUID,
    desired: Sequence[DesiredUnit],
) -> tuple[MediaItem, list[MediaStructureUnit]]:
    items = MediaItemRepository(session)
    item = items.get(media_item_id)
    if item is None or item.user_id != user_id:
        raise UnknownMediaItemError(f"no media item {media_item_id} for this user")

    units_repo = StructureUnitRepository(session)
    existing = [ExistingUnit(id=u.id) for u in units_repo.list_for_media_item(item.id)]

    plan = plan_structure(existing, desired)
    result_units = apply_structure_plan(session, media_item_id=item.id, plan=plan)

    items.mark_structure_verified(item)

    return item, list(result_units)
