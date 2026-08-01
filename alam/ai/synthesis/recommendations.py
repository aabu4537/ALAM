"""Recommendation draft shape (M6 session 2, ADR-0014; widened M6 session 3,
ADR-0015).

Parses and validates an LLM's schema-constrained response. Pure — no I/O, no
ORM — same reasoning ``ai/synthesis/journey_summary.py`` gives.

The schema is a **selection, not prose**: which candidate, backed by which
of the reader's own ``preference_fact``/``memory`` ids, or — now that
``CatalogProvider`` exists — the candidate's own fetched ``catalog`` entry.
There is no free-text field anywhere in it for the model to write a new
sentence into — the same move ``VisibleStructureUnitResponse`` makes by
omitting ``first_lines``, no field for unsourced content to occupy. This is
what makes a hallucinated characterization structurally unrepresentable
rather than merely detected after the fact, for *any* citation type, not
just the two taste-only ones session 2 shipped with;
``domain/recommendation_groundedness.py`` only has to check that cited
*ids* are real (or, for ``"catalog"``, that the candidate actually has a
fetched entry), since there is nothing else left in the shape to check.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, TypeAdapter, ValidationError


class CitationRef(BaseModel):
    model_config = {"frozen": True}

    type: Literal["preference_fact", "memory", "catalog"]
    id: str
    """For ``"catalog"``, this is the candidate's own ``media_item_id`` —
    there is exactly one fetched catalog entry per book, unlike facts and
    memories, so citing "the candidate's own metadata" needs no separate id
    space."""


class RecommendationDraft(BaseModel):
    model_config = {"frozen": True}

    media_item_id: str
    cites: list[CitationRef]
    """Which of the reader's own facts/memories support recommending this
    candidate. Never empty in a well-formed draft — a candidate with no
    supporting citation has nothing grounding it and should not have been
    selected — but that's a service-level judgment call, not something this
    schema enforces on its own."""


class RecommendationSetDraft(BaseModel):
    model_config = {"frozen": True}

    recommendations: list[RecommendationDraft]


RECOMMENDATION_RESPONSE_SCHEMA: dict[str, Any] = TypeAdapter(RecommendationSetDraft).json_schema()
"""Generated from ``RecommendationSetDraft`` itself, not hand-written, so the
shape a provider is constrained to and the shape
``parse_recommendation_response`` expects can never drift apart — same
pattern as ``ai/synthesis/journey_summary.py``'s
``JOURNEY_SUMMARY_RESPONSE_SCHEMA``."""


class RecommendationParseError(ValueError):
    """The LLM's response isn't valid JSON, or doesn't match the expected
    shape. Generation fails visibly (``status=failed``) rather than
    persisting a recommendation set nobody validated."""


def parse_recommendation_response(text: str) -> RecommendationSetDraft:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RecommendationParseError(f"response is not valid JSON: {exc}") from exc

    try:
        return RecommendationSetDraft.model_validate(raw)
    except ValidationError as exc:
        raise RecommendationParseError(
            f"response did not match the expected schema: {exc}"
        ) from exc
