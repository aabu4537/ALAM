"""CI wiring for the golden retrieval set (M3, ADR-0002 Layer 4).

Asserted, not just reported: recall@k over ``retrieve_memories`` is fully
deterministic (full-text ranking, RRF, and the fake embedding provider's
vectors are all pure functions of their input), so a drop below 1.0 is a real
regression in the retrieval path, not sampling noise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from alam.eval.retrieval_eval import run_retrieval_eval

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db


def test_golden_retrieval_set_achieves_perfect_recall(session: Session) -> None:
    report = run_retrieval_eval(session)

    failing = [r for r in report.results if r.recall < 1.0]
    assert not failing, f"cases with missed relevant memories: {failing}"
    assert report.recall_at_k == 1.0
