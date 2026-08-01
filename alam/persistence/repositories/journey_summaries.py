from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from alam.persistence.models.journey_summary import JourneySummary, JourneySummaryStatus

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session


class JourneySummaryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_pending(
        self, *, media_item_id: uuid.UUID, generated_at_ordinal: int
    ) -> JourneySummary:
        """Written and flushed *before* the LLM call — a crash or timeout
        after this point leaves a ``pending`` row a retry can find and
        overwrite via ``mark_failed``/``mark_complete``, not a lost call with
        no record."""
        journey_summary = JourneySummary(
            media_item_id=media_item_id,
            generated_at_ordinal=generated_at_ordinal,
            status=JourneySummaryStatus.PENDING,
        )
        self._session.add(journey_summary)
        self._session.flush()
        return journey_summary

    def get_latest_for_media_item(self, media_item_id: uuid.UUID) -> JourneySummary | None:
        return self._session.scalars(
            select(JourneySummary)
            .where(JourneySummary.media_item_id == media_item_id)
            .order_by(JourneySummary.created_at.desc())
            .limit(1)
        ).first()

    def mark_complete(
        self,
        journey_summary: JourneySummary,
        *,
        draft: str,
        model: str,
        prompt_version_id: str,
        excluded_snapshot: list[dict[str, Any]],
    ) -> JourneySummary:
        journey_summary.status = JourneySummaryStatus.COMPLETE
        journey_summary.draft = draft
        journey_summary.model = model
        journey_summary.prompt_version_id = prompt_version_id
        journey_summary.layer3_leaked = False
        journey_summary.layer3_spans = []
        journey_summary.excluded_snapshot = excluded_snapshot
        self._session.flush()
        return journey_summary

    def mark_blocked_leaked(
        self,
        journey_summary: JourneySummary,
        *,
        draft: str,
        model: str,
        prompt_version_id: str,
        layer3_spans: list[str],
        excluded_snapshot: list[dict[str, Any]],
    ) -> JourneySummary:
        """The draft is retained for audit but ``status`` marks it unsafe to
        serve — the caller (``services/journey_summary.py``) never returns
        ``draft`` for a row in this status."""
        journey_summary.status = JourneySummaryStatus.BLOCKED_LEAKED
        journey_summary.draft = draft
        journey_summary.model = model
        journey_summary.prompt_version_id = prompt_version_id
        journey_summary.layer3_leaked = True
        journey_summary.layer3_spans = layer3_spans
        journey_summary.excluded_snapshot = excluded_snapshot
        self._session.flush()
        return journey_summary

    def mark_failed(self, journey_summary: JourneySummary, *, error: str) -> JourneySummary:
        journey_summary.status = JourneySummaryStatus.FAILED
        journey_summary.error = error
        self._session.flush()
        return journey_summary
