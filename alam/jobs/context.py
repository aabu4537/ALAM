"""The currently-running job's id, available to code inside a handler
without threading it through every ``JobHandler`` signature (M5.5a).

``jobs/runner.py`` sets this for the duration of one handler call. Anything
running underneath — today, the LLM instrumentation wrapper in
``ai/providers/instrumentation.py`` — reads it to attribute an ``llm_calls``
row to the job that produced it. ``None`` outside a job (an eval run, a
one-off script).
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uuid

current_job_id: ContextVar[uuid.UUID | None] = ContextVar("current_job_id", default=None)
