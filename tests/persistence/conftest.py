"""Database fixtures.

Every test here runs inside a transaction that is rolled back afterwards, so the
schema is migrated once per session and no test can see another's rows.

Skips cleanly when ``ALAM_TEST_DATABASE_URL`` is unset, so ``pytest`` still
works on a machine with no Postgres. That skip is a real gap, not a pass — CI
always sets the variable, so these assertions run on every push.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tests.conftest import REQUIRE_DB_TESTS_ENV, TEST_DATABASE_URL_ENV

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

pytestmark = pytest.mark.db


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get(TEST_DATABASE_URL_ENV)
    if url:
        return url

    if os.environ.get(REQUIRE_DB_TESTS_ENV) == "1":
        # CI sets this. A broken service container would otherwise produce a
        # green run in which none of the schema assertions executed, which is
        # indistinguishable from a passing one.
        pytest.fail(
            f"{REQUIRE_DB_TESTS_ENV}=1 but {TEST_DATABASE_URL_ENV} is unset — "
            "the database tests would have been skipped silently"
        )

    pytest.skip(f"{TEST_DATABASE_URL_ENV} is not set; skipping database tests")


@pytest.fixture(scope="session")
def migrated_engine(database_url: str) -> Iterator[Engine]:
    """Apply migrations to a clean schema, then hand back the engine.

    Runs the real Alembic migration rather than ``metadata.create_all`` so the
    tests exercise what actually ships. ``create_all`` would silently produce a
    non-deferrable unique constraint and the ADR-0006 renumbering test would
    pass against a schema that does not exist in production.
    """
    engine = create_engine(database_url, future=True)

    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

    yield engine

    engine.dispose()


@pytest.fixture
def session(migrated_engine: Engine) -> Iterator[Session]:
    """A session whose work is always rolled back.

    ``join_transaction_mode="create_savepoint"`` runs the session inside a
    SAVEPOINT rather than directly on the outer transaction. Tests that
    deliberately provoke an ``IntegrityError`` cause SQLAlchemy to roll the
    session back, and without the savepoint that also unwinds the fixture's
    transaction — teardown then fails with "transaction already deassociated
    from connection" and leaks the connection.
    """
    connection = migrated_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()
