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


def test_allow_paid_providers_defaults_to_false() -> None:
    """The $0 constraint (M5.5a task 1) is enforced by this default, not by
    memory. This test exists specifically so that a future edit flipping it
    breaks CI loudly rather than quietly opening a paid path."""
    assert Settings().allow_paid_providers is False


def test_owner_password_defaults_to_unset() -> None:
    """Fail-closed by default (M7 session 2, ADR-0017), same reasoning as
    ``allow_paid_providers`` — a future edit accidentally hardcoding a
    default password breaks this loudly rather than quietly opening every
    owner-scoped route."""
    assert Settings().owner_password is None


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
        # Not a valid LLM vendor name — "voyage" and "openai" are real
        # vendors, just not for this provider kind (M5.5a).
        ("ALAM_LLM_PROVIDER", "openai"),
        ("ALAM_LLM_PROVIDER", "voyage"),
        ("ALAM_EMBEDDING_PROVIDER", "anthropic"),
        ("ALAM_STT_PROVIDER", "anthropic"),
    ],
)
def test_invalid_values_are_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    """A bad provider name should fail at startup, not at first call."""
    monkeypatch.setenv(field, value)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    ("provider_field", "provider_value", "missing_key_env_var"),
    [
        ("ALAM_LLM_PROVIDER", "anthropic", "ALAM_ANTHROPIC_API_KEY"),
        ("ALAM_EMBEDDING_PROVIDER", "voyage", "ALAM_VOYAGE_API_KEY"),
        ("ALAM_STT_PROVIDER", "openai", "ALAM_OPENAI_API_KEY"),
    ],
)
def test_a_real_provider_without_its_credential_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch,
    provider_field: str,
    provider_value: str,
    missing_key_env_var: str,
) -> None:
    """Selecting a real provider without its API key should fail here, not
    at the first request that happens to call it (M5.5a)."""
    monkeypatch.setenv(provider_field, provider_value)

    with pytest.raises(ValidationError, match=missing_key_env_var):
        Settings()


@pytest.mark.parametrize(
    ("provider_field", "provider_value", "key_env_var"),
    [
        ("ALAM_LLM_PROVIDER", "anthropic", "ALAM_ANTHROPIC_API_KEY"),
        ("ALAM_EMBEDDING_PROVIDER", "voyage", "ALAM_VOYAGE_API_KEY"),
        ("ALAM_STT_PROVIDER", "openai", "ALAM_OPENAI_API_KEY"),
    ],
)
def test_a_real_provider_with_its_credential_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
    provider_field: str,
    provider_value: str,
    key_env_var: str,
) -> None:
    monkeypatch.setenv(provider_field, provider_value)
    monkeypatch.setenv(key_env_var, "sk-test-not-a-real-key")

    Settings()  # must not raise


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
