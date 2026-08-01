"""Transcript -> typed memories (M2 session 3).

Parses and validates an LLM's JSON response against ADR-0001's fixed enum.
Pure — no I/O, no ORM — so extraction accuracy is testable in milliseconds
against hand-written JSON, without a model in the loop. Deliberately its own
``MemoryType``, distinct from ``persistence.models.memory.MemoryType``: this
module sits alongside ``domain/`` in spirit (see CLAUDE.md rule 3) and must
not import the ORM. ``services/capture_pipeline.py`` maps between the two
when persisting — the same pattern ``domain/structure_review.py``'s
``DesiredUnit`` already uses relative to ``MediaStructureUnit``.
"""

from __future__ import annotations

import enum
import json
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError


class MemoryType(enum.StrEnum):
    PREDICTION = "prediction"
    OPINION = "opinion"
    EMOTIONAL_REACTION = "emotional_reaction"
    CONFUSION = "confusion"
    CHARACTER_JUDGMENT = "character_judgment"
    FAVORITE_MOMENT = "favorite_moment"
    META_COMMENT = "meta_comment"
    OTHER = "other"


class ExtractedMemory(BaseModel):
    model_config = {"frozen": True}

    memory_type: MemoryType
    content: str


EXTRACTION_RESPONSE_SCHEMA: dict[str, Any] = TypeAdapter(list[ExtractedMemory]).json_schema()
"""The JSON Schema a schema-constrained provider is given for extraction
(follow-up to M5.5a) — generated from ``ExtractedMemory`` itself, not
hand-written, so the schema a provider is constrained to and the schema
``parse_extraction_response`` below expects can never drift apart. An empty
array is valid against this schema (no minItems), matching the prompt's own
"most transcripts yield one or two memories... return [] if none apply"."""


class ExtractionError(ValueError):
    """The LLM's response isn't valid JSON, or doesn't match the expected
    shape. A capture that fails extraction fails the job — visible and
    retryable — rather than silently producing zero memories."""


def parse_extraction_response(text: str) -> list[ExtractedMemory]:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"response is not valid JSON: {exc}") from exc

    if not isinstance(raw, list):
        raise ExtractionError(f"expected a JSON array, got {type(raw).__name__}")

    try:
        return [ExtractedMemory.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise ExtractionError(f"response did not match the expected schema: {exc}") from exc
