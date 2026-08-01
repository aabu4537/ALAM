"""Adversarial case for ``GET /books/{id}/chapters`` and
``GET /books/{id}/structure`` (ADR-0002 amendment).

Complements ``alam/eval/spoiler_eval.py`` (memories) and
``alam/eval/prediction_spoiler_eval.py`` (predictions) — this is the third
and, per the amendment's audit, oldest reader-facing surface that turned out
to sit outside Layer 1's guarantee.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from alam.api.main import create_app
from alam.eval.models import SpoilerCaseResult, SpoilerEvalReport
from alam.persistence.repositories import (
    MediaItemRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)
from alam.persistence.session import session_scope

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session


def run_structure_spoiler_eval(session: Session) -> SpoilerEvalReport:
    """One book, chapters at ordinals 1, 5, and 9 (each with real
    ``first_lines`` prose), an active session repositioned to ordinal 3:

    - ``future_chapter_omitted``: ordinal 9's label must not appear in
      ``GET .../chapters`` at all — it is past the reader's position.
    - ``first_lines_never_present``: no row in that same response may carry
      a ``first_lines`` key, including ordinal 1's own, already-visible
      chapter — the field is structurally absent from the reading read's
      response model, not filtered per row.
    - ``verified_structure_read_refuses``: once the book is marked
      verified, ``GET .../structure`` (the verification read) must refuse
      rather than serve as a bypass back to the full, unfiltered,
      first_lines-carrying list.

    A positive control — ordinal 1's chapter appearing in
    ``GET .../chapters`` with its real label — proves the first two checks
    aren't trivially passing by returning nothing.
    """
    owner = UserRepository(session).create(display_name="Eval Owner")
    book = MediaItemRepository(session).create(user_id=owner.id, title="Eval Book")
    units = StructureUnitRepository(session)

    seen_unit = units.create(
        media_item_id=book.id, ordinal=1, label="Chapter 1", first_lines="It began on Arrakis..."
    )
    units.create(
        media_item_id=book.id, ordinal=5, label="Chapter 5", first_lines="Midway through..."
    )
    future_unit = units.create(
        media_item_id=book.id,
        ordinal=9,
        label="Chapter 9: The Emperor Abdicates",
        first_lines="In the final chapter...",
    )

    ReadingSessionRepository(session).get_or_create_active(
        book.id, structure_unit_id=seen_unit.id, ordinal=3, progress=0.3
    )

    def _session_override() -> Iterator[Session]:
        yield session

    app = create_app()
    app.dependency_overrides[session_scope] = _session_override
    try:
        with TestClient(app) as client:
            chapters_response = client.get(f"/books/{book.id}/chapters")
            chapters_response.raise_for_status()
            rows = chapters_response.json()["units"]

            MediaItemRepository(session).mark_structure_verified(book)
            structure_response = client.get(f"/books/{book.id}/structure")
    finally:
        app.dependency_overrides.clear()

    seen_row = next((row for row in rows if row["label"] == "Chapter 1"), None)
    if seen_row is None:
        raise AssertionError(
            "positive control failed: ordinal 1's own, already-visible chapter did not "
            f"appear in GET .../chapters (rows={rows!r}) — the checks below would pass by "
            "returning nothing, not by correctly scoping visibility"
        )

    labels = {row["label"] for row in rows}
    future_leaked = future_unit.label in labels
    first_lines_leaked = any("first_lines" in row for row in rows)
    bypass_leaked = structure_response.status_code != 409

    results = (
        SpoilerCaseResult(
            label="future_chapter_omitted",
            leaked=future_leaked,
            leaked_labels=(future_unit.label,) if future_leaked else (),
        ),
        SpoilerCaseResult(
            label="first_lines_never_present",
            leaked=first_lines_leaked,
            leaked_labels=("first_lines",) if first_lines_leaked else (),
        ),
        SpoilerCaseResult(
            label="verified_structure_read_refuses",
            leaked=bypass_leaked,
            leaked_labels=("structure_bypass",) if bypass_leaked else (),
        ),
    )

    leakage_rate = sum(1 for r in results if r.leaked) / len(results)
    return SpoilerEvalReport(leakage_rate=leakage_rate, results=results)
