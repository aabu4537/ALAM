"""Engine and session factory.

Sync SQLAlchemy, deliberately. The worker loop in ``jobs/`` is a blocking poll
against ``FOR UPDATE SKIP LOCKED`` and is naturally synchronous, and FastAPI
runs ``def`` endpoints in a threadpool. Going async would mean maintaining two
engines and two session styles for a single-user system that will never be
concurrency-bound. Revisit if a real workload disagrees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from alam.config.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

    from alam.config.settings import Settings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def engine_options(settings: Settings) -> dict[str, Any]:
    """Engine keyword arguments for the configured connection mode.

    Split out as a pure function because neither mode fails loudly when it is
    wrong, so the choice is worth asserting directly rather than inferring from
    a constructed engine.
    """
    if not settings.database_use_transaction_pooler:
        return {"pool_pre_ping": True}

    # Supabase's transaction pooler (port 6543) hands out a different backend
    # connection per transaction. Two consequences, both of which fail
    # confusingly rather than obviously:
    #
    # NullPool — the application must not hold connections, because the pooler
    # *is* the pool. A client-side pool stacked on it exhausts the server's
    # slots while appearing idle.
    #
    # prepare_threshold=None — psycopg3 would otherwise cache prepared
    # statements against a connection the pooler swaps out from under it,
    # producing intermittent "prepared statement does not exist" errors under
    # load and none at all in testing.
    return {
        "poolclass": NullPool,
        "connect_args": {"prepare_threshold": None},
    }


def get_engine() -> Engine:
    """Process-wide engine, created on first use.

    Two shapes, chosen by configuration rather than hardcoded, because the
    right answer differs between a long-lived process and a serverless
    invocation (ADR-0007).
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(settings.database_url, future=True, **engine_options(settings))
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _session_factory


def session_scope() -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on exception."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Drop the cached engine and factory. For tests and settings changes."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
