"""Journey summary draft shape (M6 session 1).

Parses and validates an LLM's schema-constrained response. Pure — no I/O, no
ORM — same reasoning ``ai/extraction/memories.py`` gives: extraction/parsing
logic sits alongside ``domain/`` in spirit (CLAUDE.md rule 3) even though it
lives under ``ai/`` because it also defines the ``response_schema`` a
provider is constrained to.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError


class JourneySummaryDraft(BaseModel):
    model_config = {"frozen": True}

    narrative: str
    """A short narrative summary of the reader's journey through the book so
    far, grounded only in their own recorded reflections and predictions —
    never in the model's own knowledge of the book."""


JOURNEY_SUMMARY_RESPONSE_SCHEMA: dict[str, Any] = TypeAdapter(JourneySummaryDraft).json_schema()
"""Generated from ``JourneySummaryDraft`` itself, not hand-written, so the
shape a provider is constrained to and the shape
``parse_journey_summary_response`` expects can never drift apart — same
pattern as ``ai/extraction/memories.py``'s ``EXTRACTION_RESPONSE_SCHEMA``."""


class JourneySummaryParseError(ValueError):
    """The LLM's response isn't valid JSON, or doesn't match the expected
    shape. Generation fails visibly (``status=failed``) rather than
    persisting a summary nobody validated."""


def parse_journey_summary_response(text: str) -> JourneySummaryDraft:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise JourneySummaryParseError(f"response is not valid JSON: {exc}") from exc

    try:
        return JourneySummaryDraft.model_validate(raw)
    except ValidationError as exc:
        raise JourneySummaryParseError(
            f"response did not match the expected schema: {exc}"
        ) from exc
