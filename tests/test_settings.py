from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from alam.config.settings import Settings
from tests.conftest import _ENV_KEYS_EXEMPT_FROM_ISOLATION


def test_the_environment_is_isolated() -> None:
    """Guards the fixture in conftest, not the code under test.

    Without this, an ambient ``ALAM_*`` variable silently changes what the
    tests below are asserting — which is how CI and local disagreed.
    """
    leaked = [
        k for k in os.environ if k.startswith("ALAM_") and k not in _ENV_KEYS_EXEMPT_FROM_ISOLATION
    ]

    assert leaked == []


def test_defaults_are_usable_without_any_environment() -> None:
    settings = Settings()

    assert settings.env == "local"
    assert settings.job_max_attempts == 5


def test_env_prefix_is_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALAM_ENV", "production")
    monkeypatch.setenv("ALAM_JOB_MAX_ATTEMPTS", "9")

    settings = Settings()

    assert settings.env == "production"
    assert settings.job_max_attempts == 9


def test_settings_are_immutable() -> None:
    settings = Settings()

    with pytest.raises(ValidationError):
        settings.env = "production"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ALAM_ENV", "nonsense"),
        ("ALAM_WORKER_POLL_INTERVAL_SECONDS", "0"),
        ("ALAM_JOB_MAX_ATTEMPTS", "0"),
        ("ALAM_LLM_PROVIDER", "openai"),
    ],
)
def test_invalid_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    """A bad provider name should fail at startup, not at first call.

    ``openai`` is rejected because M0 ships fakes only — CLAUDE.md rule 8.
    """
    monkeypatch.setenv(field, value)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (
            "postgresql://user:pw@host:6543/db",
            "postgresql+psycopg://user:pw@host:6543/db",
        ),
        (
            "postgres://user:pw@host:6543/db",
            "postgresql+psycopg://user:pw@host:6543/db",
        ),
        (
            "postgresql+psycopg://user:pw@host:6543/db",
            "postgresql+psycopg://user:pw@host:6543/db",
        ),
    ],
)
def test_bare_postgres_schemes_are_rewritten_to_psycopg(
    monkeypatch: pytest.MonkeyPatch, given: str, expected: str
) -> None:
    """Supabase's dashboard hands out bare ``postgresql://`` strings, which
    default to a psycopg2 driver this project never installs — the project is
    written against psycopg3 throughout. Pasting Supabase's string verbatim
    must work rather than fail with an unrelated driver-import error.
    """
    monkeypatch.setenv("ALAM_DATABASE_URL", given)

    assert Settings().database_url == expected
