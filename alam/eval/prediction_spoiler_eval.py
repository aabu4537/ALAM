"""Adversarial re-read case for ``GET /books/{id}/predictions`` (ADR-0012).

Complements ``alam/eval/spoiler_eval.py``, which covers ``GET
/books/{id}/memories`` — this covers the other reader-facing route that sat
outside ADR-0002 Layer 1's guarantee until ADR-0012 closed it. Finishes a
book with three predictions made and resolved across it, starts a fresh
re-read session partway through, and checks — through the real endpoint,
not the service function in isolation — that nothing the first read
resolved becomes visible again before the re-read reaches the same point.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from alam.ai.extraction.memories import ExtractedMemory
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.api.dependencies import require_owner_session
from alam.api.main import create_app
from alam.eval.models import SpoilerCaseResult, SpoilerEvalReport
from alam.persistence.models.prediction import PredictionStatus
from alam.persistence.models.reading_session import ReadingSessionStatus
from alam.persistence.repositories import (
    CaptureRepository,
    MediaItemRepository,
    MemoryRepository,
    PredictionRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)
from alam.persistence.session import session_scope
from alam.services.reading_sessions import end_reading_session

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaItem, Memory

_RESOLVED_AT = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
_RESOLUTION_PROMPT_VERSION_ID = "eval-seed-v1"


def _memory_at(session: Session, book: MediaItem, *, ordinal: int, content: str) -> Memory:
    unit = StructureUnitRepository(session).create(
        media_item_id=book.id, ordinal=ordinal, label=f"Chapter {ordinal}"
    )
    reading_session = ReadingSessionRepository(session).get_or_create_active(
        book.id, structure_unit_id=unit.id, ordinal=ordinal, progress=1.0
    )
    capture = CaptureRepository(session).create(
        reading_session_id=reading_session.id,
        media_item_id=book.id,
        structure_unit_id=unit.id,
        structure_ordinal=ordinal,
        audio_data=b"x",
    )
    [memory] = MemoryRepository(session).create_many(
        capture_id=capture.id,
        media_item_id=book.id,
        structure_unit_id=unit.id,
        structure_ordinal=ordinal,
        prompt_version_id=_RESOLUTION_PROMPT_VERSION_ID,
        extracted=[ExtractedMemory(memory_type=ExtractedMemoryType.PREDICTION, content=content)],
    )
    return memory


def run_prediction_reread_spoiler_eval(session: Session) -> SpoilerEvalReport:
    """One book, three predictions, one full read followed by a re-read
    repositioned to ordinal 7:

    - ``prediction_early`` (made at 2, window 3, due at 5) is resolved and
      its window closes well before ordinal 7 — a positive control. If the
      endpoint failed to reveal this one, the two checks below would pass
      by masking everything rather than by scoping visibility correctly.
    - ``prediction_mid`` (made at 5, window 10, due at 15) is resolved
      during the first read, but ordinal 7 is short of its window closing —
      the endpoint must still show its statement (made at 5 <= 7) but mask
      its status back to "pending" with no evidence.
    - ``prediction_late`` (made at 18) is past ordinal 7 entirely and must
      not appear in the response at all.
    """
    owner = UserRepository(session).create(display_name="Eval Owner")
    book = MediaItemRepository(session).create(user_id=owner.id, title="Eval Book")
    predictions = PredictionRepository(session)

    early_source = _memory_at(session, book, ordinal=2, content="I bet the guard is friendly")
    early_evidence = _memory_at(session, book, ordinal=4, content="the guard really was friendly")
    early = predictions.create(
        source_memory_id=early_source.id,
        media_item_id=book.id,
        made_at_ordinal=2,
        resolution_window=3,
    )
    predictions.resolve(
        early,
        status=PredictionStatus.CONFIRMED,
        resolved_at=_RESOLVED_AT,
        resolution_prompt_version_id=_RESOLUTION_PROMPT_VERSION_ID,
        evidence_memory_ids=[early_evidence.id],
    )

    mid_source = _memory_at(session, book, ordinal=5, content="I bet Paul kills the Baron")
    mid_evidence = _memory_at(session, book, ordinal=12, content="Paul kills the Baron in the end")
    mid = predictions.create(
        source_memory_id=mid_source.id,
        media_item_id=book.id,
        made_at_ordinal=5,
        resolution_window=10,
    )
    predictions.resolve(
        mid,
        status=PredictionStatus.CONFIRMED,
        resolved_at=_RESOLVED_AT,
        resolution_prompt_version_id=_RESOLUTION_PROMPT_VERSION_ID,
        evidence_memory_ids=[mid_evidence.id],
    )

    late_source = _memory_at(session, book, ordinal=18, content="I bet the emperor abdicates")
    late_evidence = _memory_at(session, book, ordinal=19, content="the emperor abdicates to Paul")
    late = predictions.create(
        source_memory_id=late_source.id,
        media_item_id=book.id,
        made_at_ordinal=18,
        resolution_window=2,
    )
    predictions.resolve(
        late,
        status=PredictionStatus.CONFIRMED,
        resolved_at=_RESOLVED_AT,
        resolution_prompt_version_id=_RESOLUTION_PROMPT_VERSION_ID,
        evidence_memory_ids=[late_evidence.id],
    )

    first_read = ReadingSessionRepository(session).get_active_for_media_item(book.id)
    if first_read is None:
        raise AssertionError("seeding left no active session to complete — a setup bug")
    end_reading_session(
        session,
        user_id=owner.id,
        media_item_id=book.id,
        reading_session_id=first_read.id,
        status=ReadingSessionStatus.COMPLETED,
    )

    reread_unit = StructureUnitRepository(session).create(
        media_item_id=book.id, ordinal=7, label="Chapter 7 (re-read)"
    )
    ReadingSessionRepository(session).get_or_create_active(
        book.id, structure_unit_id=reread_unit.id, ordinal=7, progress=0.3
    )

    def _session_override() -> Iterator[Session]:
        yield session

    app = create_app()
    app.dependency_overrides[session_scope] = _session_override
    app.dependency_overrides[require_owner_session] = lambda: None
    try:
        with TestClient(app) as client:
            response = client.get(f"/books/{book.id}/predictions")
            response.raise_for_status()
            rows = {row["id"]: row for row in response.json()}
    finally:
        app.dependency_overrides.clear()

    early_row = rows.get(str(early.id))
    if early_row is None or early_row["status"] != "confirmed" or not early_row["evidence"]:
        raise AssertionError(
            "positive control failed: the early, already-due prediction's real "
            f"outcome was not shown (row={early_row!r}) — the checks below would "
            "pass by masking everything, not by correctly scoping visibility"
        )

    late_leaked = str(late.id) in rows
    mid_row = rows.get(str(mid.id))
    mid_leaked = mid_row is not None and (
        mid_row["status"] != "pending" or bool(mid_row["evidence"])
    )

    results = (
        SpoilerCaseResult(
            label="prediction_made_past_current_ordinal_is_omitted",
            leaked=late_leaked,
            leaked_labels=("prediction_late",) if late_leaked else (),
        ),
        SpoilerCaseResult(
            label="resolved_prediction_masked_before_window_closes",
            leaked=mid_leaked,
            leaked_labels=("prediction_mid",) if mid_leaked else (),
        ),
    )

    leakage_rate = sum(1 for r in results if r.leaked) / len(results)
    return SpoilerEvalReport(leakage_rate=leakage_rate, results=results)
