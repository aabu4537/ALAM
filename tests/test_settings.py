from __future__ import annotations

import pytest
from pydantic import ValidationError

from alam.config.settings import Settings


def test_defaults_are_usable_without_any_environment() -> None:
    settings = Settings(_env_file=None)

    assert settings.env == "local"
    assert settings.job_max_attempts == 5


def test_env_prefix_is_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALAM_ENV", "production")
    monkeypatch.setenv("ALAM_JOB_MAX_ATTEMPTS", "9")

    settings = Settings(_env_file=None)

    assert settings.env == "production"
    assert settings.job_max_attempts == 9


def test_settings_are_immutable() -> None:
    settings = Settings(_env_file=None)

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
        Settings(_env_file=None)
