"""Orchestrates the start of the capture pipeline (ADR-0004): resolve or
resume the reader's active session at the selected chapter, and persist the
raw audio as a pending capture. Transcription, correction, and extraction are
separate job handlers (M2 sessions 2-3) — this module only gets a capture
onto the queue in the same transaction that records it, per rule 5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.domain.reading_progress import compute_progress
from alam.jobs.job_types import TRANSCRIBE_CAPTURE
from alam.jobs.queue import JobQueue
from alam.persistence.repositories.captures import CaptureRepository
from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.reading_sessions import ReadingSessionRepository
from alam.persistence.repositories.structure_units import StructureUnitRepository
from alam.services.epub_ingestion import UnknownMediaItemError

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from alam.persistence.models import Capture


class UnknownStructureUnitError(ValueError):
    """``structure_unit_id`` doesn't belong to this media item."""


def submit_capture(
    session: Session,
    *,
    user_id: uuid.UUID,
    media_item_id: uuid.UUID,
    structure_unit_id: uuid.UUID,
    audio: bytes,
) -> Capture:
    items = MediaItemRepository(session)
    item = items.get(media_item_id)
    if item is None or item.user_id != user_id:
        raise UnknownMediaItemError(f"no media item {media_item_id} for this user")

    units = StructureUnitRepository(session).list_for_media_item(media_item_id)
    unit = next((u for u in units if u.id == structure_unit_id), None)
    if unit is None:
        raise UnknownStructureUnitError(
            f"no structure unit {structure_unit_id} for media item {media_item_id}"
        )

    progress = compute_progress(unit.ordinal, len(units))
    reading_session = ReadingSessionRepository(session).get_or_create_active(
        media_item_id, structure_unit_id=unit.id, ordinal=unit.ordinal, progress=progress
    )

    capture = CaptureRepository(session).create(
        reading_session_id=reading_session.id,
        media_item_id=media_item_id,
        structure_unit_id=unit.id,
        structure_ordinal=unit.ordinal,
        audio_data=audio,
    )

    JobQueue(session).enqueue(job_type=TRANSCRIBE_CAPTURE, payload={"capture_id": str(capture.id)})

    return capture
