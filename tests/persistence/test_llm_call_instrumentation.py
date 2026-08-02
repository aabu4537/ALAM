"""InstrumentedLLMProvider: every ``.complete()`` call made through
``get_llm_provider()`` is recorded to ``llm_calls`` (M5.5a) — from the
resolver, not from any individual call site.

Uses the real ``get_llm_provider()`` resolver rather than constructing
``InstrumentedLLMProvider`` directly, since the thing under test is that the
choke point wraps correctly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from alam.ai.providers import get_llm_provider
from alam.config.settings import get_settings
from alam.jobs.context import current_job_id
from alam.persistence import session as session_module
from alam.persistence.models.job import Job
from alam.persistence.models.llm_call import LLMCall

if TYPE_CHECKING:
    import uuid
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _redirect_global_engine_to_the_test_database(
    monkeypatch: pytest.MonkeyPatch, migrated_engine: Engine, database_url: str
) -> Iterator[None]:
    """``InstrumentedLLMProvider`` can't receive the test's ``session``
    fixture — ``LLMProvider.complete()`` has no session parameter, by
    design (M5.5a doesn't widen the Protocol). It opens its own via
    ``persistence.session``, which otherwise resolves ``ALAM_DATABASE_URL``'s
    default (a local dev database, not this migrated test one).
    """
    monkeypatch.setenv("ALAM_DATABASE_URL", database_url)
    get_settings.cache_clear()
    session_module.reset_engine()
    yield
    session_module.reset_engine()
    get_settings.cache_clear()


def _committed_job() -> uuid.UUID:
    """A ``Job`` row visible outside the test's own (savepoint-scoped,
    never-committed) ``session`` fixture — ``llm_calls.job_id`` has a real FK
    to ``jobs.id``, so referencing an uncommitted row would fail exactly the
    way a real dangling reference should."""
    with session_module.get_session_factory()() as session:
        job = Job(job_type="noop", payload={})
        session.add(job)
        session.commit()
        return job.id


class TestInstrumentedLLMProvider:
    def test_a_completion_is_recorded(self, session: Session) -> None:
        llm = get_llm_provider()
        result = llm.complete("hello", prompt_version_id="instrumentation-test-v1")

        row = session.execute(
            select(LLMCall).where(LLMCall.prompt_version_id == "instrumentation-test-v1")
        ).scalar_one()
        assert row.model == result.model
        assert row.input_tokens == result.input_tokens
        assert row.output_tokens == result.output_tokens
        assert row.latency_ms >= 0
        assert row.provider == "fake"

    def test_the_completion_is_still_returned_to_the_caller(self, session: Session) -> None:
        """Instrumentation observes the call; it must not change what the
        caller gets back."""
        result = get_llm_provider().complete("hello", prompt_version_id="passthrough-test-v1")

        assert result.text

    def test_call_site_identifies_the_caller_not_the_wrapper(self, session: Session) -> None:
        get_llm_provider().complete("x", prompt_version_id="call-site-test-v1")

        row = session.execute(
            select(LLMCall).where(LLMCall.prompt_version_id == "call-site-test-v1")
        ).scalar_one()
        assert row.call_site == (
            "tests.persistence.test_llm_call_instrumentation"
            ".test_call_site_identifies_the_caller_not_the_wrapper"
        )
        assert "alam.ai.providers.instrumentation" not in row.call_site

    def test_no_job_running_records_a_null_job_id(self, session: Session) -> None:
        assert current_job_id.get() is None

        get_llm_provider().complete("x", prompt_version_id="no-job-test-v1")

        row = session.execute(
            select(LLMCall).where(LLMCall.prompt_version_id == "no-job-test-v1")
        ).scalar_one()
        assert row.job_id is None

    def test_job_id_is_picked_up_from_the_contextvar(self, session: Session) -> None:
        job_id = _committed_job()
        token = current_job_id.set(job_id)
        try:
            get_llm_provider().complete("x", prompt_version_id="job-id-test-v1")
        finally:
            current_job_id.reset(token)

        row = session.execute(
            select(LLMCall).where(LLMCall.prompt_version_id == "job-id-test-v1")
        ).scalar_one()
        assert row.job_id == job_id

    def test_multiple_calls_each_get_their_own_row(self, session: Session) -> None:
        llm = get_llm_provider()
        llm.complete("first", prompt_version_id="multi-test-v1")
        llm.complete("second", prompt_version_id="multi-test-v1")

        rows = (
            session.execute(select(LLMCall).where(LLMCall.prompt_version_id == "multi-test-v1"))
            .scalars()
            .all()
        )
        assert len(rows) == 2
