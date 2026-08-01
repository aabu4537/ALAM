"""The ``llm_calls`` table (M5.5a) — one row per ``LLMProvider.complete()``
call, written by the instrumenting wrapper in ``ai/providers/instrumentation.py``
rather than by any individual call site.

Immutable once written, same idiom as ``prediction_evidence``: ``created_at``
only, no ``updated_at`` — a call either happened or it didn't, and nothing
about it changes afterward.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base, UUIDPrimaryKeyMixin


class LLMCall(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "llm_calls"

    call_site: Mapped[str] = mapped_column(String(200), nullable=False)
    """``{module}.{function}`` of whatever called ``.complete()``, recovered
    from the call stack inside the instrumenting wrapper — not passed in by
    the caller. See ``ai/providers/instrumentation.py``."""

    prompt_version_id: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)

    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)

    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    """From ``jobs.context.current_job_id``, a contextvar set by
    ``jobs/runner.py`` for the duration of a handler call — not threaded
    through any handler signature. NULL for a call made outside a job (an
    eval run, a one-off script)."""

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_llm_calls_job_id", "job_id"),)

    def __repr__(self) -> str:
        return (
            f"<LLMCall id={self.id} call_site={self.call_site!r} "
            f"model={self.model!r} tokens={self.input_tokens}+{self.output_tokens}>"
        )
