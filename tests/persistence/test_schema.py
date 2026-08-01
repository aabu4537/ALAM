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


def test_memory_embeddings_vector_column_has_no_fixed_dimension(session: Session) -> None:
    """ADR-0008: a fixed-width ``vector(N)`` column is what forces a
    same-table embedding design into a stop-the-world migration on every
    model swap. This side table's vector column must stay dimensionless so
    rows from different-dimension models can coexist for the same memory."""
    column_type = session.execute(
        text(
            "SELECT format_type(a.atttypid, a.atttypmod) "
            "FROM pg_attribute a "
            "WHERE a.attrelid = 'memory_embeddings'::regclass AND a.attname = 'vector'"
        )
    ).scalar_one()

    assert column_type == "vector", f"expected an unconstrained vector column, got {column_type!r}"


def test_memory_embeddings_natural_key_is_unique_but_content_hash_is_not(
    session: Session,
) -> None:
    """The natural key is the real uniqueness guarantee — one row per memory
    per model/version. ``content_hash`` is deliberately just an index: two
    different memories can share identical content, and both legitimately
    need their own row (ADR-0008)."""
    unique_constraints = set(
        session.scalars(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'memory_embeddings'::regclass AND contype = 'u'"
            )
        ).all()
    )
    indexes = set(
        session.scalars(
            text("SELECT indexname FROM pg_indexes WHERE tablename = 'memory_embeddings'")
        ).all()
    )

    assert "uq_memory_embeddings_memory_model_version" in unique_constraints
    assert not any("content_hash" in c for c in unique_constraints)
    assert "ix_memory_embeddings_content_hash" in indexes


def test_expected_tables_exist_and_nothing_else(session: Session) -> None:
    """M0 shipped four tables; M2 adds `reading_sessions`, `captures`
    (session 1), and `memories` (session 3); M3 session 1 adds
    `memory_embeddings`; M4 session 1 adds `preference_facts` and
    `preference_fact_evidence`; M5 session 1 adds `predictions` and
    `prediction_evidence` (evidence links to `memories`, not `content_chunks`
    — see ADR-0009); M5.5a adds `llm_calls`; M6 session 1 adds
    `journey_summaries` (ADR-0013); M6 session 2 adds `recommendations`
    (ADR-0014); M6 session 4 adds `briefings`, reusing the same
    citation-groundedness scheme. `content_chunks` remains later work — a
    stray table here means something was built ahead of the chunking
    pipeline that doesn't exist yet (see ADR-0008)."""
    tables = set(
        session.scalars(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).all()
    )

    assert tables == {
        "users",
        "media_items",
        "media_structure_units",
        "jobs",
        "reading_sessions",
        "captures",
        "memories",
        "memory_embeddings",
        "preference_facts",
        "preference_fact_evidence",
        "predictions",
        "prediction_evidence",
        "llm_calls",
        "journey_summaries",
        "recommendations",
        "briefings",
    }


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
    assert "ck_jobs_status" in checks
    assert "ck_reading_sessions_status" in checks
    assert "ck_captures_status" in checks
    assert "ck_memories_memory_type" in checks


def test_claim_path_indexes_are_partial(session: Session) -> None:
    """The claim query scans outstanding work, not job history.

    Without the predicates these indexes grow with every job ever run, and the
    queue slows down permanently as a function of throughput.
    """
    rows = session.execute(
        text(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename = 'jobs' AND indexname IN "
            "('ix_jobs_claimable', 'ix_jobs_expired_leases')"
        )
    ).all()
    predicates = {str(name): str(definition) for name, definition in rows}

    assert len(predicates) == 2
    assert "WHERE" in predicates["ix_jobs_claimable"]
    assert "WHERE" in predicates["ix_jobs_expired_leases"]


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


def test_current_progress_out_of_range_is_rejected_by_the_database(session: Session) -> None:
    from sqlalchemy.exc import IntegrityError

    user_id = session.execute(
        text("INSERT INTO users (id, display_name) VALUES (gen_random_uuid(), 'x') RETURNING id")
    ).scalar_one()
    item_id = session.execute(
        text(
            "INSERT INTO media_items (id, user_id, media_type, title) "
            "VALUES (gen_random_uuid(), :uid, 'book', 'x') RETURNING id"
        ),
        {"uid": user_id},
    ).scalar_one()
    unit_id = session.execute(
        text(
            "INSERT INTO media_structure_units (id, media_item_id, ordinal, unit_type, label) "
            "VALUES (gen_random_uuid(), :item_id, 1, 'chapter', 'Ch 1') RETURNING id"
        ),
        {"item_id": item_id},
    ).scalar_one()

    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO reading_sessions "
                "(id, media_item_id, current_structure_unit_id, current_ordinal, current_progress) "
                "VALUES (gen_random_uuid(), :item_id, :unit_id, 1, 1.5)"
            ),
            {"item_id": item_id, "unit_id": unit_id},
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
