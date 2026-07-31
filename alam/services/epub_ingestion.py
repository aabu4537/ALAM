"""Orchestrates EPUB ingestion: parse, then persist the proposal as an
unverified structure hypothesis (ADR-0004). `media.books.epub` does the
parsing (no I/O beyond the given bytes); this is the only place that talks
to the database for it, per CLAUDE.md's dependency direction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.domain.structure_review import DesiredUnit, ExistingUnit, plan_structure
from alam.media.books.epub import parse_epub
from alam.persistence.models.media_item import MediaType
from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.structure_units import StructureUnitRepository
from alam.services.structure_plan import apply_structure_plan

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from alam.media.books.epub import ParsedEpub
    from alam.persistence.models import MediaItem, MediaStructureUnit


class UnknownMediaItemError(ValueError):
    """``media_item_id`` was given but doesn't resolve to this user's book."""


def preview_epub(data: bytes) -> ParsedEpub:
    """Parses without touching the database at all."""
    return parse_epub(data)


def commit_epub(
    session: Session, *, user_id: uuid.UUID, media_item_id: uuid.UUID | None, data: bytes
) -> tuple[MediaItem, list[MediaStructureUnit]]:
    """Parses and replaces the target item's structure with the fresh proposal.

    A book that was previously verified is not left marked verified against
    structure it no longer reflects — committing a new EPUB always resets
    ``structure_verified_at`` to null, requiring re-confirmation.
    """
    parsed = parse_epub(data)
    items = MediaItemRepository(session)

    if media_item_id is not None:
        item = items.get(media_item_id)
        if item is None or item.user_id != user_id:
            raise UnknownMediaItemError(f"no media item {media_item_id} for this user")
    else:
        item = items.create(
            user_id=user_id,
            title=parsed.metadata.title or "Untitled",
            media_type=MediaType.BOOK,
            attributes={"author": parsed.metadata.author},
        )

    units_repo = StructureUnitRepository(session)
    existing = [ExistingUnit(id=u.id) for u in units_repo.list_for_media_item(item.id)]
    desired = [DesiredUnit(label=u.label, first_lines=u.first_lines) for u in parsed.units]

    plan = plan_structure(existing, desired)
    result_units = apply_structure_plan(session, media_item_id=item.id, plan=plan)

    item.structure_verified_at = None
    session.flush()

    return item, list(result_units)
