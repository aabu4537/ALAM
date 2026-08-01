"""Capture submission, reading-session lifecycle (ADR-0004, M2 session 1), and
memory search (M3 retrieval's first production caller).

Submitting a capture is what advances (or starts) the book's active reading
session — there is no separate "select chapter" step, matching the ADR's
"progress is captured as part of the recording act." The audio body is raw
bytes, not multipart, same tradeoff as the Goodreads/EPUB routers.

Transcription and extraction happen out of band via the job queue enqueued
here; a capture's ``status`` starts and stays ``pending`` until M2 session 2's
handler is registered.

``GET .../memories`` never takes an ordinal from the request — it resolves
one server-side via ``services.reading_sessions.get_reader_context``, so a
client cannot ask to see past its own reading position.
"""

from __future__ import annotations

import datetime as dt

# `uuid` stays a real import, not TYPE_CHECKING-only, despite ruff's TC003.
# FastAPI/Pydantic resolves path- and query-param annotations via TypeAdapter
# even under `from __future__ import annotations`, unlike a Depends()-only
# parameter (see books.py's Session handling) — verified empirically: moving
# this under TYPE_CHECKING raises PydanticUserError on the first request.
import uuid  # noqa: TC003
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from alam.ai.retrieval.hybrid import DEFAULT_LIMIT, retrieve_memories
from alam.persistence.models.reading_session import ReadingSessionStatus
from alam.persistence.repositories.captures import CaptureRepository
from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.reading_sessions import ReadingSessionRepository
from alam.persistence.repositories.users import UserRepository
from alam.persistence.session import session_scope
from alam.services.capture_submission import (
    UnknownStructureUnitError,
    submit_capture,
)
from alam.services.epub_ingestion import UnknownMediaItemError
from alam.services.reading_sessions import (
    UnknownReadingSessionError,
    end_reading_session,
    get_reader_context,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import Capture, Memory, ReadingSession

router = APIRouter(prefix="/books/{media_item_id}", tags=["captures"])

EndStatus = Literal["completed", "abandoned"]

_END_STATUS_MAP: dict[str, ReadingSessionStatus] = {
    "completed": ReadingSessionStatus.COMPLETED,
    "abandoned": ReadingSessionStatus.ABANDONED,
}


class ReadingSessionResponse(BaseModel):
    id: str
    media_item_id: str
    status: str
    current_structure_unit_id: str
    current_ordinal: int
    current_progress: float
    started_at: dt.datetime
    ended_at: dt.datetime | None


class CaptureResponse(BaseModel):
    id: str
    reading_session_id: str
    media_item_id: str
    structure_unit_id: str
    structure_ordinal: int
    status: str
    raw_transcript: str | None
    corrected_transcript: str | None
    created_at: dt.datetime


class MemoryResponse(BaseModel):
    id: str
    memory_type: str
    content: str
    structure_ordinal: int
    created_at: dt.datetime


def _reading_session_response(reading_session: ReadingSession) -> ReadingSessionResponse:
    return ReadingSessionResponse(
        id=str(reading_session.id),
        media_item_id=str(reading_session.media_item_id),
        status=reading_session.status.value,
        current_structure_unit_id=str(reading_session.current_structure_unit_id),
        current_ordinal=reading_session.current_ordinal,
        current_progress=reading_session.current_progress,
        started_at=reading_session.started_at,
        ended_at=reading_session.ended_at,
    )


def _capture_response(capture: Capture) -> CaptureResponse:
    return CaptureResponse(
        id=str(capture.id),
        reading_session_id=str(capture.reading_session_id),
        media_item_id=str(capture.media_item_id),
        structure_unit_id=str(capture.structure_unit_id),
        structure_ordinal=capture.structure_ordinal,
        status=capture.status.value,
        raw_transcript=capture.raw_transcript,
        corrected_transcript=capture.corrected_transcript,
        created_at=capture.created_at,
    )


def _memory_response(memory: Memory) -> MemoryResponse:
    return MemoryResponse(
        id=str(memory.id),
        memory_type=memory.memory_type.value,
        content=memory.content,
        structure_ordinal=memory.structure_ordinal,
        created_at=memory.created_at,
    )


async def _read_audio_bytes(request: Request) -> bytes:
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="request body is empty")
    return raw


@router.post("/captures", response_model=CaptureResponse, status_code=status.HTTP_201_CREATED)
async def create_capture(
    media_item_id: uuid.UUID,
    structure_unit_id: uuid.UUID,
    request: Request,
    session: Session = Depends(session_scope),
) -> CaptureResponse:
    audio = await _read_audio_bytes(request)
    owner = UserRepository(session).get_owner()
    if owner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="book not found")

    try:
        capture = submit_capture(
            session,
            user_id=owner.id,
            media_item_id=media_item_id,
            structure_unit_id=structure_unit_id,
            audio=audio,
        )
    except (UnknownMediaItemError, UnknownStructureUnitError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _capture_response(capture)


@router.get("/captures/{capture_id}", response_model=CaptureResponse)
def get_capture(
    media_item_id: uuid.UUID, capture_id: uuid.UUID, session: Session = Depends(session_scope)
) -> CaptureResponse:
    owner = UserRepository(session).get_owner()
    item = MediaItemRepository(session).get(media_item_id) if owner else None
    if item is None or owner is None or item.user_id != owner.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="book not found")

    capture = CaptureRepository(session).get(capture_id)
    if capture is None or capture.media_item_id != media_item_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="capture not found")

    return _capture_response(capture)


@router.get("/reading-sessions/active", response_model=ReadingSessionResponse)
def get_active_reading_session(
    media_item_id: uuid.UUID, session: Session = Depends(session_scope)
) -> ReadingSessionResponse:
    owner = UserRepository(session).get_owner()
    item = MediaItemRepository(session).get(media_item_id) if owner else None
    if item is None or owner is None or item.user_id != owner.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="book not found")

    reading_session = ReadingSessionRepository(session).get_active_for_media_item(media_item_id)
    if reading_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no active reading session"
        )

    return _reading_session_response(reading_session)


@router.post("/reading-sessions/{reading_session_id}/end", response_model=ReadingSessionResponse)
def end_session(
    media_item_id: uuid.UUID,
    reading_session_id: uuid.UUID,
    end_status: EndStatus,
    session: Session = Depends(session_scope),
) -> ReadingSessionResponse:
    owner = UserRepository(session).get_owner()
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="reading session not found"
        )

    try:
        reading_session = end_reading_session(
            session,
            user_id=owner.id,
            media_item_id=media_item_id,
            reading_session_id=reading_session_id,
            status=_END_STATUS_MAP[end_status],
        )
    except UnknownReadingSessionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return _reading_session_response(reading_session)


@router.get("/memories", response_model=list[MemoryResponse])
def search_memories(
    media_item_id: uuid.UUID,
    query: str,
    limit: int = DEFAULT_LIMIT,
    session: Session = Depends(session_scope),
) -> list[MemoryResponse]:
    """Spoiler-safe hybrid search (M3, ADR-0002) over the owner's active
    reading position — the first production caller of ``retrieve_memories``.
    ``current_ordinal`` is never a request parameter; ``get_reader_context``
    resolves it from the media item's active reading session."""
    owner = UserRepository(session).get_owner()
    if owner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="book not found")

    try:
        reader_context = get_reader_context(session, user_id=owner.id, media_item_id=media_item_id)
    except UnknownReadingSessionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    memories = retrieve_memories(session, reader_context, query=query, limit=limit)
    return [_memory_response(memory) for memory in memories]
