"""Prediction + evidence window -> resolution outcome (M5).

Parses and validates the resolution LLM's JSON response. Pure — no I/O, no
ORM — same reasoning as ``ai/extraction/memories.py`` and
``ai/consolidation/actions.py``: sits alongside ``domain/`` in spirit
(CLAUDE.md rule 3), testable against hand-written JSON with no model in the
loop. ``services/prediction_resolution.py`` maps the outcome onto
``PredictionRepository.resolve``.
"""

from __future__ import annotations

import enum
import json

from pydantic import BaseModel, ValidationError


class ResolutionOutcome(enum.StrEnum):
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    UNRESOLVABLE = "unresolvable"
    """A real outcome, not a fallback for a parse failure — some predictions
    are too vague for the evidence window to confirm or refute either way."""


class Resolution(BaseModel):
    model_config = {"frozen": True}

    outcome: ResolutionOutcome


class ResolutionError(ValueError):
    """The LLM's response isn't valid JSON, or doesn't match the expected
    shape. A prediction that fails to parse fails the job — visible and
    retryable — rather than silently staying pending forever."""


def parse_resolution_response(text: str) -> Resolution:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ResolutionError(f"response is not valid JSON: {exc}") from exc

    try:
        return Resolution.model_validate(raw)
    except ValidationError as exc:
        raise ResolutionError(f"response did not match the expected schema: {exc}") from exc
