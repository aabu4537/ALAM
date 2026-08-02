from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from alam.persistence.models.llm_call import LLMCall

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session


class LLMCallRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        call_site: str,
        provider: str | None,
        prompt_version_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        job_id: uuid.UUID | None,
    ) -> LLMCall:
        call = LLMCall(
            call_site=call_site,
            provider=provider,
            prompt_version_id=prompt_version_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            job_id=job_id,
        )
        self._session.add(call)
        self._session.flush()
        return call

    def list_all(self) -> Sequence[LLMCall]:
        """Ordered newest first. Dev/personal scale — same "small enough to
        load wholesale" precedent ``preference_facts``' L3 tier already
        uses — the cost view (``services/cost_view.py``) aggregates over
        this directly rather than pushing cost computation into SQL, since
        the pricing table is Python-side.

        Tiebreaks on ``id`` (UUIDv7, time-ordered) after ``created_at`` —
        Postgres's ``now()`` returns the same value for every statement
        inside one transaction, so two calls recorded in quick succession
        (or, in a test, two rows inserted in the same wrapping transaction)
        can otherwise tie on ``created_at`` alone, making "newest first"
        order non-deterministic exactly when a reader would care most.
        """
        return self._session.scalars(
            select(LLMCall).order_by(LLMCall.created_at.desc(), LLMCall.id.desc())
        ).all()
