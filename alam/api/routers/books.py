"""EPUB ingestion, structure verification, and reading-time endpoints
(ADR-0004; ADR-0002 amendment for the two structure reads).

``/epub/preview`` only parses — no database access, no owner resolution,
nothing written. ``/epub/commit`` persists the parsed proposal as an
*unverified* structure hypothesis.

``GET .../structure`` and ``GET .../chapters`` are deliberately two routes,
not one with a mode switch, because they serve two audiences with opposite
needs: ``.../structure`` is the one-time pre-reading verification read — the
full, unfiltered unit list including ``first_lines`` (raw book prose), so a
human can confirm chapter boundaries before anything is indexed — and it
refuses once verification is complete, since nothing about reviewing
chapter boundaries is still a legitimate reason to read the whole book's
opening lines on demand after that point. ``.../chapters`` is the
reading-time read: ordinal-scoped via ``ReaderContext``, and ``first_lines``
is not a field either response shares — it is structurally absent from
``.../chapters``' response model, not filtered out of a shared one.
``PUT .../structure`` applies the human's corrections and is the only path
that marks the item verified.

The EPUB body is raw bytes, not a multipart upload — same tradeoff as the
Goodreads import router: avoids adding `python-multipart` for a single
caller pre-M7.

``GET .../journey-summary`` and ``GET .../briefing`` are the same kind of
split: a journey summary is for a book with a reading position to
summarize (``ReaderContext``-scoped); a briefing (M6 session 4) is for a
book with none yet — it refuses once an active ``ReadingSession`` exists,
pointing at ``.../journey-summary`` instead, the same "pre-book" boundary
``ai/prompts/briefing.py`` and ``services/briefing.py`` describe in more
depth.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from alam.api.dependencies import reader_context_dependency
from alam.domain.catalog_metadata import catalog_entry
from alam.domain.structure_review import DesiredUnit, StructurePlanError
from alam.media.books.epub import EpubParseError
from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.reading_sessions import ReadingSessionRepository
from alam.persistence.repositories.structure_units import StructureUnitRepository
from alam.persistence.repositories.users import UserRepository
from alam.persistence.session import session_scope
from alam.services.briefing import (
    BriefingBlockedError,
    BriefingGenerationError,
    get_or_generate_briefing,
)
from alam.services.briefing import UnknownMediaItemError as UnknownBriefingMediaItemError
from alam.services.epub_ingestion import UnknownMediaItemError, commit_epub, preview_epub
from alam.services.journey_summary import (
    JourneySummaryBlockedError,
    JourneySummaryGenerationError,
    get_or_generate_journey_summary,
)
from alam.services.journey_summary import (
    UnknownMediaItemError as UnknownJourneySummaryMediaItemError,
)
from alam.services.predictions import list_predictions_for_book
from alam.services.structure_verification import verify_structure
from alam.services.structure_visibility import list_visible_structure_units

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.domain.reader_context import ReaderContext
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


class VisibleStructureUnitResponse(BaseModel):
    id: str
    ordinal: int
    label: str
    # Deliberately no `first_lines` field — see the module docstring. This is
    # not the same shape as `StructureUnitResponse` with a field omitted at
    # serialization time; it is a distinct model that never carries raw book
    # prose, so there is no "forgot to strip it" failure mode.


class VisibleStructureResponse(BaseModel):
    media_item_id: str
    title: str
    units: list[VisibleStructureUnitResponse]


class DesiredUnitRequest(BaseModel):
    id: uuid.UUID | None = None
    label: str
    first_lines: str | None = None


class PredictionResponse(BaseModel):
    id: str
    statement: str
    status: str
    made_at_ordinal: int
    resolution_window: int
    resolved_at: str | None
    evidence: list[str]


class JourneySummaryResponse(BaseModel):
    id: str
    media_item_id: str
    narrative: str
    generated_at_ordinal: int
    model: str
    prompt_version_id: str


class BriefingClaimResponse(BaseModel):
    text: str
    """Copied verbatim from the cited ``preference_fact``/``memory``'s own
    stored text — never written by the LLM (same discipline ADR-0014
    established for recommendations)."""
    cites_type: str
    cites_id: str


class BriefingResponse(BaseModel):
    id: str
    media_item_id: str
    title: str
    author: str | None
    blurb: str | None
    subjects: list[str]
    claims: list[BriefingClaimResponse]


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
    """The verification read (ADR-0004 steps 2-4): every unit, including
    ``first_lines`` raw prose, for reviewing and correcting chapter
    boundaries before confirming them. Refuses once ``PUT .../structure``
    has verified the book — ``GET .../chapters`` is the reading-time
    equivalent from that point on, and this route returning the full,
    unfiltered book on request forever would let an already-reading client
    re-fetch every future chapter's opening lines on demand."""
    owner = UserRepository(session).get_owner()
    item = MediaItemRepository(session).get(media_item_id) if owner else None
    if item is None or owner is None or item.user_id != owner.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="book not found")

    if item.structure_is_verified:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="structure is already verified; use GET .../chapters instead",
        )

    units = list(StructureUnitRepository(session).list_for_media_item(media_item_id))
    return _structure_response(item, units)


@router.get("/{media_item_id}/chapters", response_model=VisibleStructureResponse)
def get_chapters(
    media_item_id: uuid.UUID,
    session: Session = Depends(session_scope),
    reader_context: ReaderContext = Depends(reader_context_dependency),
) -> VisibleStructureResponse:
    """The reading-time read: chapter id, ordinal, and label — never
    ``first_lines`` — for every unit up to the active reading session's
    current ordinal (ADR-0002 amendment, same ``ReaderContext`` pattern as
    ``GET .../memories`` and ``GET .../predictions``)."""
    item = MediaItemRepository(session).get(media_item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="book not found")

    units = list_visible_structure_units(session, reader_context=reader_context)
    return VisibleStructureResponse(
        media_item_id=str(item.id),
        title=item.title,
        units=[
            VisibleStructureUnitResponse(id=str(u.id), ordinal=u.ordinal, label=u.label)
            for u in units
        ],
    )


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


@router.get("/{media_item_id}/predictions", response_model=list[PredictionResponse])
def get_predictions(
    session: Session = Depends(session_scope),
    reader_context: ReaderContext = Depends(reader_context_dependency),
) -> list[PredictionResponse]:
    """Predictions extracted from this book's reflections, oldest first (M5,
    ADR-0009), scoped to the active reading session's current ordinal
    (ADR-0012) — not by which session made or resolved them. A prediction
    made past the current position is omitted; one made before it but not
    yet due for resolution renders ``pending`` with no evidence even if an
    earlier, further-along session already resolved it. Same shape as
    ``GET .../memories``: no ordinal is ever a request parameter, and a book
    with no active reading session 404s rather than falling back to
    unfiltered history."""
    predictions = list_predictions_for_book(session, reader_context=reader_context)
    return [
        PredictionResponse(
            id=str(p.id),
            statement=p.statement,
            status=p.status.value,
            made_at_ordinal=p.made_at_ordinal,
            resolution_window=p.resolution_window,
            resolved_at=p.resolved_at.isoformat() if p.resolved_at else None,
            evidence=p.evidence,
        )
        for p in predictions
    ]


@router.get("/{media_item_id}/journey-summary", response_model=JourneySummaryResponse)
def get_journey_summary(
    session: Session = Depends(session_scope),
    reader_context: ReaderContext = Depends(reader_context_dependency),
) -> JourneySummaryResponse:
    """A short narrative of the reader's journey through this book so far
    (M6 session 1, ADR-0013), generated synchronously on first read or once
    the cached artifact goes stale (``services.journey_summary``). Same
    ``ReaderContext`` gating as ``.../predictions`` and ``.../memories``: no
    ordinal is ever a request parameter, and a book with no active reading
    session 404s.

    A fresh generation attempt that fails the Layer 3 leak check never
    reaches this response — the service raises instead of returning the
    blocked draft, and this route turns that into a 503 rather than a
    silent fallback to stale content.
    """
    try:
        summary = get_or_generate_journey_summary(session, reader_context=reader_context)
    except UnknownJourneySummaryMediaItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except JourneySummaryBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except JourneySummaryGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    assert summary.draft is not None  # only COMPLETE rows are ever returned here
    assert summary.model is not None
    assert summary.prompt_version_id is not None
    return JourneySummaryResponse(
        id=str(summary.id),
        media_item_id=str(summary.media_item_id),
        narrative=summary.draft,
        generated_at_ordinal=summary.generated_at_ordinal,
        model=summary.model,
        prompt_version_id=summary.prompt_version_id,
    )


@router.get("/{media_item_id}/briefing", response_model=BriefingResponse)
def get_briefing(
    media_item_id: uuid.UUID, session: Session = Depends(session_scope)
) -> BriefingResponse:
    """A spoiler-safe pre-book orientation for a book the reader has not
    started yet (M6 session 4) — no ``ReaderContext``, since there is no
    reading position to construct one from. Refuses once the book has an
    active ``ReadingSession``: ``.../journey-summary`` is the equivalent
    for a book already in progress, same "two routes, not a mode switch"
    split ``.../structure`` vs ``.../chapters`` already established.

    The teaser (``blurb``/``subjects``) is read live from the item's own
    cached catalog entry (ADR-0015) — never persisted a second time on the
    briefing row. ``claims`` are the reader's own facts/memories about
    *other* books the LLM selected as relevant, with text ALAM composed
    from the cited record, never from the LLM (same discipline ADR-0014
    established for recommendations — no Layer 3 leak check runs here for
    the identical reason: the schema has no field an LLM-authored
    characterization of this book's content could occupy)."""
    owner = UserRepository(session).get_owner()
    item = MediaItemRepository(session).get(media_item_id) if owner else None
    if item is None or owner is None or item.user_id != owner.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="book not found")

    active_session = ReadingSessionRepository(session).get_active_for_media_item(media_item_id)
    if active_session is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="book is already being read; see GET .../journey-summary instead",
        )

    try:
        briefing = get_or_generate_briefing(session, media_item_id=media_item_id)
    except UnknownBriefingMediaItemError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BriefingBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except BriefingGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    assert briefing.claims is not None  # only COMPLETE rows are ever returned here
    entry = catalog_entry(item.attributes) or {}
    return BriefingResponse(
        id=str(briefing.id),
        media_item_id=str(item.id),
        title=item.title,
        author=item.attributes.get("author"),
        blurb=entry.get("blurb"),
        subjects=entry.get("subjects", []),
        claims=[BriefingClaimResponse(**claim) for claim in briefing.claims],
    )
