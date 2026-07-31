"""The Postgres job queue.

Knows nothing about how it is triggered — a loop, an HTTP request, or a test
calls the same methods. That separation is what keeps the hosting decision in
ADR-0007 a deployment choice rather than an architectural one.

Never opens or commits a transaction. The caller owns the unit of work, which
is the entire point of rule 5: enqueueing a job and writing the row that
justifies it commit together or not at all.
"""

from __future__ import annotations

import datetime as dt
import random
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, text

from alam.domain.backoff import backoff_seconds, with_jitter
from alam.persistence.models.job import Job, JobStatus

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

DEFAULT_MAX_ATTEMPTS = 5

# One statement. The subquery locks candidate rows with SKIP LOCKED so
# concurrent workers step over each other's picks instead of blocking, and the
# UPDATE marks them claimed before any other transaction can see them.
#
# Both arms of the WHERE matter: the first is ordinary pending work, the second
# reclaims jobs whose worker died without releasing them (ADR-0007). Attempts
# increment here rather than on failure, so a job that kills its worker still
# exhausts its retries.
_CLAIM_SQL = text(
    """
    UPDATE jobs
       SET status = 'running',
           attempts = jobs.attempts + 1,
           claimed_at = now(),
           lease_expires_at = now() + (:lease_seconds * interval '1 second'),
           updated_at = now()
     WHERE jobs.id IN (
           SELECT id
             FROM jobs
            WHERE (status = 'pending' AND run_after <= now())
               OR (status = 'running' AND lease_expires_at < now())
            ORDER BY run_after, created_at
            FOR UPDATE SKIP LOCKED
            LIMIT :max_jobs
           )
    RETURNING id
    """
)


class JobQueue:
    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(
        self,
        *,
        job_type: str,
        payload: dict[str, Any] | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        delay_seconds: float = 0.0,
    ) -> Job:
        """Add a job. Visible to workers only once the caller commits."""
        job = Job(
            job_type=job_type,
            payload=payload or {},
            status=JobStatus.PENDING,
            attempts=0,
            max_attempts=max_attempts,
            run_after=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=delay_seconds),
        )
        self._session.add(job)
        self._session.flush()
        return job

    def claim(self, *, max_jobs: int, lease_seconds: float) -> Sequence[Job]:
        """Atomically claim up to ``max_jobs``, returned in run order.

        The claim is not durable until the caller commits. A worker should
        commit immediately and only then run handlers — otherwise a handler
        crash rolls back the attempt counter along with its own work, and the
        job retries forever without ever burning an attempt.
        """
        if max_jobs < 1:
            raise ValueError(f"max_jobs must be >= 1, got {max_jobs}")

        claimed_ids = list(
            self._session.scalars(
                _CLAIM_SQL, {"max_jobs": max_jobs, "lease_seconds": lease_seconds}
            ).all()
        )
        if not claimed_ids:
            return []

        return list(
            self._session.scalars(
                select(Job)
                .where(Job.id.in_(claimed_ids))
                .order_by(Job.run_after, Job.created_at)
                .execution_options(populate_existing=True)
            ).all()
        )

    def complete(self, job: Job) -> Job:
        """Mark a job done. Terminal — it will never be claimed again."""
        job.status = JobStatus.SUCCEEDED
        job.claimed_at = None
        job.lease_expires_at = None
        self._session.flush()
        return job

    def fail(self, job: Job, *, error: str) -> Job:
        """Record a failure, then either reschedule or give up.

        Attempts were already incremented at claim time, so this only decides
        whether any remain.
        """
        job.last_error = error
        job.claimed_at = None
        job.lease_expires_at = None

        if job.attempts >= job.max_attempts:
            job.status = JobStatus.FAILED
        else:
            delay = with_jitter(backoff_seconds(job.attempts), random.random())
            job.status = JobStatus.PENDING
            job.run_after = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=delay)

        self._session.flush()
        return job

    def get(self, job_id: uuid.UUID) -> Job | None:
        return self._session.get(Job, job_id)

    def pending_count(self) -> int:
        """Depth of claimable work. For diagnostics, not for control flow."""
        return len(
            list(
                self._session.scalars(
                    select(Job.id).where(
                        Job.status == JobStatus.PENDING,
                        Job.run_after <= dt.datetime.now(dt.UTC),
                    )
                ).all()
            )
        )
