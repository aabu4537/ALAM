"""Pure LLM cost estimation (M7 session 1).

No I/O — testable in milliseconds, per CLAUDE.md rule 3. Mirrors the shape
``ai/providers/real/voyage_embeddings.py``'s ``_MODEL_DIMENSIONS`` dict
already establishes: a small, explicit table keyed by model id, with the
same "verify against the vendor's current published pricing before relying
on this for a real spend decision" caveat that table carries — prices
drift, this is a snapshot, not a live lookup.

Deliberately LLM-only (a scope decision made directly with the user, M7
session 1): ``get_embedding_provider()``/``get_stt_provider()`` have no
equivalent instrumentation to `llm_calls`, so a Voyage embedding call or an
OpenAI Whisper transcription — both real spend under a paid provider — are
invisible to this module and to the cost view built on top of it
(``services/cost_view.py``). A known, documented gap, not a silent one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    input_per_million_usd: float
    output_per_million_usd: float


_FREE_PROVIDERS = frozenset({"fake", "ollama"})
"""``fake`` never leaves this process; ``ollama`` is local inference — both
are $0 by construction, regardless of which model string was configured
(``ollama_model`` is free text, not a fixed enum), never subject to
``PAID_PROVIDER_KINDS`` (``config/settings.py``)."""

_PRICING_BY_PROVIDER: dict[str, dict[str, ModelPricing]] = {
    "anthropic": {
        "claude-sonnet-4-5-20250929": ModelPricing(
            input_per_million_usd=3.00, output_per_million_usd=15.00
        ),
    },
}
"""Snapshot, not a live lookup — verify against Anthropic's current
published pricing before relying on this for a real spend decision, same
caveat ``voyage_embeddings.py`` carries for its own real client."""


def estimate_cost_usd(
    *, provider: str | None, model: str, input_tokens: int, output_tokens: int
) -> float | None:
    """``None`` means "cannot be priced" — an unrecognized ``(provider,
    model)`` pair, or a pre-migration row with no ``provider`` recorded.
    Never silently reported as ``0.0``; ``0.0`` is reserved for a
    genuinely free provider (``fake``/``ollama``), so a caller can tell
    "known to cost nothing" apart from "unknown, might cost something."
    """
    if provider in _FREE_PROVIDERS:
        return 0.0
    pricing = _PRICING_BY_PROVIDER.get(provider or "", {}).get(model)
    if pricing is None:
        return None
    return (
        input_tokens * pricing.input_per_million_usd
        + output_tokens * pricing.output_per_million_usd
    ) / 1_000_000
