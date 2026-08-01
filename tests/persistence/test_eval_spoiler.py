"""CI wiring for the adversarial spoiler set (M3, ADR-0002 Layer 4).

``leakage_rate`` is asserted at exactly 0.0. Layer 1 is a SQL predicate, not a
model's probabilistic judgment — any leakage here means the ordinal filter
itself broke, which must fail the build, not just get reported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alam.eval.journey_summary_eval import run_journey_summary_spoiler_eval
from alam.eval.prediction_spoiler_eval import run_prediction_reread_spoiler_eval
from alam.eval.spoiler_eval import run_spoiler_eval, run_spoiler_eval_via_endpoint
from alam.eval.structure_spoiler_eval import run_structure_spoiler_eval

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db


def test_adversarial_spoiler_set_has_zero_leakage(session: Session) -> None:
    report = run_spoiler_eval(session)

    leaked = [r for r in report.results if r.leaked]
    assert not leaked, f"spoiler leakage in: {leaked}"
    assert report.leakage_rate == 0.0


def test_adversarial_spoiler_set_has_zero_leakage_through_the_real_endpoint(
    session: Session,
) -> None:
    """Same cases, same predicate, run through ``GET /books/{id}/memories``
    instead of calling ``retrieve_memories`` directly — pre-M6 hardening
    task 4. A regression that only lived in the router or in
    ``get_reader_context`` (not in ``retrieve_memories`` itself) would pass
    ``test_adversarial_spoiler_set_has_zero_leakage`` above and fail here."""
    report = run_spoiler_eval_via_endpoint(session)

    leaked = [r for r in report.results if r.leaked]
    assert not leaked, f"spoiler leakage in: {leaked}"
    assert report.leakage_rate == 0.0


def test_predictions_have_zero_leakage_across_a_reread(session: Session) -> None:
    """ADR-0012's re-read case: a completed first read leaves resolved
    predictions in the database; a re-read at a low ordinal must not see
    them until it reaches the same points again."""
    report = run_prediction_reread_spoiler_eval(session)

    leaked = [r for r in report.results if r.leaked]
    assert not leaked, f"prediction leakage in: {leaked}"
    assert report.leakage_rate == 0.0


def test_chapters_have_zero_leakage_and_first_lines_never_appears(session: Session) -> None:
    """ADR-0002 amendment: GET .../chapters must not surface a future
    chapter's label, must never carry first_lines at all, and GET
    .../structure must refuse once verified rather than serving as a
    bypass back to the unfiltered list."""
    report = run_structure_spoiler_eval(session)

    leaked = [r for r in report.results if r.leaked]
    assert not leaked, f"structure leakage in: {leaked}"
    assert report.leakage_rate == 0.0


def test_journey_summary_has_zero_leakage(session: Session) -> None:
    """M6 session 1's ``synthesis_leakage_rate`` (ADR-0002 Layer 3,
    ADR-0013): a journey summary generated mid-book must not leak a
    spoiler-shaped memory the ordinal filter excluded, checked both by
    Layer 3's own verdict and, defense-in-depth, by a plain substring check
    on the draft actually returned."""
    report = run_journey_summary_spoiler_eval(session)

    leaked = [r for r in report.results if r.leaked]
    assert not leaked, f"journey summary leakage in: {leaked}"
    assert report.leakage_rate == 0.0
