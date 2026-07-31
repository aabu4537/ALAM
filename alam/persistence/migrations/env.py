"""Alembic environment.

The database URL comes from typed settings rather than alembic.ini, so the app,
the worker, and migrations cannot disagree about which database they mean, and
no credentials live in a committed file.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from alam.config.settings import get_settings

# Imported for the side effect of registering every model on Base.metadata —
# autogenerate cannot see a model that was never imported.
from alam.persistence.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Only fall back to settings when the caller has not supplied a URL. Tests and
# CI construct a Config pointed at a throwaway database; overriding that
# unconditionally would silently migrate the developer's real database instead.
if not config.get_main_option("sqlalchemy.url", None):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        # Without this the pool outlives the call. Harmless for a one-shot CLI
        # run, but tests invoke this in-process and the leaked connection
        # surfaces as an unraisable exception during teardown.
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
