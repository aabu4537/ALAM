from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from alam.api.dependencies import require_owner_session
from alam.api.main import create_app
from alam.config.settings import Settings, get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

TEST_DATABASE_URL_ENV = "ALAM_TEST_DATABASE_URL"
REQUIRE_DB_TESTS_ENV = "ALAM_REQUIRE_DB_TESTS"

_ENV_KEYS_EXEMPT_FROM_ISOLATION = frozenset({TEST_DATABASE_URL_ENV, REQUIRE_DB_TESTS_ENV})
"""Names the isolation fixture must not strip.

These configure the test run itself rather than the application — one points at
the throwaway test database, the other turns its absence into a failure. Both
are read by fixtures, so clearing them would break the database tests outright.
"""


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run every test against a known-empty configuration environment.

    Two separate leaks are closed here, and both are silent:

    ``_env_file=None`` stops pydantic-settings reading ``.env`` but does *not*
    stop it reading ``os.environ``. CI exports ``ALAM_ENV=ci``, so a test
    asserting on defaults saw ``ci`` and failed there while passing on any
    machine whose shell happened to be clean.

    The ``.env`` file is the mirror image: absent in CI, usually present
    locally, so a developer's real database URL could quietly satisfy a test
    that CI would fail.

    Tests that want a value set it explicitly with ``monkeypatch.setenv``.
    """
    for key in [k for k in os.environ if k.startswith("ALAM_")]:
        if key in _ENV_KEYS_EXEMPT_FROM_ISOLATION:
            continue
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setitem(Settings.model_config, "env_file", None)

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """``require_owner_session`` (M7 session 2, ADR-0017) is overridden to a
    no-op here — this fixture exists to test everything *other than* the
    auth gate itself conveniently, the same reason it already stands up a
    plain app rather than requiring every caller to configure one. The
    gate's own behavior is tested directly: ``tests/test_auth_router.py``
    (login/logout) and ``tests/test_owner_session_gating.py``
    (previously-open routes now require a real session) both build their
    own ``TestClient`` without this override.
    """
    app = create_app()
    app.dependency_overrides[require_owner_session] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
