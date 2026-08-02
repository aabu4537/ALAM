"""Preference profile read endpoints (ADR-0001, M4 session 3).

No caller-supplied user id, same as ``books.py`` and ``captures.py`` —
``UserRepository.get_owner()`` resolves the single owner account
(CLAUDE.md rule 9). Router-level ``require_owner_session`` (M7 session 2,
ADR-0017) is what actually keeps the real profile unreachable by an
unauthenticated caller; the single-owner resolution above only keeps it
separate from demo data, not private on its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from alam.api.dependencies import require_owner_session
from alam.persistence.repositories.users import UserRepository
from alam.persistence.session import session_scope
from alam.services.taste_drift import get_taste_drift

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter(
    prefix="/preferences", tags=["preferences"], dependencies=[Depends(require_owner_session)]
)


class TasteDriftEntryResponse(BaseModel):
    id: str
    statement: str
    confidence: float
    observation_count: int
    active: bool
    observed_from: str
    superseded_at: str | None


class TasteDriftChainResponse(BaseModel):
    history: list[TasteDriftEntryResponse]


class TasteDriftResponse(BaseModel):
    chains: list[TasteDriftChainResponse]


@router.get("/taste-drift", response_model=TasteDriftResponse)
def taste_drift(session: Session = Depends(session_scope)) -> TasteDriftResponse:
    """Every preference lineage, oldest fact to newest, each entry's
    confidence current as of this request (decayed for the still-active
    entry, frozen at retirement for the rest). No owner yet — nothing
    consolidated yet — both render as an empty list rather than a 404;
    there's no specific resource being asked for and missing.
    """
    owner = UserRepository(session).get_owner()
    if owner is None:
        return TasteDriftResponse(chains=[])

    chains = get_taste_drift(session, user_id=owner.id)
    return TasteDriftResponse(
        chains=[
            TasteDriftChainResponse(
                history=[
                    TasteDriftEntryResponse(
                        id=str(entry.fact.id),
                        statement=entry.fact.statement,
                        confidence=entry.confidence,
                        observation_count=entry.fact.observation_count,
                        active=entry.active,
                        observed_from=entry.fact.created_at.isoformat(),
                        superseded_at=(
                            entry.fact.superseded_at.isoformat()
                            if entry.fact.superseded_at
                            else None
                        ),
                    )
                    for entry in chain
                ]
            )
            for chain in chains
        ]
    )
