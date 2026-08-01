"""Memory batch -> preference-fact actions (M4 session 2, ADR-0001).

Parses and validates the consolidation LLM's JSON response. Pure — no I/O, no
ORM — same reasoning as ``ai/extraction/memories.py``: this sits alongside
``domain/`` in spirit (CLAUDE.md rule 3) and must be testable against
hand-written JSON with no model in the loop. ``services/consolidation.py``
maps an action onto ``PreferenceFactRepository`` calls.
"""

from __future__ import annotations

import enum
import json
import uuid

from pydantic import BaseModel, ValidationError, model_validator


class ConsolidationActionType(enum.StrEnum):
    NEW = "new"
    """A preference not already covered by any active fact."""

    REINFORCE = "reinforce"
    """A new memory confirms an existing active fact — no new statement, no
    new row; just moves confidence toward 1 and resets the decay clock."""

    SUPERSEDE = "supersede"
    """A new memory contradicts an existing active fact — writes a new row
    with its own statement, retiring the old one rather than editing it."""


class ConsolidationAction(BaseModel):
    model_config = {"frozen": True}

    action: ConsolidationActionType
    memory_ids: list[uuid.UUID]
    """Which memories in this batch support the action. Never empty — an
    action with no evidence isn't a consolidation decision, it's a guess."""

    statement: str | None = None
    """Required for ``new`` and ``supersede``; the human-readable fact text."""

    fact_id: uuid.UUID | None = None
    """Required for ``reinforce`` and ``supersede``; which existing active
    fact (from the ones the prompt supplied) the action applies to."""

    @model_validator(mode="after")
    def _required_fields_match_the_action(self) -> ConsolidationAction:
        if not self.memory_ids:
            raise ValueError("an action must cite at least one supporting memory")
        needs_statement = self.action in (
            ConsolidationActionType.NEW,
            ConsolidationActionType.SUPERSEDE,
        )
        if needs_statement and not self.statement:
            raise ValueError(f"{self.action.value} requires a non-empty statement")
        needs_fact_id = self.action in (
            ConsolidationActionType.REINFORCE,
            ConsolidationActionType.SUPERSEDE,
        )
        if needs_fact_id and self.fact_id is None:
            raise ValueError(f"{self.action.value} requires a fact_id")
        return self


class ConsolidationError(ValueError):
    """The LLM's response isn't valid JSON, or doesn't match the expected
    shape. A consolidation batch that fails to parse fails the job — visible
    and retryable — rather than silently updating nothing."""


def parse_consolidation_response(text: str) -> list[ConsolidationAction]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConsolidationError(f"response is not valid JSON: {exc}") from exc

    if not isinstance(raw, list):
        raise ConsolidationError(f"expected a JSON array, got {type(raw).__name__}")

    try:
        return [ConsolidationAction.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise ConsolidationError(f"response did not match the expected schema: {exc}") from exc
