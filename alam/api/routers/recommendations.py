"""Recommendation read endpoint (M6 session 2, ADR-0014).

Library-wide, not ``/books/{id}``-scoped — no ``ReaderContext``, resolves
the single owner via ``UserRepository.get_owner()``, same as
``GET /preferences/taste-drift``. No owner or an empty to-read shelf both
render as an empty list rather than a 404 — same precedent, there's no
specific resource being asked for and missing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from alam.persistence.repositories.users import UserRepository
from alam.persistence.session import session_scope
from alam.services.recommendations import (
    RecommendationsBlockedError,
    RecommendationsGenerationError,
    get_or_generate_recommendations,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


class ClaimResponse(BaseModel):
    text: str
    """Copied verbatim from the cited ``preference_fact``/``memory``'s own
    stored text — never written by the LLM (ADR-0014)."""
    cites_type: str
    cites_id: str


class RecommendedCandidateResponse(BaseModel):
    media_item_id: str
    title: str
    claims: list[ClaimResponse]


class RecommendationsResponse(BaseModel):
    id: str | None
    generated_at: str | None
    recommendations: list[RecommendedCandidateResponse]


@router.get("", response_model=RecommendationsResponse)
def get_recommendations(session: Session = Depends(session_scope)) -> RecommendationsResponse:
    """The reader's own to-read shelf, filtered to what best matches their
    recorded taste, generated synchronously on first read or once the
    cached artifact goes stale (``services.recommendations``).

    A fresh generation attempt that cites an id that doesn't exist or
    doesn't belong to the reader never reaches this response — the service
    raises instead of returning it, and this route turns that into a 503
    rather than a silent fallback to stale content.
    """
    owner = UserRepository(session).get_owner()
    if owner is None:
        return RecommendationsResponse(id=None, generated_at=None, recommendations=[])

    try:
        recommendation = get_or_generate_recommendations(session, user_id=owner.id)
    except RecommendationsBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except RecommendationsGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    assert recommendation.candidates is not None  # only COMPLETE rows are ever returned here
    return RecommendationsResponse(
        id=str(recommendation.id),
        generated_at=recommendation.updated_at.isoformat(),
        recommendations=[
            RecommendedCandidateResponse(
                media_item_id=c["media_item_id"],
                title=c["title"],
                claims=[ClaimResponse(**claim) for claim in c["claims"]],
            )
            for c in recommendation.candidates
        ],
    )
