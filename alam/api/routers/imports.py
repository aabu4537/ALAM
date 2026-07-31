"""Goodreads CSV import endpoints.

Two-step per the M1 DoD: preview computes and returns a diff without writing
anything, commit re-parses the same upload and applies it in one transaction.
There is no server-side preview state held between the calls — no frontend
exists yet (CLAUDE.md) to make that worth building, so a caller must not let
the file change between the two requests. See `services.goodreads_import` for
that tradeoff spelled out.

The body is the raw CSV, not a multipart upload — this avoids adding
`python-multipart` as a dependency for what is, pre-M7, a single caller using
`curl --data-binary`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from alam.domain.goodreads import GoodreadsCSVError, ImportDiff
from alam.persistence.repositories.users import UserRepository
from alam.persistence.session import session_scope
from alam.services.goodreads_import import commit_import, preview_import

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter(prefix="/imports/goodreads", tags=["imports"])

OWNER_DISPLAY_NAME = "Owner"


class FieldChangeResponse(BaseModel):
    field: str
    old: Any
    new: Any


class NewBookResponse(BaseModel):
    title: str
    author: str
    dedupe_key: str


class UpdatedBookResponse(BaseModel):
    id: str
    title: str
    changes: list[FieldChangeResponse]


class SkippedRowResponse(BaseModel):
    row_index: int
    reason: str


class ImportDiffResponse(BaseModel):
    to_create: list[NewBookResponse]
    to_update: list[UpdatedBookResponse]
    unchanged_count: int
    skipped: list[SkippedRowResponse]


def _to_response(diff: ImportDiff) -> ImportDiffResponse:
    return ImportDiffResponse(
        to_create=[
            NewBookResponse(
                title=b.row.title,
                author=b.row.author,
                dedupe_key=f"{b.dedupe_key.kind}:{b.dedupe_key.value}",
            )
            for b in diff.to_create
        ],
        to_update=[
            UpdatedBookResponse(
                id=str(b.existing_id),
                title=b.row.title,
                changes=[
                    FieldChangeResponse(field=c.field, old=c.old, new=c.new) for c in b.changes
                ],
            )
            for b in diff.to_update
        ],
        unchanged_count=len(diff.unchanged),
        skipped=[SkippedRowResponse(row_index=s.row_index, reason=s.reason) for s in diff.skipped],
    )


async def _read_csv(request: Request) -> str:
    raw = await request.body()
    if not raw:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="request body is empty")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="body is not UTF-8 text"
        ) from exc


@router.post("/preview", response_model=ImportDiffResponse)
async def preview(
    request: Request, session: Session = Depends(session_scope)
) -> ImportDiffResponse:
    csv_text = await _read_csv(request)
    owner = UserRepository(session).get_owner()
    try:
        diff = preview_import(session, user_id=owner.id if owner else None, csv_text=csv_text)
    except GoodreadsCSVError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_response(diff)


@router.post("/commit", response_model=ImportDiffResponse)
async def commit(request: Request, session: Session = Depends(session_scope)) -> ImportDiffResponse:
    csv_text = await _read_csv(request)
    owner = UserRepository(session).get_or_create_owner(OWNER_DISPLAY_NAME)
    try:
        diff = commit_import(session, user_id=owner.id, csv_text=csv_text)
    except GoodreadsCSVError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_response(diff)
