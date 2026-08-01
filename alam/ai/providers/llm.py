"""LLM provider Protocol.

``prompt_version_id`` is a required argument, not an optional one. CLAUDE.md
rule 6 says every LLM output records the prompt version that produced it, and
the cheapest way to make that hold is to make it impossible to obtain a
completion without naming one. The provider does not invent it — the caller
owns the prompt template and its version — and the response carries it back so
whatever persists the output already has it in hand.

``response_schema`` (follow-up to M5.5a) is an optional JSON Schema dict a
caller passes when it wants the response constrained to a specific shape,
not just asked for one in prose. Each provider satisfies it with whatever
native mechanism it has — Ollama's ``format`` parameter (via
``response_format={"type":"json_schema",...}`` on its OpenAI-compatible
endpoint), Anthropic's forced tool-use, OpenAI's ``response_format`` — so
``Completion.text`` is still always a plain string; how it got
schema-constrained is the provider's business, not the caller's. ``None``
means "no constraint," the same free-text behavior every caller had before
this existed. Extraction is the first (and, as of this change, only) real
caller — see ``ai/extraction/memories.py``'s ``EXTRACTION_RESPONSE_SCHEMA``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import jsonschema
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any


class Completion(BaseModel):
    """One LLM response, with everything needed to persist it honestly."""

    model_config = {"frozen": True}

    text: str

    model: str
    """Concrete model identifier, not a family. Recorded so an output can be
    attributed after a model migration."""

    prompt_version_id: str
    """Echoed from the request. See the module docstring and rule 6."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    """Token accounting is required for M7's cost view, and retrofitting it
    means losing the history that makes the view worth having."""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@runtime_checkable
class LLMProvider(Protocol):
    """Text in, text out — optionally shape-constrained via
    ``response_schema``. Was "deliberately narrow" with structured output
    left out until a real caller existed (ADR-0003's reasoning about
    guessing the wrong abstraction, applied to this seam); extraction is
    now that caller.
    """

    @property
    def model(self) -> str: ...

    def complete(
        self,
        prompt: str,
        *,
        prompt_version_id: str,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        response_schema: Mapping[str, Any] | None = None,
    ) -> Completion: ...


class SchemaValidationError(ValueError):
    """A fake's canned response doesn't conform to the ``response_schema``
    the caller asked for. A fake must not be able to return a shape no real
    provider, constrained by the same schema, could ever produce — silently
    accepting a non-conforming canned response would make a test pass
    against a shape production can't reach.
    """


def validate_against_schema(text: str, schema: Mapping[str, Any]) -> None:
    """Raises ``SchemaValidationError`` if ``text`` isn't JSON matching
    ``schema``. Used by fake providers only (M5.5a follow-up) — real
    providers rely on their own constrained-decoding mechanism instead of
    a second, client-side check of output they didn't choose the shape of."""
    try:
        instance = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SchemaValidationError(f"canned response is not valid JSON: {exc}") from exc

    try:
        jsonschema.validate(instance=instance, schema=schema)
    except jsonschema.ValidationError as exc:
        raise SchemaValidationError(
            f"canned response does not conform to response_schema: {exc.message}"
        ) from exc
