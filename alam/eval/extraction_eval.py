"""Extraction accuracy against hand-labeled transcripts (M3, ADR-0002 Layer
4 / docs/milestones.md's "Evaluation harness").

Runs the exact prompt-build -> LLM -> parse pipeline ``services/
capture_pipeline.py`` uses in production, not a reimplementation of it, so a
prompt-wording regression shows up here too.

**Not a real quality signal while ``ALAM_LLM_PROVIDER=fake``.** ``FakeLLM``
has no extraction capability — with no queued response it returns a
deterministic non-JSON string, which fails to parse on every case. That is
the honest result of running this harness against a provider with no
judgment to measure, not a bug in the harness. This module exists so the
dataset format, the pipeline wiring, and the CI job are in place; the
accuracy number only means something once a real ``LLMProvider`` exists
(CLAUDE.md rule 8) — see ADR-0002's rejection of claiming a guarantee that
doesn't hold.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.ai.extraction.memories import ExtractedMemory, ExtractionError, parse_extraction_response
from alam.ai.extraction.memories import MemoryType as ExtractedMemoryType
from alam.ai.prompts.extraction import PROMPT_VERSION_ID, build_extraction_prompt
from alam.eval.models import ExtractionCase, ExtractionCaseResult, ExtractionEvalReport

if TYPE_CHECKING:
    from alam.ai.providers.llm import LLMProvider

EXTRACTION_CASES: tuple[ExtractionCase, ...] = (
    ExtractionCase(
        label="single_opinion",
        transcript="I really think Paul is being too reckless taking this bet with the Fremen.",
        expected=(ExtractedMemory(memory_type=ExtractedMemoryType.OPINION, content="..."),),
    ),
    ExtractionCase(
        label="single_prediction",
        transcript="I bet Jessica turns out to be more important to the Bene Gesserit plan than "
        "anyone's said so far.",
        expected=(ExtractedMemory(memory_type=ExtractedMemoryType.PREDICTION, content="..."),),
    ),
    ExtractionCase(
        label="emotional_reaction",
        transcript="That scene with the gom jabbar genuinely made my stomach drop.",
        expected=(
            ExtractedMemory(memory_type=ExtractedMemoryType.EMOTIONAL_REACTION, content="..."),
        ),
    ),
    ExtractionCase(
        label="confusion",
        transcript="Wait, I don't understand why the Baron trusts Piter at all after that scene.",
        expected=(ExtractedMemory(memory_type=ExtractedMemoryType.CONFUSION, content="..."),),
    ),
    ExtractionCase(
        label="character_judgment",
        transcript="Duncan Idaho comes across as fiercely loyal, more than anyone else at court.",
        expected=(
            ExtractedMemory(memory_type=ExtractedMemoryType.CHARACTER_JUDGMENT, content="..."),
        ),
    ),
    ExtractionCase(
        label="favorite_moment",
        transcript="My favorite part so far is the ornithopter flight over the spice fields.",
        expected=(ExtractedMemory(memory_type=ExtractedMemoryType.FAVORITE_MOMENT, content="..."),),
    ),
    ExtractionCase(
        label="meta_comment",
        transcript="The pacing in this chapter feels a lot slower than the last one.",
        expected=(ExtractedMemory(memory_type=ExtractedMemoryType.META_COMMENT, content="..."),),
    ),
    ExtractionCase(
        label="two_distinct_memories_in_one_transcript",
        transcript="I love how tense the council scene is, but I'm also a little confused about "
        "why Yueh betrays the Atreides after being so loyal.",
        expected=(
            ExtractedMemory(memory_type=ExtractedMemoryType.FAVORITE_MOMENT, content="..."),
            ExtractedMemory(memory_type=ExtractedMemoryType.CONFUSION, content="..."),
        ),
    ),
)
"""``content`` on each expected memory is a placeholder — this harness scores
``memory_type`` multisets only (see ``ExtractionEvalReport``'s docstring for
why), so wording is never compared."""


def _expected_types(memories: tuple[ExtractedMemory, ...]) -> tuple[str, ...]:
    return tuple(sorted(m.memory_type.value for m in memories))


def run_extraction_eval(
    llm: LLMProvider, *, cases: tuple[ExtractionCase, ...] = EXTRACTION_CASES
) -> ExtractionEvalReport:
    results = []
    for case in cases:
        prompt = build_extraction_prompt(case.transcript)
        completion = llm.complete(prompt, prompt_version_id=PROMPT_VERSION_ID)

        expected_types = _expected_types(case.expected)
        try:
            actual = parse_extraction_response(completion.text)
        except ExtractionError as exc:
            results.append(
                ExtractionCaseResult(
                    label=case.label,
                    correct=False,
                    expected_types=expected_types,
                    actual_types=(),
                    error=str(exc),
                )
            )
            continue

        actual_types = _expected_types(tuple(actual))
        results.append(
            ExtractionCaseResult(
                label=case.label,
                correct=actual_types == expected_types,
                expected_types=expected_types,
                actual_types=actual_types,
                error=None,
            )
        )

    accuracy = sum(1 for r in results if r.correct) / len(results) if results else 0.0
    return ExtractionEvalReport(accuracy=accuracy, results=tuple(results))
