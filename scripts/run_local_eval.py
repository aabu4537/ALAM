"""Real (local) eval baseline runner (M5.5a task 3).

Not part of the application or the test suite — run manually, once, to
produce the numbers in docs/eval/baseline-local-providers.md. Exercises the
exact same eval harness CI runs against FakeLLM
(tests/test_eval_extraction.py, tests/persistence/test_eval_retrieval.py,
tests/persistence/test_eval_spoiler.py) but against real local providers
(Ollama, sentence-transformers) — something the test suite itself can never
do (rule 8: zero network calls in tests). Also runs journey_summary_eval
with the same real LLM, closing the one gap the M5.5a run left open: a
real, not canned, synthesis_leakage_rate for Layer 3
(alam/ai/synthesis/leak_check.py).

Usage:
    ALAM_TEST_DATABASE_URL=postgresql+psycopg://alam:alam@localhost:5432/alam_test \
        uv run python scripts/run_local_eval.py

Requires a running Ollama server with ALAM_OLLAMA_MODEL already pulled.
Points ALAM_DATABASE_URL at the same throwaway test database the eval
tests use — every case seeds its own fresh owner/book (see
eval/seeding.py), so this is safe to run against it directly and safe to
leave the rows behind; the next `pytest` run drops and recreates the
schema before anything reads it again.
"""

from __future__ import annotations

import datetime as dt
import os
import time

os.environ.setdefault("ALAM_LLM_PROVIDER", "ollama")
os.environ.setdefault("ALAM_EMBEDDING_PROVIDER", "local")
os.environ.setdefault("ALAM_OLLAMA_MODEL", "llama3.2:1b")
os.environ.setdefault("ALAM_LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
os.environ.setdefault(
    "ALAM_DATABASE_URL",
    os.environ.get(
        "ALAM_TEST_DATABASE_URL", "postgresql+psycopg://alam:alam@localhost:5432/alam_test"
    ),
)
os.environ.setdefault("ALAM_LOG_FORMAT", "console")

from sqlalchemy import delete, select

from alam.ai.providers import get_llm_provider
from alam.config.settings import get_settings
from alam.eval.extraction_eval import EXTRACTION_CASES, run_extraction_eval
from alam.eval.journey_summary_eval import run_journey_summary_spoiler_eval
from alam.eval.retrieval_eval import run_retrieval_eval
from alam.eval.spoiler_eval import run_spoiler_eval
from alam.persistence import session as session_module
from alam.persistence.models.llm_call import LLMCall
from alam.persistence.models.user import User


def main() -> None:
    get_settings.cache_clear()
    session_module.reset_engine()
    settings = get_settings()

    print(f"llm_provider={settings.llm_provider} model={settings.ollama_model}")
    print(
        f"embedding_provider={settings.embedding_provider} model={settings.local_embedding_model}"
    )
    print(f"database={settings.database_url}")
    print()

    started_at = dt.datetime.now(dt.UTC)
    session_factory = session_module.get_session_factory()

    print("=== extraction ===")
    llm = get_llm_provider()
    t0 = time.perf_counter()
    extraction_report = run_extraction_eval(llm, cases=EXTRACTION_CASES)
    elapsed = time.perf_counter() - t0
    print(f"accuracy={extraction_report.accuracy:.3f} elapsed={elapsed:.1f}s")
    for er in extraction_report.results:
        status = "OK  " if er.correct else "FAIL"
        print(
            f"  [{status}] {er.label}: expected={er.expected_types} "
            f"actual={er.actual_types} error={er.error}"
        )
    print()

    print("=== retrieval ===")
    with session_factory() as session:
        t0 = time.perf_counter()
        retrieval_report = run_retrieval_eval(session)
        elapsed = time.perf_counter() - t0
        session.commit()
    print(f"recall@{retrieval_report.k}={retrieval_report.recall_at_k:.3f} elapsed={elapsed:.1f}s")
    for rr in retrieval_report.results:
        print(f"  {rr.label}: recall={rr.recall:.2f} missing={rr.missing_labels}")
    print()

    print("=== spoiler ===")
    with session_factory() as session:
        t0 = time.perf_counter()
        spoiler_report = run_spoiler_eval(session)
        elapsed = time.perf_counter() - t0
        session.commit()
    print(f"leakage_rate={spoiler_report.leakage_rate:.3f} elapsed={elapsed:.1f}s")
    for sr in spoiler_report.results:
        marker = "LEAKED" if sr.leaked else "clean "
        print(f"  [{marker}] {sr.label}: {sr.leaked_labels}")
    print()

    print("=== journey summary (Layer 3) ===")
    # Unlike the sections above, this one goes through the real HTTP path
    # (reader_context_dependency -> UserRepository.get_owner()), which
    # assumes exactly one non-demo user. Each pytest run gets that for free
    # via per-test transaction rollback (tests/persistence/conftest.py); this
    # script commits after every section against one shared connection, so
    # the extraction/retrieval/spoiler owners above are still there unless
    # cleared first. Cascades (ondelete="CASCADE" on media_items.user_id)
    # take their seeded books/sessions/memories with them — safe, since
    # those sections' reports were already printed above.
    with session_factory() as session:
        session.execute(delete(User).where(User.is_demo.is_(False)))
        session.commit()

    with session_factory() as session:
        t0 = time.perf_counter()
        journey_report = run_journey_summary_spoiler_eval(session, llm=llm)
        elapsed = time.perf_counter() - t0
        session.commit()
    print(f"leakage_rate={journey_report.leakage_rate:.3f} elapsed={elapsed:.1f}s")
    for jr in journey_report.results:
        marker = "LEAKED" if jr.leaked else "clean "
        print(f"  [{marker}] {jr.label}: {jr.leaked_labels}")
    print()

    print("=== llm_calls recorded this run ===")
    with session_factory() as session:
        calls = session.scalars(
            select(LLMCall).where(LLMCall.created_at >= started_at).order_by(LLMCall.created_at)
        ).all()
        total_input = sum(c.input_tokens for c in calls)
        total_output = sum(c.output_tokens for c in calls)
        print(f"{len(calls)} calls, {total_input} input tokens, {total_output} output tokens")
        for c in calls:
            print(
                f"  {c.call_site} model={c.model} prompt_version={c.prompt_version_id} "
                f"in={c.input_tokens} out={c.output_tokens} latency_ms={c.latency_ms:.0f}"
            )


if __name__ == "__main__":
    main()
