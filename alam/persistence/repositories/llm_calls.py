from __future__ import annotations

from typing import TYPE_CHECKING

from alam.persistence.models.llm_call import LLMCall

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session


class LLMCallRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        call_site: str,
        prompt_version_id: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        job_id: uuid.UUID | None,
    ) -> LLMCall:
        call = LLMCall(
            call_site=call_site,
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
