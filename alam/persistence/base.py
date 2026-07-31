"""Declarative base and shared column conventions.

UUIDv7 primary keys are generated client-side via ``uuid6.uuid7`` rather than in
Postgres. v7 is time-ordered, so rows cluster by creation time in the index
without the write amplification random v4 keys cause. Generating in Python means
no extension dependency, and the id exists before the flush — which repositories
rely on to wire relationships without a round trip.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid6 import uuid7

# Explicit naming so Alembic autogenerate emits stable, non-random constraint
# names — otherwise every migration churns them and downgrades cannot find them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """UUIDv7 primary key."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)


class TimestampMixin:
    """``created_at`` / ``updated_at``, both TIMESTAMPTZ and stored UTC.

    Defaults are server-side so rows written outside the ORM — migrations,
    backfills, psql — still get correct values.
    """

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
