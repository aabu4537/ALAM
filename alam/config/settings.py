"""Typed application settings.

Every value is read from the environment with an ``ALAM_`` prefix. There is no
layered config file system and no runtime mutation — settings are resolved once
at import and treated as immutable.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
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

    # --- Job queue ---
    worker_poll_interval_seconds: float = Field(default=1.0, gt=0)
    worker_batch_size: int = Field(default=1, ge=1)
    job_max_attempts: int = Field(default=5, ge=1)

    # --- Providers ---
    llm_provider: ProviderKind = "fake"
    embedding_provider: ProviderKind = "fake"
    stt_provider: ProviderKind = "fake"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached so that FastAPI dependencies and the worker entrypoint observe the
    same instance. Call ``get_settings.cache_clear()`` in tests that need to
    rebuild it under a patched environment.
    """
    return Settings()
