"""Engine and session factory.

Sync SQLAlchemy, deliberately. The worker loop in ``jobs/`` is a blocking poll
against ``FOR UPDATE SKIP LOCKED`` and is naturally synchronous, and FastAPI
runs ``def`` endpoints in a threadpool. Going async would mean maintaining two
engines and two session styles for a single-user system that will never be
concurrency-bound. Revisit if a real workload disagrees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from alam.config.settings import get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Process-wide engine, created on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
            future=True,
        )
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
