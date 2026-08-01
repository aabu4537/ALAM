"""CI wiring for ``recommendation_groundedness`` (M6 session 2, ADR-0014).

``ungrounded_rate`` is asserted at exactly 0.0 — both the clean-citation
case and the deliberately-bad-citation positive control must come back
clean, the same "not vacuously passing" precedent
``test_journey_summary_has_zero_leakage`` established for
``synthesis_leakage_rate``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alam.eval.recommendation_eval import run_recommendation_groundedness_eval

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db


def test_recommendations_have_zero_ungrounded_citations(session: Session) -> None:
    report = run_recommendation_groundedness_eval(session)

    ungrounded = [r for r in report.results if r.ungrounded]
    assert not ungrounded, f"ungrounded recommendation citations in: {ungrounded}"
    assert report.ungrounded_rate == 0.0
