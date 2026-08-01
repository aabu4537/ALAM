"""Anthropic-backed ``LLMProvider`` (M5.5a).

``complete()`` maps directly onto ``messages.create()``, and ``Completion``'s
fields all come straight off the response — ``model`` (Anthropic echoes back
the concrete model id), ``usage.input_tokens`` / ``usage.output_tokens``.

One adaptation, not a Protocol change: Anthropic's API requires
``max_tokens``; the Protocol allows ``None`` (no other provider does,
today). ``_DEFAULT_MAX_TOKENS`` fills the gap when a caller doesn't specify
one — every current call site (extraction, correction, consolidation,
prediction resolution) already omits it and relies on the provider's
default, so this is where that default now lives.

``response_schema`` (follow-up to M5.5a) is satisfied via forced tool-use —
Anthropic has no ``response_format``-style parameter the way OpenAI/Ollama
do. A synthetic tool is built from the schema and ``tool_choice`` is forced
to it, so the model cannot respond with anything but a call to that tool;
the tool call's already-parsed ``input`` is re-serialized to a JSON string
for ``Completion.text``, keeping the Protocol's "text out" contract uniform
across providers regardless of which one had to route through a
schema-constraining mechanism that ordinarily produces structured data
directly. Not verified against a live call (no credential in this
environment) — verify against a real response before relying on it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import anthropic

from alam.ai.providers.llm import Completion

if TYPE_CHECKING:
    from collections.abc import Mapping

_DEFAULT_MAX_TOKENS = 4096
_SCHEMA_TOOL_NAME = "emit_structured_response"


class AnthropicLLM:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.model_name = model
        self._client = anthropic.Anthropic(api_key=api_key)

    @property
    def model(self) -> str:
        return self.model_name

    def complete(
        self,
        prompt: str,
        *,
        prompt_version_id: str,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        response_schema: Mapping[str, Any] | None = None,
    ) -> Completion:
        optional_args: dict[str, Any] = {}
        if response_schema is not None:
            optional_args["tools"] = [
                {
                    "name": _SCHEMA_TOOL_NAME,
                    "description": "Emit the structured response matching the required schema.",
                    "input_schema": dict(response_schema),
                }
            ]
            optional_args["tool_choice"] = {"type": "tool", "name": _SCHEMA_TOOL_NAME}

        response = self._client.messages.create(
            model=self.model_name,
            max_tokens=max_tokens or _DEFAULT_MAX_TOKENS,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
            **optional_args,
        )

        if response_schema is not None:
            [tool_use] = [block for block in response.content if block.type == "tool_use"]
            text = json.dumps(tool_use.input)
        else:
            text = "".join(block.text for block in response.content if block.type == "text")

        return Completion(
            text=text,
            model=response.model,
            prompt_version_id=prompt_version_id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
