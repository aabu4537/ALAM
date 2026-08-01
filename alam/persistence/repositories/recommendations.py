from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from alam.persistence.models.recommendation import Recommendation, RecommendationStatus

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session


class RecommendationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_pending(
        self,
        *,
        user_id: uuid.UUID,
        generated_shelf_snapshot: list[str],
        generated_fact_snapshot: list[str],
    ) -> Recommendation:
        """Written and flushed *before* the LLM call — a crash or timeout
        after this point leaves a ``pending`` row a retry can find and
        overwrite, not a lost call with no record."""
        recommendation = Recommendation(
            user_id=user_id,
            generated_shelf_snapshot=generated_shelf_snapshot,
            generated_fact_snapshot=generated_fact_snapshot,
            status=RecommendationStatus.PENDING,
        )
        self._session.add(recommendation)
        self._session.flush()
        return recommendation

    def get_latest_for_user(self, user_id: uuid.UUID) -> Recommendation | None:
        return self._session.scalars(
            select(Recommendation)
            .where(Recommendation.user_id == user_id)
            .order_by(Recommendation.created_at.desc())
            .limit(1)
        ).first()

    def mark_complete(
        self,
        recommendation: Recommendation,
        *,
        candidates: list[dict[str, Any]],
        model: str | None,
        prompt_version_id: str | None,
    ) -> Recommendation:
        """``model``/``prompt_version_id`` are nullable here on purpose: an
        empty to-read shelf short-circuits to ``complete`` with no LLM call,
        so there is nothing to record."""
        recommendation.status = RecommendationStatus.COMPLETE
        recommendation.candidates = candidates
        recommendation.model = model
        recommendation.prompt_version_id = prompt_version_id
        self._session.flush()
        return recommendation

    def mark_blocked_ungrounded(
        self,
        recommendation: Recommendation,
        *,
        model: str,
        prompt_version_id: str,
        ungrounded_citations: list[dict[str, Any]],
    ) -> Recommendation:
        """``candidates`` is never set on a blocked row — resolving cited
        text to display happens only after groundedness passes (see
        ``services/recommendations.py``), so there is nothing composed yet
        to retain for audit beyond which citations failed."""
        recommendation.status = RecommendationStatus.BLOCKED_UNGROUNDED
        recommendation.model = model
        recommendation.prompt_version_id = prompt_version_id
        recommendation.ungrounded_citations = ungrounded_citations
        self._session.flush()
        return recommendation

    def mark_failed(self, recommendation: Recommendation, *, error: str) -> Recommendation:
        recommendation.status = RecommendationStatus.FAILED
        recommendation.error = error
        self._session.flush()
        return recommendation
