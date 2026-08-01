from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from alam.persistence.models.briefing import Briefing, BriefingStatus

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session


class BriefingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_pending(
        self,
        *,
        media_item_id: uuid.UUID,
        generated_fact_snapshot: list[str],
        generated_catalog_present: bool,
    ) -> Briefing:
        """Written and flushed *before* the LLM call — a crash or timeout
        after this point leaves a ``pending`` row a retry can find and
        overwrite, not a lost call with no record."""
        briefing = Briefing(
            media_item_id=media_item_id,
            generated_fact_snapshot=generated_fact_snapshot,
            generated_catalog_present=generated_catalog_present,
            status=BriefingStatus.PENDING,
        )
        self._session.add(briefing)
        self._session.flush()
        return briefing

    def get_latest_for_media_item(self, media_item_id: uuid.UUID) -> Briefing | None:
        return self._session.scalars(
            select(Briefing)
            .where(Briefing.media_item_id == media_item_id)
            .order_by(Briefing.created_at.desc())
            .limit(1)
        ).first()

    def mark_complete(
        self,
        briefing: Briefing,
        *,
        claims: list[dict[str, Any]],
        model: str | None,
        prompt_version_id: str | None,
    ) -> Briefing:
        """``model``/``prompt_version_id`` are nullable here on purpose:
        nothing to personalize from short-circuits to ``complete`` with no
        LLM call, so there is nothing to record."""
        briefing.status = BriefingStatus.COMPLETE
        briefing.claims = claims
        briefing.model = model
        briefing.prompt_version_id = prompt_version_id
        self._session.flush()
        return briefing

    def mark_blocked_ungrounded(
        self,
        briefing: Briefing,
        *,
        model: str,
        prompt_version_id: str,
        ungrounded_citations: list[dict[str, Any]],
    ) -> Briefing:
        """``claims`` is never set on a blocked row — resolving cited text
        to display happens only after groundedness passes (see
        ``services/briefing.py``), so there is nothing composed yet to
        retain for audit beyond which citations failed."""
        briefing.status = BriefingStatus.BLOCKED_UNGROUNDED
        briefing.model = model
        briefing.prompt_version_id = prompt_version_id
        briefing.ungrounded_citations = ungrounded_citations
        self._session.flush()
        return briefing

    def mark_failed(self, briefing: Briefing, *, error: str) -> Briefing:
        briefing.status = BriefingStatus.FAILED
        briefing.error = error
        self._session.flush()
        return briefing
