"""Job handlers for the M2 capture pipeline: transcribe, correct against the
book's entity list, then extract typed memories. Each stage is its own job so
a failure in one does not force the others to redo — retried independently,
same as any job in the queue (CLAUDE.md rule 5).

Handlers must not commit (see ``jobs/handlers.py``); the runner owns the
transaction and commits after a handler returns successfully.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from alam.ai.extraction.memories import ExtractionError, parse_extraction_response
from alam.ai.prompts.entity_correction import (
    PROMPT_VERSION_ID as CORRECTION_PROMPT_VERSION_ID,
)
from alam.ai.prompts.entity_correction import build_entity_correction_prompt
from alam.ai.prompts.extraction import (
    PROMPT_VERSION_ID as EXTRACTION_PROMPT_VERSION_ID,
)
from alam.ai.prompts.extraction import build_extraction_prompt
from alam.ai.providers import get_llm_provider, get_stt_provider
from alam.config.settings import get_settings
from alam.domain.entity_bias import book_entity_list
from alam.jobs.job_types import CORRECT_TRANSCRIPT, EXTRACT_MEMORIES
from alam.jobs.queue import JobQueue
from alam.persistence.models.memory import MemoryType
from alam.persistence.repositories.captures import CaptureRepository
from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.memories import MemoryRepository
from alam.persistence.repositories.predictions import PredictionRepository
from alam.persistence.repositories.structure_units import StructureUnitRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import Capture, MediaItem


class CapturePipelineError(LookupError):
    """A capture pipeline job's payload or precondition doesn't hold. Treated
    as an ordinary job failure — a capture deleted between enqueue and run, or
    a stage run out of order, should not take the drain down."""


def _load_capture(session: Session, payload: dict[str, Any]) -> Capture:
    capture_id = uuid.UUID(payload["capture_id"])
    capture = CaptureRepository(session).get(capture_id)
    if capture is None:
        raise CapturePipelineError(f"no capture {capture_id}")
    return capture


def _load_media_item(session: Session, capture: Capture) -> MediaItem:
    item = MediaItemRepository(session).get(capture.media_item_id)
    if item is None:
        raise CapturePipelineError(
            f"capture {capture.id} has no media item {capture.media_item_id}"
        )
    return item


def _entities_for(session: Session, item: MediaItem) -> list[str]:
    labels = [u.label for u in StructureUnitRepository(session).list_for_media_item(item.id)]
    return book_entity_list(
        title=item.title, author=item.attributes.get("author"), chapter_labels=labels
    )


def transcribe_capture(session: Session, payload: dict[str, Any]) -> None:
    capture = _load_capture(session, payload)
    item = _load_media_item(session, capture)
    entities = _entities_for(session, item)

    stt = get_stt_provider()
    transcript = stt.transcribe(capture.audio_data, entities=entities)

    CaptureRepository(session).mark_transcribed(
        capture, raw_transcript=transcript.text, transcript_model=transcript.model
    )

    JobQueue(session).enqueue(job_type=CORRECT_TRANSCRIPT, payload={"capture_id": str(capture.id)})


def correct_transcript(session: Session, payload: dict[str, Any]) -> None:
    capture = _load_capture(session, payload)
    if capture.raw_transcript is None:
        raise CapturePipelineError(f"capture {capture.id} has not been transcribed yet")

    item = _load_media_item(session, capture)
    entities = _entities_for(session, item)

    llm = get_llm_provider()
    prompt = build_entity_correction_prompt(transcript=capture.raw_transcript, entities=entities)
    completion = llm.complete(prompt, prompt_version_id=CORRECTION_PROMPT_VERSION_ID)

    CaptureRepository(session).mark_corrected(capture, corrected_transcript=completion.text)

    JobQueue(session).enqueue(job_type=EXTRACT_MEMORIES, payload={"capture_id": str(capture.id)})


def extract_memories(session: Session, payload: dict[str, Any]) -> None:
    capture = _load_capture(session, payload)
    if capture.corrected_transcript is None:
        raise CapturePipelineError(f"capture {capture.id} has not been corrected yet")

    llm = get_llm_provider()
    prompt = build_extraction_prompt(capture.corrected_transcript)
    completion = llm.complete(prompt, prompt_version_id=EXTRACTION_PROMPT_VERSION_ID)

    try:
        extracted = parse_extraction_response(completion.text)
    except ExtractionError as exc:
        raise CapturePipelineError(f"capture {capture.id}: {exc}") from exc

    memories = MemoryRepository(session).create_many(
        capture_id=capture.id,
        media_item_id=capture.media_item_id,
        structure_unit_id=capture.structure_unit_id,
        structure_ordinal=capture.structure_ordinal,
        prompt_version_id=EXTRACTION_PROMPT_VERSION_ID,
        extracted=extracted,
    )

    resolution_window = get_settings().prediction_resolution_window
    predictions = PredictionRepository(session)
    for memory in memories:
        if memory.memory_type == MemoryType.PREDICTION:
            predictions.create(
                source_memory_id=memory.id,
                media_item_id=memory.media_item_id,
                made_at_ordinal=memory.structure_ordinal,
                resolution_window=resolution_window,
            )

    CaptureRepository(session).mark_extracted(capture)
