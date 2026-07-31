"""Handler registry.

A handler receives an open session and the job's payload, and either returns
(success) or raises (failure). It must not commit — the runner owns the
transaction boundary so a partial handler write is rolled back before the
failure is recorded.

M0 shipped one no-op handler. Real handlers arrive with the milestones that
need them: transcription and correction at M2 session 2, extraction at M2
session 3, embedding at M3, consolidation at M4. This module is the
composition root for that wiring — it imports concrete handler functions from
``services/`` and registers them, the same way ``api/main.py`` wires up
routers. It can do so without a circular import because job type *constants*
live in ``jobs/job_types.py``, not here — a service needs to name the job type
it enqueues, and importing it back from this module would be circular.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from alam.jobs.job_types import CORRECT_TRANSCRIPT, NOOP, TRANSCRIBE_CAPTURE
from alam.services.capture_pipeline import correct_transcript, transcribe_capture

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

__all__ = [
    "CORRECT_TRANSCRIPT",
    "NOOP",
    "TRANSCRIBE_CAPTURE",
    "JobHandler",
    "UnknownJobTypeError",
    "get_handler",
    "register",
    "registered_types",
]


class JobHandler(Protocol):
    def __call__(self, session: Session, payload: dict[str, Any]) -> None: ...


class UnknownJobTypeError(LookupError):
    """Raised when a job names a handler that is not registered.

    Treated as an ordinary job failure rather than a crash — a stale job type
    left in the queue by a rollback must not take the whole drain down with it.
    """


_HANDLERS: dict[str, JobHandler] = {}


def register(job_type: str, handler: JobHandler) -> None:
    if job_type in _HANDLERS:
        raise ValueError(f"handler already registered for {job_type!r}")
    _HANDLERS[job_type] = handler


def get_handler(job_type: str) -> JobHandler:
    try:
        return _HANDLERS[job_type]
    except KeyError as exc:
        raise UnknownJobTypeError(
            f"no handler registered for job type {job_type!r}; known types: {sorted(_HANDLERS)}"
        ) from exc


def registered_types() -> list[str]:
    return sorted(_HANDLERS)


def noop_handler(session: Session, payload: dict[str, Any]) -> None:
    """Does nothing, successfully.

    Exists so M0 can prove the queue end to end — claim, run, complete, retry,
    lease expiry — without any milestone's real work existing yet.
    """


register(NOOP, noop_handler)
register(TRANSCRIBE_CAPTURE, transcribe_capture)
register(CORRECT_TRANSCRIPT, correct_transcript)
