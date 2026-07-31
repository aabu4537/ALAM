"""The ``jobs`` table.

A Postgres queue, claimed with ``SELECT ... FOR UPDATE SKIP LOCKED``. No
Celery, no Redis, no broker (CLAUDE.md rule 5) — the point is that enqueueing a
job and writing the row that justifies it are the *same transaction*, which no
external broker can offer.

A claim is a **lease**, not a flag. There is no always-on worker to notice its
own death, so a job whose lease expires is reclaimable rather than stranded in
``running`` forever. See ADR-0007.
"""

from __future__ import annotations

import datetime as dt
import enum
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class JobStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    """Terminal. Attempts are exhausted; the job will never be claimed again."""


class Job(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "jobs"

    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    """Resolved against the handler registry in ``alam.jobs.handlers``."""

    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            name="status",
            native_enum=False,
            create_constraint=True,
            length=20,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=JobStatus.PENDING,
        server_default=JobStatus.PENDING.value,
    )

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    """Incremented on claim, not on failure.

    Counting at claim time is what makes a worker that dies mid-job cost an
    attempt. Counting at failure would let a job that reliably kills its worker
    retry forever, because it never reaches the failure path.
    """

    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5"))

    run_after: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    """Earliest time this job may be claimed. Carries the retry backoff."""

    claimed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lease_expires_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """When another worker may take this job back.

    The only thing standing between a killed function and a permanently stuck
    job. Must comfortably exceed the drain budget so a job still being worked
    on is never stolen.
    """

    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # The claim query's two arms. Partial indexes keep them small — the vast
        # majority of rows are terminal and never scanned again.
        Index(
            "ix_jobs_claimable",
            "run_after",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_jobs_expired_leases",
            "lease_expires_at",
            postgresql_where=text("status = 'running'"),
        ),
        Index("ix_jobs_job_type_status", "job_type", "status"),
    )

    @property
    def attempts_remaining(self) -> int:
        return max(0, self.max_attempts - self.attempts)

    def __repr__(self) -> str:
        return (
            f"<Job id={self.id} type={self.job_type!r} status={self.status.value} "
            f"attempts={self.attempts}/{self.max_attempts}>"
        )
