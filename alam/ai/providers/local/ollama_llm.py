"""Ollama-backed ``LLMProvider`` (M5.5a task 2), reusing the ``openai``
client already installed for Whisper (task 3) rather than a parallel HTTP
client — Ollama exposes an OpenAI-compatible ``/v1/chat/completions``
endpoint, and the installed SDK version's ``OpenAI(base_url=...)`` needs
nothing else to point at it. Verified against the installed SDK's actual
``chat.completions.create`` signature and ``ChatCompletion`` response shape
(``usage.prompt_tokens`` / ``usage.completion_tokens``, OpenAI's naming —
different words than Anthropic's ``input_tokens`` / ``output_tokens`` for
the same thing, mapped onto ``Completion`` either way).

Two structured-output paths, not one, both empirically verified against a
live Ollama server (curl, this session — a schema with ``$defs``/``$ref``
round-trips correctly through Ollama's OpenAI-compat layer):

**``response_schema`` given (follow-up to M5.5a):** ``response_format={"type":
"json_schema", "json_schema": {...}}`` — real grammar-constrained decoding,
not just an instruction to the model. Extraction uses this path.

**``response_schema`` absent, but ``prompt_version_id`` is one of
``_JSON_MODE_PROMPT_VERSIONS``:** the older, weaker ``{"type":
"json_object"}`` mode — guarantees valid JSON, not any particular shape.
Consolidation and prediction resolution still use this path; not converted
in this change. Built from the prompt modules' own ``PROMPT_VERSION_ID``
constants so it can't silently drift out of sync with a version bump.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import openai

from alam.ai.prompts.consolidation import PROMPT_VERSION_ID as _CONSOLIDATION_PROMPT_VERSION_ID
from alam.ai.prompts.prediction_resolution import (
    PROMPT_VERSION_ID as _PREDICTION_RESOLUTION_PROMPT_VERSION_ID,
)
from alam.ai.providers.llm import Completion

if TYPE_CHECKING:
    from collections.abc import Mapping

_DEFAULT_MAX_TOKENS = 4096

_JSON_MODE_PROMPT_VERSIONS = frozenset(
    {
        _CONSOLIDATION_PROMPT_VERSION_ID,
        _PREDICTION_RESOLUTION_PROMPT_VERSION_ID,
    }
)
"""Extraction is deliberately absent now — it passes response_schema and
uses the stronger constrained-decoding path above instead. entity-correction
is absent for the original reason: it produces a corrected transcript, not
JSON, and forcing JSON mode on it would break the one call site that wants
plain text back."""


class OllamaLLM:
    def __init__(self, *, base_url: str, model: str) -> None:
        self.model_name = model
        # api_key is required by the SDK's constructor but unchecked by
        # Ollama's server — any non-empty string works.
        self._client = openai.OpenAI(base_url=base_url, api_key="ollama")

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
        # Built as a plain dict and passed via **kwargs, not a typed
        # ChatCompletionMessageParam list — mypy widens a literal dict's
        # "role" to `str`, which the SDK's overloaded `create()` then
        # rejects; going through `Any` here is simpler than importing and
        # constructing the exact TypedDict for one message.
        optional_args: dict[str, Any] = {}
        if response_schema is not None:
            optional_args["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "schema": dict(response_schema)},
            }
        elif prompt_version_id in _JSON_MODE_PROMPT_VERSIONS:
            optional_args["response_format"] = {"type": "json_object"}

        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens or _DEFAULT_MAX_TOKENS,
            **optional_args,
        )
        choice = response.choices[0]
        usage = response.usage

        return Completion(
            text=choice.message.content or "",
            model=response.model,
            prompt_version_id=prompt_version_id,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )
