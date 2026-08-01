"""Case and report shapes shared by the three eval harnesses (M3, ADR-0002
Layer 4).

Not ``domain/`` — these types describe I/O-bound evaluation runs (they seed a
database, they call a provider), not pure logic. Frozen dataclasses rather
than Pydantic: nothing here crosses a wire boundary, so the extra machinery
buys nothing (CLAUDE.md's Pydantic convention is for boundary types).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from alam.ai.extraction.memories import ExtractedMemory


@dataclass(frozen=True)
class SeedMemory:
    """One memory to seed before a retrieval or spoiler case runs.

    ``label`` is the case-local handle a case's expectations refer to — never
    persisted, never compared to anything but itself within one case.
    """

    label: str
    content: str
    structure_ordinal: int


@dataclass(frozen=True)
class RetrievalCase:
    label: str
    memories: tuple[SeedMemory, ...]
    query: str
    current_ordinal: int
    relevant_labels: tuple[str, ...]
    """Labels from ``memories`` that a good retriever must surface."""


@dataclass(frozen=True)
class RetrievalCaseResult:
    label: str
    recall: float
    missing_labels: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalEvalReport:
    k: int
    recall_at_k: float
    """Macro-average of each case's recall — every case counts equally
    regardless of how many relevant memories it defines."""
    results: tuple[RetrievalCaseResult, ...]


@dataclass(frozen=True)
class SpoilerCase:
    label: str
    memories: tuple[SeedMemory, ...]
    query: str
    current_ordinal: int
    """Engineered adversarially: at least one memory in ``memories`` sits past
    this ordinal and is textually close to ``query``, so it would surface if
    the ordinal filter were missing or broken."""


@dataclass(frozen=True)
class SpoilerCaseResult:
    label: str
    leaked: bool
    leaked_labels: tuple[str, ...]
    """Non-empty only when ``leaked`` — the labels of any returned memory
    whose ``structure_ordinal`` exceeds the case's ``current_ordinal``."""


@dataclass(frozen=True)
class SpoilerEvalReport:
    leakage_rate: float
    """ADR-0002 Layer 4's headline number. Layer 1 is a SQL predicate, not a
    model's judgment call, so this is expected to be exactly 0.0 — the
    adversarial set exists to catch a regression, not to measure a
    probabilistic quality level."""
    results: tuple[SpoilerCaseResult, ...]


@dataclass(frozen=True)
class ExtractionCase:
    label: str
    transcript: str
    expected: tuple[ExtractedMemory, ...]


@dataclass(frozen=True)
class ExtractionCaseResult:
    label: str
    correct: bool
    expected_types: tuple[str, ...]
    actual_types: tuple[str, ...]
    error: str | None
    """Set when the provider's response failed to parse at all — a stronger
    failure than a type mismatch, reported separately rather than folded into
    a wrong-answer bucket."""


@dataclass(frozen=True)
class ExtractionEvalReport:
    accuracy: float
    """A case counts as correct when the multiset of extracted memory_types
    exactly matches the multiset of expected memory_types. Content wording is
    not scored — judging paraphrase quality needs a semantic comparison this
    harness does not attempt.

    NOT a real quality signal while ``ALAM_LLM_PROVIDER=fake``: FakeLLM has no
    extraction capability, so this number reflects the harness's own plumbing,
    not any model's judgment. Meaningful only once a real LLM provider exists.
    """
    results: tuple[ExtractionCaseResult, ...]
