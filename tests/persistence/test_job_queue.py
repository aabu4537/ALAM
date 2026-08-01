"""The concurrency guarantee the whole queue rests on.

These tests use their own committed transactions rather than the rolled-back
``session`` fixture — two workers sharing one connection would not exercise
``SKIP LOCKED`` at all, and the test would pass for the wrong reason.
"""

from __future__ import annotations

import datetime as dt
import threading
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from alam.jobs.queue import JobQueue
from alam.persistence.models.job import Job, JobStatus

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

pytestmark = pytest.mark.db

NOOP = "noop"


@pytest.fixture
def clean_jobs(migrated_engine: Engine) -> Iterator[Engine]:
    """Committed state, truncated either side. Not rolled back."""
    with migrated_engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE jobs CASCADE"))
    yield migrated_engine
    with migrated_engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE jobs CASCADE"))


class TestConcurrentClaiming:
    def test_two_workers_never_claim_the_same_job(self, clean_jobs: Engine) -> None:
        """The M0 definition of done.

        Two workers race over one queue. Every job must be claimed exactly
        once — no duplicates, none dropped. Without SKIP LOCKED this either
        deadlocks or double-claims.
        """
        job_count = 60
        with Session(clean_jobs) as session:
            queue = JobQueue(session)
            expected = {queue.enqueue(job_type=NOOP, payload={"n": i}).id for i in range(job_count)}
            session.commit()

        claimed: list[list[uuid.UUID]] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(2)

        def worker() -> None:
            mine: list[uuid.UUID] = []
            try:
                barrier.wait(timeout=10)
                with Session(clean_jobs) as session:
                    queue = JobQueue(session)
                    while True:
                        batch = queue.claim(max_jobs=5, lease_seconds=60)
                        session.commit()
                        if not batch:
                            break
                        mine.extend(j.id for j in batch)
            except BaseException as exc:
                errors.append(exc)
            finally:
                claimed.append(mine)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert errors == []
        all_claimed = [job_id for batch in claimed for job_id in batch]

        assert len(all_claimed) == len(set(all_claimed)), "a job was claimed twice"
        assert set(all_claimed) == expected, "a job was never claimed"
        assert len(all_claimed) == job_count

    def test_both_workers_actually_did_work(self, clean_jobs: Engine) -> None:
        """Guards the test above.

        If one worker claimed everything before the other started, the
        no-double-claim assertion would hold trivially and prove nothing.
        """
        with Session(clean_jobs) as session:
            queue = JobQueue(session)
            for i in range(60):
                queue.enqueue(job_type=NOOP, payload={"n": i})
            session.commit()

        counts: list[int] = []
        barrier = threading.Barrier(2)

        def worker() -> None:
            n = 0
            barrier.wait(timeout=10)
            with Session(clean_jobs) as session:
                queue = JobQueue(session)
                while True:
                    batch = queue.claim(max_jobs=1, lease_seconds=60)
                    session.commit()
                    if not batch:
                        break
                    n += 1
            counts.append(n)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert sum(counts) == 60
        assert all(c > 0 for c in counts), f"one worker did nothing: {counts}"


class TestLeases:
    def test_a_claimed_job_is_invisible_to_other_workers(self, clean_jobs: Engine) -> None:
        with Session(clean_jobs) as first:
            JobQueue(first).enqueue(job_type=NOOP, payload={})
            first.commit()

        with Session(clean_jobs) as first:
            assert len(JobQueue(first).claim(max_jobs=5, lease_seconds=60)) == 1
            first.commit()

            with Session(clean_jobs) as second:
                assert JobQueue(second).claim(max_jobs=5, lease_seconds=60) == []

    def test_an_expired_lease_is_reclaimed(self, clean_jobs: Engine) -> None:
        """ADR-0007. A killed serverless function cannot release its own claim.

        Without reclaim-on-expiry the job sits `running` forever and is never
        retried — silent, permanent loss with nothing raising an error.
        """
        with Session(clean_jobs) as session:
            queue = JobQueue(session)
            queue.enqueue(job_type=NOOP, payload={})
            session.commit()

            claimed = queue.claim(max_jobs=1, lease_seconds=-1)
            session.commit()
            assert len(claimed) == 1
            # Read the id before the session closes — the instance detaches.
            claimed_id = claimed[0].id

        with Session(clean_jobs) as session:
            reclaimed = JobQueue(session).claim(max_jobs=1, lease_seconds=60)
            session.commit()

            assert len(reclaimed) == 1
            assert reclaimed[0].id == claimed_id

    def test_reclaiming_counts_as_another_attempt(self, clean_jobs: Engine) -> None:
        """Otherwise a job that reliably kills its worker retries forever."""
        with Session(clean_jobs) as session:
            queue = JobQueue(session)
            queue.enqueue(job_type=NOOP, payload={})
            session.commit()
            queue.claim(max_jobs=1, lease_seconds=-1)
            session.commit()

            again = queue.claim(max_jobs=1, lease_seconds=60)
            session.commit()

            assert again[0].attempts == 2


class TestRetries:
    def test_failure_reschedules_with_backoff(self, clean_jobs: Engine) -> None:
        with Session(clean_jobs) as session:
            queue = JobQueue(session)
            queue.enqueue(job_type=NOOP, payload={}, max_attempts=3)
            session.commit()

            job = queue.claim(max_jobs=1, lease_seconds=60)[0]
            queue.fail(job, error="boom")
            session.commit()

            assert job.status is JobStatus.PENDING
            assert job.last_error == "boom"
            assert job.run_after > dt.datetime.now(dt.UTC)

    def test_a_rescheduled_job_is_not_claimable_until_run_after(self, clean_jobs: Engine) -> None:
        with Session(clean_jobs) as session:
            queue = JobQueue(session)
            queue.enqueue(job_type=NOOP, payload={}, max_attempts=3)
            session.commit()
            job = queue.claim(max_jobs=1, lease_seconds=60)[0]
            queue.fail(job, error="boom")
            session.commit()

            assert queue.claim(max_jobs=5, lease_seconds=60) == []

    def test_exhausting_attempts_marks_the_job_failed(self, clean_jobs: Engine) -> None:
        """`failed` is terminal. A job that cannot succeed must stop consuming
        drain budget forever."""
        with Session(clean_jobs) as session:
            queue = JobQueue(session)
            job = queue.enqueue(job_type=NOOP, payload={}, max_attempts=1)
            session.commit()

            claimed = queue.claim(max_jobs=1, lease_seconds=60)[0]
            queue.fail(claimed, error="boom")
            session.commit()

            assert claimed.status is JobStatus.FAILED
            assert queue.claim(max_jobs=5, lease_seconds=60) == []
            assert job.id == claimed.id

    def test_success_is_terminal(self, clean_jobs: Engine) -> None:
        with Session(clean_jobs) as session:
            queue = JobQueue(session)
            queue.enqueue(job_type=NOOP, payload={})
            session.commit()

            job = queue.claim(max_jobs=1, lease_seconds=60)[0]
            queue.complete(job)
            session.commit()

            assert job.status is JobStatus.SUCCEEDED
            assert queue.claim(max_jobs=5, lease_seconds=60) == []


class TestEnqueue:
    def test_enqueue_is_transactional(self, clean_jobs: Engine) -> None:
        """Rule 5's actual point. A job enqueued in a transaction that rolls
        back must not exist — that is what an external broker cannot give you.
        """
        with Session(clean_jobs) as session:
            JobQueue(session).enqueue(job_type=NOOP, payload={})
            session.rollback()

        with Session(clean_jobs) as session:
            assert session.query(Job).count() == 0

    def test_delayed_jobs_are_not_claimed_early(self, clean_jobs: Engine) -> None:
        with Session(clean_jobs) as session:
            queue = JobQueue(session)
            queue.enqueue(job_type=NOOP, payload={}, delay_seconds=300)
            session.commit()

            assert queue.claim(max_jobs=5, lease_seconds=60) == []

    def test_jobs_are_claimed_in_run_after_order(self, clean_jobs: Engine) -> None:
        with Session(clean_jobs) as session:
            queue = JobQueue(session)
            late = queue.enqueue(job_type=NOOP, payload={"o": "late"}, delay_seconds=-10)
            early = queue.enqueue(job_type=NOOP, payload={"o": "early"}, delay_seconds=-60)
            session.commit()

            claimed = queue.claim(max_jobs=2, lease_seconds=60)

            assert [j.id for j in claimed] == [early.id, late.id]
