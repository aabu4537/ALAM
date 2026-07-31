"""EPUB ingestion and structure verification endpoints (ADR-0004).

``/epub/preview`` only parses — no database access, no owner resolution,
nothing written. ``/epub/commit`` persists the parsed proposal as an
*unverified* structure hypothesis. ``GET .../structure`` reads whatever is
currently persisted, verified or not. ``PUT .../structure`` applies the
human's corrections and is the only path that marks the item verified.

The EPUB body is raw bytes, not a multipart upload — same tradeoff as the
Goodreads import router: avoids adding `python-multipart` for a single
caller pre-M7.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from alam.domain.structure_review import DesiredUnit, StructurePlanError
from alam.media.books.epub import EpubParseError
from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.structure_units import StructureUnitRepository
from alam.persistence.repositories.users import UserRepository
from alam.persistence.session import session_scope
from alam.services.epub_ingestion import UnknownMediaItemError, commit_epub, preview_epub
from alam.services.structure_verification import verify_structure

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.media.books.epub import ParsedEpub
    from alam.persistence.models import MediaItem, MediaStructureUnit

router = APIRouter(prefix="/books", tags=["books"])

OWNER_DISPLAY_NAME = "Owner"


class ProposedUnitResponse(BaseModel):
    ordinal: int
    label: str
    first_lines: str | None


class EpubPreviewResponse(BaseModel):
    title: str | None
    author: str | None
    units: list[ProposedUnitResponse]


class StructureUnitResponse(BaseModel):
    id: str
    ordinal: int
    label: str
    first_lines: str | None


class BookStructureResponse(BaseModel):
    media_item_id: str
    title: str
    structure_verified: bool
    units: list[StructureUnitResponse]


class DesiredUnitRequest(BaseModel):
    id: uuid.UUID | None = None
    label: str
    first_lines: str | None = None


def _preview_response(parsed: ParsedEpub) -> EpubPreviewResponse:
    return EpubPreviewResponse(
        title=parsed.metadata.title,
        author=parsed.metadata.author,
        units=[
            ProposedUnitResponse(ordinal=u.ordinal, label=u.label, first_lines=u.first_lines)
            for u in parsed.units
        ],
    )


def _structure_response(item: MediaItem, units: list[MediaStructureUnit]) -> BookStructureResponse:
    return BookStructureResponse(
        media_item_id=str(item.id),
        title=item.title,
        structure_verified=item.structure_is_verified,
        units=[
            StructureUnitResponse(
                id=str(u.id), ordinal=u.ordinal, label=u.label, first_lines=u.first_lines
            )
            for u in units
        ],
    )


async def _read_epub_bytes(request: Request) -> bytes:
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="request body is empty")
    return raw


@router.post("/epub/preview", response_model=EpubPreviewResponse)
async def preview(request: Request) -> EpubPreviewResponse:
    data = await _read_epub_bytes(request)
    try:
        parsed = preview_epub(data)
    except EpubParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _preview_response(parsed)


@router.post("/epub/commit", response_model=BookStructureResponse)
async def commit(
    request: Request,
    media_item_id: uuid.UUID | None = None,
    session: Session = Depends(session_scope),
) -> BookStructureResponse:
    data = await _read_epub_bytes(request)
    owner = UserRepository(session).get_or_create_owner(OWNER_DISPLAY_NAME)
    try:
        item, units = commit_epub(session, user_id=owner.id, media_item_id=media_item_id, data=data)
    except EpubParseError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except UnknownMediaItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _structure_response(item, units)


@router.get("/{media_item_id}/structure", response_model=BookStructureResponse)
def get_structure(
    media_item_id: uuid.UUID, session: Session = Depends(session_scope)
) -> BookStructureResponse:
    owner = UserRepository(session).get_owner()
    item = MediaItemRepository(session).get(media_item_id) if owner else None
    if item is None or owner is None or item.user_id != owner.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="book not found")

    units = list(StructureUnitRepository(session).list_for_media_item(media_item_id))
    return _structure_response(item, units)


@router.put("/{media_item_id}/structure", response_model=BookStructureResponse)
def put_structure(
    media_item_id: uuid.UUID,
    desired_units: list[DesiredUnitRequest],
    session: Session = Depends(session_scope),
) -> BookStructureResponse:
    owner = UserRepository(session).get_owner()
    if owner is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="book not found")

    desired = [
        DesiredUnit(keep_id=u.id, label=u.label, first_lines=u.first_lines) for u in desired_units
    ]
    try:
        item, units = verify_structure(
            session, media_item_id=media_item_id, user_id=owner.id, desired=desired
        )
    except UnknownMediaItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StructurePlanError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _structure_response(item, units)
