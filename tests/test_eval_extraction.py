"""CI wiring for extraction accuracy (M3, ADR-0002 Layer 4). No database —
the pipeline is prompt build -> LLM call -> parse.

Two things are worth locking in, and neither is "the model is good," since
``FakeLLM`` has no extraction capability to be good or bad at (see
``alam/eval/extraction_eval.py``'s module docstring):

1. Running the harness against a provider with genuinely nothing to offer
   produces an honest, structurally sound zero — not a crash, not a silent
   pass.
2. The harness's own scoring logic is correct: fed exactly the expected
   types, it reports perfect accuracy.
"""

from __future__ import annotations

import json

from alam.ai.providers.fakes import FakeLLM
from alam.eval.extraction_eval import EXTRACTION_CASES, run_extraction_eval


def test_a_provider_with_no_capability_is_scored_honestly() -> None:
    llm = FakeLLM()  # no queued responses -> deterministic non-JSON default text

    report = run_extraction_eval(llm, cases=EXTRACTION_CASES)

    assert report.accuracy == 0.0
    assert all(r.error is not None for r in report.results)


def test_the_scoring_logic_reports_perfect_accuracy_when_types_match() -> None:
    responses = [
        json.dumps([{"memory_type": m.memory_type.value, "content": "x"} for m in case.expected])
        for case in EXTRACTION_CASES
    ]
    llm = FakeLLM(responses=responses)

    report = run_extraction_eval(llm, cases=EXTRACTION_CASES)

    assert report.accuracy == 1.0
    assert all(r.correct and r.error is None for r in report.results)


def test_a_type_mismatch_is_scored_incorrect_not_errored() -> None:
    """Valid JSON with the wrong types is a wrong answer, not a parse
    failure — the two must stay distinguishable in the report."""
    llm = FakeLLM(responses=['[{"memory_type": "confusion", "content": "x"}]'])

    report = run_extraction_eval(llm, cases=EXTRACTION_CASES[:1])

    assert report.accuracy == 0.0
    assert report.results[0].correct is False
    assert report.results[0].error is None
