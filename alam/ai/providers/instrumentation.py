"""Wraps whatever ``get_llm_provider()`` returns so every ``.complete()``
call is recorded, without touching any of the four call sites themselves
(M5.5a — ``capture_pipeline.py``, ``consolidation.py``,
``prediction_resolution.py``).

``call_site`` isn't passed in — nothing calls ``.complete()`` with one, and
adding that parameter would mean editing every call site this wrapper is
explicitly meant to leave alone. It's recovered from the call stack instead:
whichever module and function called ``.complete()`` is the call site,
exactly as if a human read the traceback.

Writes through an independent session, not the caller's. The four call
sites all run inside a job handler's transaction, and that transaction can
still roll back after the LLM call already happened — a parse failure on
the response, for instance. The LLM spend is real regardless of what the
handler does next, so the record of it must survive a rollback the caller
triggers for unrelated reasons.
"""

from __future__ import annotations

import inspect
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from alam.jobs.context import current_job_id
from alam.persistence.repositories.llm_calls import LLMCallRepository
from alam.persistence.session import get_session_factory

if TYPE_CHECKING:
    from alam.ai.providers.llm import Completion, LLMProvider


def _call_site() -> str:
    """The module and function of whoever called ``complete()`` — i.e. the
    caller of the caller of this function. ``context=0`` skips reading
    source lines, which ``inspect.stack()`` does per frame by default and
    doesn't need here."""
    frame = inspect.stack(context=0)[2]
    module = frame.frame.f_globals.get("__name__", "?")
    return f"{module}.{frame.function}"


@dataclass
class InstrumentedLLMProvider:
    """Implements ``LLMProvider`` by delegating to another one and recording
    every call. Wraps, doesn't replace — the inner provider still does the
    actual work."""

    inner: LLMProvider

    @property
    def model(self) -> str:
        return self.inner.model

    def complete(
        self,
        prompt: str,
        *,
        prompt_version_id: str,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> Completion:
        call_site = _call_site()
        started = time.perf_counter()
        completion = self.inner.complete(
            prompt,
            prompt_version_id=prompt_version_id,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        latency_ms = (time.perf_counter() - started) * 1000

        with get_session_factory()() as session:
            LLMCallRepository(session).create(
                call_site=call_site,
                prompt_version_id=completion.prompt_version_id,
                model=completion.model,
                input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                latency_ms=latency_ms,
                job_id=current_job_id.get(),
            )
            session.commit()

        return completion
