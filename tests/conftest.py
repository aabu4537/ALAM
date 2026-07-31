from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from alam.api.main import create_app
from alam.config.settings import Settings, get_settings

if TYPE_CHECKING:
    from collections.abc import Iterator


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
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setitem(Settings.model_config, "env_file", None)

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c
