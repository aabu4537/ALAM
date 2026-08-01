"""Drain behaviour: bounds, failure isolation, and transaction discipline."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from alam.jobs import handlers
from alam.jobs.context import current_job_id
from alam.jobs.queue import JobQueue
from alam.jobs.runner import drain
from alam.persistence.models.job import Job, JobStatus

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

pytestmark = pytest.mark.db

NOOP = handlers.NOOP


@pytest.fixture
def factory(migrated_engine: Engine) -> Iterator[sessionmaker[Session]]:
    with migrated_engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE jobs CASCADE"))
    yield sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with migrated_engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE jobs CASCADE"))


@pytest.fixture
def temp_handler() -> Iterator[Any]:
    """Register handlers for one test and remove them afterwards."""
    registered: list[str] = []

    def add(job_type: str, fn: Any) -> str:
        handlers.register(job_type, fn)
        registered.append(job_type)
        return job_type

    yield add
    for job_type in registered:
        handlers._HANDLERS.pop(job_type, None)


def _enqueue(factory: sessionmaker[Session], job_type: str = NOOP, **kw: Any) -> None:
    with factory() as session:
        JobQueue(session).enqueue(job_type=job_type, payload=kw.pop("payload", {}), **kw)
        session.commit()


class TestDrainBounds:
    def test_empty_queue_is_idle(self, factory: sessionmaker[Session]) -> None:
        result = drain(factory, max_jobs=10, budget_seconds=5, lease_seconds=60)

        assert result.idle
        assert result.claimed == 0
        assert not result.budget_exhausted

    def test_processes_everything_available(self, factory: sessionmaker[Session]) -> None:
        for _ in range(7):
            _enqueue(factory)

        result = drain(factory, max_jobs=10, budget_seconds=10, lease_seconds=60)

        assert result.claimed == 7
        assert result.succeeded == 7
        assert not result.budget_exhausted

    def test_max_jobs_is_respected(self, factory: sessionmaker[Session]) -> None:
        for _ in range(10):
            _enqueue(factory)

        result = drain(factory, max_jobs=3, budget_seconds=10, lease_seconds=60)

        assert result.claimed == 3

    def test_budget_stops_the_drain(
        self, factory: sessionmaker[Session], temp_handler: Any
    ) -> None:
        """The bound that keeps an invocation under the platform ceiling."""

        def slow(session: Session, payload: dict[str, Any]) -> None:
            time.sleep(0.15)

        job_type = temp_handler("slow", slow)
        for _ in range(20):
            _enqueue(factory, job_type=job_type)

        result = drain(factory, max_jobs=20, budget_seconds=0.3, lease_seconds=60)

        assert result.budget_exhausted
        assert result.claimed < 20

    def test_lease_shorter_than_budget_is_rejected(self, factory: sessionmaker[Session]) -> None:
        """Otherwise a job is reclaimed while it is still running, and the same
        work happens twice with no error anywhere."""
        with pytest.raises(ValueError, match="must exceed"):
            drain(factory, max_jobs=1, budget_seconds=60, lease_seconds=30)


class TestFailureHandling:
    def test_a_failing_handler_does_not_stop_the_drain(
        self, factory: sessionmaker[Session], temp_handler: Any
    ) -> None:
        def boom(session: Session, payload: dict[str, Any]) -> None:
            raise RuntimeError("handler exploded")

        bad = temp_handler("bad", boom)
        _enqueue(factory, job_type=bad)
        for _ in range(3):
            _enqueue(factory)

        result = drain(factory, max_jobs=10, budget_seconds=10, lease_seconds=60)

        assert result.failed == 1
        assert result.succeeded == 3

    def test_failure_is_recorded_with_the_error(
        self, factory: sessionmaker[Session], temp_handler: Any
    ) -> None:
        def boom(session: Session, payload: dict[str, Any]) -> None:
            raise RuntimeError("handler exploded")

        bad = temp_handler("bad2", boom)
        _enqueue(factory, job_type=bad, max_attempts=3)

        drain(factory, max_jobs=1, budget_seconds=10, lease_seconds=60)

        with factory() as session:
            job = session.scalars(text("SELECT id FROM jobs")).one()
            reloaded = session.get(Job, job)
            assert reloaded is not None
            assert reloaded.status is JobStatus.PENDING
            assert "handler exploded" in (reloaded.last_error or "")
            assert reloaded.attempts == 1

    def test_partial_handler_writes_are_rolled_back(
        self, factory: sessionmaker[Session], temp_handler: Any
    ) -> None:
        """A handler that writes and then fails must leave nothing behind."""

        def write_then_fail(session: Session, payload: dict[str, Any]) -> None:
            JobQueue(session).enqueue(job_type=NOOP, payload={"orphan": True})
            raise RuntimeError("after the write")

        bad = temp_handler("write_then_fail", write_then_fail)
        _enqueue(factory, job_type=bad)

        drain(factory, max_jobs=1, budget_seconds=10, lease_seconds=60)

        with factory() as session:
            orphans = session.execute(
                text("SELECT count(*) FROM jobs WHERE payload ? 'orphan'")
            ).scalar_one()

            assert orphans == 0

    def test_the_attempt_survives_a_handler_crash(
        self, factory: sessionmaker[Session], temp_handler: Any
    ) -> None:
        """The reason the claim is committed before the handler runs.

        If the rollback took the attempt counter with it, a job that always
        crashes would retry forever without exhausting its attempts.
        """

        def boom(session: Session, payload: dict[str, Any]) -> None:
            raise RuntimeError("nope")

        bad = temp_handler("always_crashes", boom)
        _enqueue(factory, job_type=bad, max_attempts=2)

        drain(factory, max_jobs=1, budget_seconds=10, lease_seconds=60)

        with factory() as session:
            attempts = session.execute(text("SELECT attempts FROM jobs")).scalar_one()

            assert attempts == 1

    def test_unknown_job_type_fails_the_job_not_the_drain(
        self, factory: sessionmaker[Session]
    ) -> None:
        """A stale job type left by an earlier deploy must not take down the
        whole drain."""
        _enqueue(factory, job_type="no_such_handler")
        _enqueue(factory)

        result = drain(factory, max_jobs=10, budget_seconds=10, lease_seconds=60)

        assert result.failed == 1
        assert result.succeeded == 1

        with factory() as session:
            error = session.execute(
                text("SELECT last_error FROM jobs WHERE job_type = 'no_such_handler'")
            ).scalar_one()

            assert "no handler registered" in error


class TestSuccessPath:
    def test_completed_jobs_are_not_reprocessed(self, factory: sessionmaker[Session]) -> None:
        _enqueue(factory)

        first = drain(factory, max_jobs=10, budget_seconds=10, lease_seconds=60)
        second = drain(factory, max_jobs=10, budget_seconds=10, lease_seconds=60)

        assert first.succeeded == 1
        assert second.idle

    def test_lease_is_released_on_success(self, factory: sessionmaker[Session]) -> None:
        _enqueue(factory)
        drain(factory, max_jobs=1, budget_seconds=10, lease_seconds=60)

        with factory() as session:
            row = session.execute(
                text("SELECT status, claimed_at, lease_expires_at FROM jobs")
            ).one()

            assert row.status == "succeeded"
            assert row.claimed_at is None
            assert row.lease_expires_at is None

    def test_a_job_enqueued_by_a_handler_is_claimed_in_the_same_drain_call(
        self, factory: sessionmaker[Session], temp_handler: Any
    ) -> None:
        """The property chained pipelines (M2's transcribe -> correct ->
        extract, M3's backfill batches) depend on: a handler's own enqueue
        must not have to wait for the next cron tick. drain()'s claim loop
        re-queries the jobs table fresh on every iteration, so a job
        committed by the previous iteration's handler is visible to the
        next `claim()` call within the same drain() invocation."""

        def link_one(session: Session, payload: dict[str, Any]) -> None:
            depth = payload["depth"]
            if depth < 3:
                JobQueue(session).enqueue(job_type="chain", payload={"depth": depth + 1})

        job_type = temp_handler("chain", link_one)
        _enqueue(factory, job_type=job_type, payload={"depth": 0})

        result = drain(factory, max_jobs=10, budget_seconds=10, lease_seconds=60)

        assert result.claimed == 4  # depth 0, 1, 2, 3
        assert result.succeeded == 4
        assert not result.budget_exhausted

    def test_a_chain_longer_than_max_jobs_stops_at_the_cap(
        self, factory: sessionmaker[Session], temp_handler: Any
    ) -> None:
        """The other half of the same guarantee: re-querying within the
        budget must still respect max_jobs, or one runaway chain could
        starve every other job type sharing the queue."""

        def link_forever(session: Session, payload: dict[str, Any]) -> None:
            JobQueue(session).enqueue(job_type="chain2", payload={})

        job_type = temp_handler("chain2", link_forever)
        _enqueue(factory, job_type=job_type)

        result = drain(factory, max_jobs=5, budget_seconds=10, lease_seconds=60)

        assert result.claimed == 5


class TestJobIdContext:
    """current_job_id (M5.5a) — set for the duration of a handler call so
    code running underneath it (the LLM instrumentation wrapper) can
    attribute what it records, without the handler signature knowing about
    it."""

    def test_current_job_id_is_set_for_the_duration_of_the_handler(
        self, factory: sessionmaker[Session], temp_handler: Any
    ) -> None:
        seen: list[uuid.UUID | None] = []

        def record_job_id(session: Session, payload: dict[str, Any]) -> None:
            seen.append(current_job_id.get())

        job_type = temp_handler("record_job_id", record_job_id)
        _enqueue(factory, job_type=job_type)

        drain(factory, max_jobs=1, budget_seconds=10, lease_seconds=60)

        with factory() as session:
            job_id = session.execute(text("SELECT id FROM jobs")).scalar_one()

        assert seen == [job_id]

    def test_current_job_id_is_reset_after_the_handler_succeeds(
        self, factory: sessionmaker[Session]
    ) -> None:
        _enqueue(factory)

        drain(factory, max_jobs=1, budget_seconds=10, lease_seconds=60)

        assert current_job_id.get() is None

    def test_current_job_id_is_reset_even_if_the_handler_fails(
        self, factory: sessionmaker[Session], temp_handler: Any
    ) -> None:
        def boom(session: Session, payload: dict[str, Any]) -> None:
            raise RuntimeError("boom")

        job_type = temp_handler("boom_for_context", boom)
        _enqueue(factory, job_type=job_type)

        drain(factory, max_jobs=1, budget_seconds=10, lease_seconds=60)

        assert current_job_id.get() is None
