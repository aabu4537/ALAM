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
LLMProviderKind = Literal["fake", "anthropic"]
EmbeddingProviderKind = Literal["fake", "voyage"]
SttProviderKind = Literal["fake", "openai"]
"""One union per provider kind, not one shared union (M5.5a) — the three
providers have disjoint real vendors, and a shared ``ProviderKind`` would let
``ALAM_LLM_PROVIDER=voyage`` type-check as valid when it can never resolve to
anything. CLAUDE.md rule 8: provider access goes through a Protocol either
way, so this only constrains which vendor name is even legal in config."""

PAID_PROVIDER_KINDS: frozenset[str] = frozenset({"anthropic", "voyage", "openai"})
"""Every provider kind that can spend real money (M5.5a task 1). Checked
against whichever of ``llm_provider`` / ``embedding_provider`` / ``stt_provider``
is being resolved — the names don't overlap across the three, so one set
covers all of them. Gated by ``allow_paid_providers``, independent of local
kinds added later (ollama, local, faster_whisper), which never appear here."""


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

    embedding_backfill_batch_size: int = Field(default=50, ge=1)
    """Memories processed per backfill job invocation (ADR-0008). Bounds one
    invocation's work so it fits comfortably inside a single drain, not the
    reason it can be interrupted safely — the job's own re-enqueue-with-
    cursor design is what makes a kill mid-run resumable. This just tunes
    how many batches that takes.
    """

    # --- Profile (M4) ---
    consolidation_batch_size: int = Field(default=20, ge=1)
    """Memories weighed against the profile per consolidation job invocation
    (ADR-0001). One LLM call per batch, so this also bounds prompt size —
    L3 facts are loaded wholesale into the same call, and a personal
    library's weekly reflection volume is small, but the cap keeps a large
    first-run backlog from producing one unbounded prompt.
    """

    consolidation_initial_confidence: float = Field(default=0.5, ge=0, le=1)
    """A single observation is moderate evidence, not proof — reinforcement
    (domain.preference_decay.reinforce) is what moves confidence toward 1 as
    more observations accumulate."""

    # --- Predictions (M5) ---
    prediction_resolution_window: int = Field(default=10, ge=1)
    """Ordinals of progress a prediction waits before its evidence window is
    scanned (docs/milestones.md, M5). Captured onto each ``predictions`` row
    at creation time, not re-read at resolution time, so a later change to
    this default doesn't retroactively move an already-pending prediction's
    goalposts.
    """

    # --- Retrieval (M3) ---
    retrieval_candidate_limit: int = Field(default=20, ge=1)
    """Rows fetched per branch (vector, full-text) before RRF fusion narrows
    to the caller's requested limit. Wider than the final limit so a memory
    that ranks well on only one axis still reaches the fusion step instead of
    being cut before fusion ever sees it.
    """

    # --- Providers ---
    llm_provider: LLMProviderKind = "fake"
    embedding_provider: EmbeddingProviderKind = "fake"
    stt_provider: SttProviderKind = "fake"

    allow_paid_providers: bool = False
    """Fail-closed gate on every kind in ``PAID_PROVIDER_KINDS`` (M5.5a task
    1). Selecting ``anthropic``/``voyage``/``openai`` in the fields above is
    not enough by itself to reach a paid API — this must also be true. The
    $0 constraint is enforced here, in code, rather than relied on as
    something a person remembers to check before setting a provider kind.
    Default is False; ``tests/test_settings.py`` asserts that specifically,
    so a future edit to this default breaks CI loudly rather than silently
    opening the gate.
    """

    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-sonnet-4-5-20250929"
    """Verify this against Anthropic's current model list before relying on
    it — model ids are retired on a schedule this file cannot track for you.
    """

    voyage_api_key: SecretStr | None = None
    voyage_model: str = "voyage-3"

    openai_api_key: SecretStr | None = None
    """Used only for the Whisper STT endpoint (M5.5a) — not an LLM or
    embedding vendor here. A separate ``openai`` LLM/embedding backend is
    something to add later, not implied by this key's presence."""

    whisper_model: str = "whisper-1"

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

    @model_validator(mode="after")
    def _real_providers_require_credentials(self) -> Settings:
        """A provider selected without its credential should fail at
        startup, the same way an unknown provider name already does —
        not at the first request that happens to call it (M5.5a)."""
        missing = []
        if self.llm_provider == "anthropic" and self.anthropic_api_key is None:
            missing.append("ALAM_ANTHROPIC_API_KEY")
        if self.embedding_provider == "voyage" and self.voyage_api_key is None:
            missing.append("ALAM_VOYAGE_API_KEY")
        if self.stt_provider == "openai" and self.openai_api_key is None:
            missing.append("ALAM_OPENAI_API_KEY")

        if missing:
            raise ValueError(
                "missing required credentials for the configured provider(s): " + ", ".join(missing)
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
