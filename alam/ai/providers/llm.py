"""LLM provider Protocol.

``prompt_version_id`` is a required argument, not an optional one. CLAUDE.md
rule 6 says every LLM output records the prompt version that produced it, and
the cheapest way to make that hold is to make it impossible to obtain a
completion without naming one. The provider does not invent it — the caller
owns the prompt template and its version — and the response carries it back so
whatever persists the output already has it in hand.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


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
    """Text in, text out.

    Deliberately narrow. Structured/JSON output is what M2 extraction will
    want, and it is left out until that caller exists — guessing the shape now
    is how you get the wrong abstraction (ADR-0003's reasoning, applied to a
    different seam).
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
    ) -> Completion: ...
