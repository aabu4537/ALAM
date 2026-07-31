"""Handler registry.

A handler receives an open session and the job's payload, and either returns
(success) or raises (failure). It must not commit — the runner owns the
transaction boundary so a partial handler write is rolled back before the
failure is recorded.

M0 ships one no-op handler. Real handlers arrive with the milestones that need
them: transcription and extraction at M2, embedding at M3, consolidation at M4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class JobHandler(Protocol):
    def __call__(self, session: Session, payload: dict[str, Any]) -> None: ...


class UnknownJobTypeError(LookupError):
    """Raised when a job names a handler that is not registered.

    Treated as an ordinary job failure rather than a crash — a stale job type
    left in the queue by a rollback must not take the whole drain down with it.
    """


_HANDLERS: dict[str, JobHandler] = {}

NOOP = "noop"

TRANSCRIBE_CAPTURE = "transcribe_capture"
"""Job type enqueued by ``services.capture_submission``. The handler itself
arrives in M2 session 2 — until it is registered, a job of this type fails
with ``UnknownJobTypeError`` and retries out, which is fine for an
in-progress milestone branch that never reaches production undrained."""


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
