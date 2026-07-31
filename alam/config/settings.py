"""Typed application settings.

Every value is read from the environment with an ``ALAM_`` prefix. There is no
layered config file system and no runtime mutation — settings are resolved once
at import and treated as immutable.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "ci", "staging", "production"]
LogFormat = Literal["json", "console"]
ProviderKind = Literal["fake"]
"""M0 ships fakes only. Real provider names join this union when they exist —
see CLAUDE.md rule 8."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ALAM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    # --- Application ---
    env: Environment = "local"
    debug: bool = False
    log_level: str = "INFO"
    log_format: LogFormat = "json"

    # --- Database ---
    database_url: str = "postgresql+psycopg://alam:alam@localhost:5432/alam"

    database_use_transaction_pooler: bool = False
    """Set when connecting through Supabase's transaction pooler (port 6543).

    Switches the engine to NullPool with prepared statements disabled. Wrong in
    either direction: a client-side pool on top of the pooler exhausts server
    slots, and disabling pooling for a long-lived worker throws away every
    connection. See ADR-0007 and persistence/session.py.
    """

    # --- Job queue ---
    worker_poll_interval_seconds: float = Field(default=1.0, gt=0)
    job_max_attempts: int = Field(default=5, ge=1)

    drain_max_jobs: int = Field(default=10, ge=1)
    drain_budget_seconds: float = Field(default=25.0, gt=0)
    """Wall-clock ceiling for one drain.

    Must stay well under the platform's function limit — 300s on Vercel Hobby
    with Fluid Compute — so an invocation returns rather than being killed
    mid-job (ADR-0007).
    """

    job_lease_seconds: float = Field(default=120.0, gt=0)
    """How long a claim is held before another worker may take it back.

    Must exceed ``drain_budget_seconds``, or a job can be stolen from a worker
    still running it. Enforced below.
    """

    drain_secret: SecretStr | None = None
    """Bearer token for POST /internal/jobs/drain.

    The endpoint is public. Unset means the endpoint refuses all callers rather
    than accepting them.
    """

    demo_seed_secret: SecretStr | None = None
    """Bearer token for POST /internal/demo/seed.

    A separate secret from ``drain_secret`` — draining the queue and creating
    demo data are different operations with different blast radii, and one
    leaking should not imply the other is exposed too. Same fail-closed
    default as the drain secret.
    """

    # --- Providers ---
    llm_provider: ProviderKind = "fake"
    embedding_provider: ProviderKind = "fake"
    stt_provider: ProviderKind = "fake"

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, value: str) -> str:
        """Supabase's dashboard hands out bare ``postgresql://`` connection
        strings, which makes SQLAlchemy default to psycopg2 — a driver this
        project doesn't install, since everything is written against psycopg3.
        Rewriting the scheme here means pasting Supabase's string verbatim
        just works, instead of failing at connect time with a driver import
        error that has nothing to do with the actual mistake.
        """
        for bare_scheme in ("postgresql://", "postgres://"):
            if value.startswith(bare_scheme):
                return "postgresql+psycopg://" + value[len(bare_scheme) :]
        return value

    @model_validator(mode="after")
    def _lease_must_outlive_the_drain(self) -> Settings:
        """Catch a misconfiguration that would otherwise look like flakiness.

        If the lease is shorter than the drain budget, a long-running job has
        its lease expire while it is still being worked on, a second worker
        reclaims it, and the job runs twice. That surfaces as rare duplicate
        side effects, which is close to impossible to diagnose after the fact.
        """
        if self.job_lease_seconds <= self.drain_budget_seconds:
            raise ValueError(
                f"job_lease_seconds ({self.job_lease_seconds}) must exceed "
                f"drain_budget_seconds ({self.drain_budget_seconds}), or a job "
                f"can be reclaimed while it is still running"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached so that FastAPI dependencies and the worker entrypoint observe the
    same instance. Call ``get_settings.cache_clear()`` in tests that need to
    rebuild it under a patched environment.
    """
    return Settings()
