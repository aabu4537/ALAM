"""Anthropic-backed ``LLMProvider`` (M5.5a).

Fits the existing Protocol without changes: ``complete()`` maps directly
onto ``messages.create()``, and ``Completion``'s fields all come straight
off the response — ``model`` (Anthropic echoes back the concrete model
id), ``usage.input_tokens`` / ``usage.output_tokens``.

One adaptation, not a Protocol change: Anthropic's API requires
``max_tokens``; the Protocol allows ``None`` (no other provider does,
today). ``_DEFAULT_MAX_TOKENS`` fills the gap when a caller doesn't specify
one — every current call site (extraction, correction, consolidation,
prediction resolution) already omits it and relies on the provider's
default, so this is where that default now lives.
"""

from __future__ import annotations

import anthropic

from alam.ai.providers.llm import Completion

_DEFAULT_MAX_TOKENS = 4096


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
    ) -> Completion:
        response = self._client.messages.create(
            model=self.model_name,
            max_tokens=max_tokens or _DEFAULT_MAX_TOKENS,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")

        return Completion(
            text=text,
            model=response.model,
            prompt_version_id=prompt_version_id,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
