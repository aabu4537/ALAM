"""Assertions about the shipped schema itself, not about repository behaviour.

These check the properties later milestones will silently depend on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def test_vector_extension_is_enabled(session: Session) -> None:
    """M3 needs pgvector. The migration enables it at M0 so a privilege problem
    surfaces now rather than three milestones from here."""
    installed = session.execute(
        text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    ).scalar_one_or_none()

    assert installed is not None


def test_expected_tables_exist_and_nothing_else(session: Session) -> None:
    """M0 ships three tables. `memories` and chunks are later milestones, and a
    stray table here means something was built ahead of its milestone."""
    tables = set(
        session.scalars(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).all()
    )

    assert tables == {"users", "media_items", "media_structure_units"}


def test_ordinal_uniqueness_is_deferrable(session: Session) -> None:
    """The property ADR-0006's renumbering depends on.

    A non-deferrable constraint here still passes every ordinary test and only
    fails when a real reshuffle runs, so it is asserted directly.
    """
    row = session.execute(
        text(
            "SELECT condeferrable, condeferred FROM pg_constraint "
            "WHERE conname = 'uq_media_structure_units_media_item_id_ordinal'"
        )
    ).one_or_none()

    assert row is not None, "the unique constraint is missing entirely"
    deferrable, deferred_by_default = row
    assert deferrable is True, "constraint is not DEFERRABLE; bulk renumbering will abort"
    assert deferred_by_default is False, "expected INITIALLY IMMEDIATE"


def test_all_timestamp_columns_are_timezone_aware(session: Session) -> None:
    """CLAUDE.md: all timestamps TIMESTAMPTZ, stored UTC.

    A bare `timestamp` column silently drops the offset, and every ordinal
    window and decay calculation downstream inherits the error.
    """
    naive = session.execute(
        text(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND data_type LIKE 'timestamp%%' "
            "AND data_type <> 'timestamp with time zone'"
        )
    ).all()

    assert naive == []


def test_discriminator_columns_are_constrained_in_the_database(
    session: Session,
) -> None:
    """`native_enum=False` alone yields a bare VARCHAR.

    SQLAlchemy 2.0 defaults `create_constraint` to False, so the enum would be
    enforced only by the ORM and any raw SQL, backfill, or migration could
    write an unknown media type. Caught exactly this way during Session 2.
    """
    checks = set(
        session.scalars(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE contype = 'c' AND connamespace = 'public'::regnamespace"
            )
        ).all()
    )

    # Names come from the `ck` naming convention in persistence/base.py, which
    # prepends `ck_<table>_` — so the Enum's own `name` is the bare column name.
    assert "ck_media_items_media_type" in checks
    assert "ck_media_structure_units_unit_type" in checks


def test_unknown_media_type_is_rejected_by_the_database(session: Session) -> None:
    from sqlalchemy.exc import IntegrityError

    user_id = session.execute(
        text("INSERT INTO users (id, display_name) VALUES (gen_random_uuid(), 'x') RETURNING id")
    ).scalar_one()

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO media_items (id, user_id, media_type, title) "
                "VALUES (gen_random_uuid(), :uid, 'podcast', 'Nope')"
            ),
            {"uid": user_id},
        )


def test_primary_keys_are_uuid(session: Session) -> None:
    non_uuid = session.execute(
        text(
            "SELECT c.table_name, c.data_type "
            "FROM information_schema.columns c "
            "JOIN information_schema.key_column_usage k "
            "  ON k.table_name = c.table_name AND k.column_name = c.column_name "
            "JOIN information_schema.table_constraints t "
            "  ON t.constraint_name = k.constraint_name "
            "WHERE t.constraint_type = 'PRIMARY KEY' "
            "  AND c.table_schema = 'public' AND c.data_type <> 'uuid' "
            # Alembic's own bookkeeping table, not ours.
            "  AND c.table_name <> 'alembic_version'"
        )
    ).all()

    assert non_uuid == []
