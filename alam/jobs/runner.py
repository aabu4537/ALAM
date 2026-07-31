"""Bounded queue draining.

One ``drain`` is a single unit of work with a hard ceiling on both job count and
wall time, so it finishes and returns rather than being killed by a platform
timeout (ADR-0007). The caller decides how often to invoke it: a loop locally,
a scheduled HTTP request in production.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from alam.config.logging import get_logger
from alam.jobs.handlers import get_handler
from alam.jobs.queue import JobQueue
from alam.persistence.models.job import Job

log = get_logger(__name__)

# Evaluated at runtime, so Callable and Session cannot be deferred imports.
SessionFactory = Callable[[], Session]


@dataclass(frozen=True, slots=True)
class DrainResult:
    claimed: int = 0
    succeeded: int = 0
    failed: int = 0
    budget_exhausted: bool = False
    """True if the drain stopped on time rather than on an empty queue.

    A drain that keeps reporting this is a signal to raise the schedule
    frequency or the budget — the queue is growing faster than it is served.
    """

    @property
    def idle(self) -> bool:
        return self.claimed == 0


def drain(
    session_factory: SessionFactory,
    *,
    max_jobs: int,
    budget_seconds: float,
    lease_seconds: float,
) -> DrainResult:
    """Claim and run jobs until the queue is empty or the budget is spent.

    Jobs are taken one at a time on purpose. Claiming a batch would mean a
    single killed invocation leaves the whole batch to wait out its lease,
    which is a worse failure mode than the extra round trips cost.
    """
    if lease_seconds <= budget_seconds:
        raise ValueError(
            f"lease_seconds ({lease_seconds}) must exceed budget_seconds "
            f"({budget_seconds}); otherwise a job can be stolen from a worker "
            f"that is still running it"
        )

    started = time.monotonic()
    claimed = succeeded = failed = 0

    while claimed < max_jobs:
        if time.monotonic() - started >= budget_seconds:
            return DrainResult(claimed, succeeded, failed, budget_exhausted=True)

        with session_factory() as session:
            queue = JobQueue(session)
            batch = queue.claim(max_jobs=1, lease_seconds=lease_seconds)
            # Commit the claim before running anything. If the handler crashes,
            # the attempt must already be durable — otherwise the rollback
            # takes the attempt counter with it and the job retries forever.
            session.commit()

            if not batch:
                break

            job = batch[0]
            claimed += 1

            if _run_one(session, queue, job):
                succeeded += 1
            else:
                failed += 1

    return DrainResult(claimed, succeeded, failed, budget_exhausted=False)


def _run_one(session: Session, queue: JobQueue, job: Job) -> bool:
    """Run one claimed job. Returns True on success."""
    job_id, job_type, payload = job.id, job.job_type, job.payload

    try:
        get_handler(job_type)(session, payload)
    except Exception as exc:
        # Discard whatever the handler managed to write before failing. The
        # claim survives — it was committed above — so the job can be re-read
        # and its failure recorded against a clean transaction.
        session.rollback()

        reloaded = session.get(Job, job_id)
        if reloaded is None:
            log.error("job.vanished", job_id=str(job_id), job_type=job_type)
            return False

        queue.fail(reloaded, error=f"{type(exc).__name__}: {exc}")
        session.commit()

        log.warning(
            "job.failed",
            job_id=str(job_id),
            job_type=job_type,
            attempts=reloaded.attempts,
            max_attempts=reloaded.max_attempts,
            status=reloaded.status.value,
            error=str(exc),
        )
        return False

    queue.complete(job)
    session.commit()
    log.info("job.succeeded", job_id=str(job_id), job_type=job_type)
    return True
