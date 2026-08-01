"""Provider interfaces and their implementations.

All access to an LLM, an embedding model, or speech-to-text goes through a
Protocol here (CLAUDE.md rule 8). Callers depend on the Protocol, never on a
concrete client, which is what lets every later milestone be tested offline
with no API spend and no flaky tests.

The resolvers below are the single place a real implementation gets wired
in, and ``LLMProviderKind`` / ``EmbeddingProviderKind`` / ``SttProviderKind``
in ``config/settings.py`` constrain which vendor name is even legal — so a
real provider misconfigured before one exists fails at startup rather than
at first call.

``get_llm_provider()`` wraps its result in ``InstrumentedLLMProvider``
(M5.5a) so every ``.complete()`` call is recorded to ``llm_calls``, from
this one choke point, without any of the four call sites needing to know
instrumentation exists.

Every resolver also checks ``PAID_PROVIDER_KINDS`` before doing anything
else (M5.5a task 1) — selecting a paid vendor name is not, by itself,
enough to reach it. ``ALAM_ALLOW_PAID_PROVIDERS`` must also be true. The $0
constraint lives here, in code that runs on every resolution, not in
anyone's memory of which settings to leave alone.

``ollama`` / ``local`` / ``faster_whisper`` (M5.5a task 2) are $0 local
counterparts, never subject to that gate — see ``ai/providers/local/``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.ai.providers.embeddings import Embedding, EmbeddingProvider
from alam.ai.providers.fakes import (
    FakeEmbeddingProvider,
    FakeLLM,
    FakeSpeechToText,
    ProviderError,
)
from alam.ai.providers.instrumentation import InstrumentedLLMProvider
from alam.ai.providers.llm import Completion, LLMProvider
from alam.ai.providers.stt import SpeechToTextProvider, Transcript
from alam.config.settings import PAID_PROVIDER_KINDS, get_settings

if TYPE_CHECKING:
    from alam.config.settings import Settings

__all__ = [
    "Completion",
    "Embedding",
    "EmbeddingProvider",
    "FakeEmbeddingProvider",
    "FakeLLM",
    "FakeSpeechToText",
    "InstrumentedLLMProvider",
    "LLMProvider",
    "ProviderError",
    "ProviderNotPermittedError",
    "SpeechToTextProvider",
    "Transcript",
    "get_embedding_provider",
    "get_llm_provider",
    "get_stt_provider",
]


class ProviderNotPermittedError(RuntimeError):
    """A paid provider kind is configured but ``ALAM_ALLOW_PAID_PROVIDERS``
    is not set (M5.5a task 1). Fails closed: the default is refusal, not a
    warning that spend is about to happen."""


def _require_paid_providers_allowed(*, setting_name: str, kind: str, allowed: bool) -> None:
    if kind in PAID_PROVIDER_KINDS and not allowed:
        raise ProviderNotPermittedError(
            f"{setting_name}={kind!r} is a paid provider. Set "
            "ALAM_ALLOW_PAID_PROVIDERS=true to enable it — this may incur real cost."
        )


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    _require_paid_providers_allowed(
        setting_name="llm_provider",
        kind=settings.llm_provider,
        allowed=settings.allow_paid_providers,
    )
    if settings.llm_provider == "fake":
        return InstrumentedLLMProvider(FakeLLM())
    if settings.llm_provider == "anthropic":
        # Imported here, not at module level, so importing this package —
        # which every test does, including TestNoNetwork — never pulls in
        # the anthropic client for the (overwhelmingly common) "fake" path.
        from alam.ai.providers.real.anthropic_llm import AnthropicLLM

        assert settings.anthropic_api_key is not None  # enforced by Settings
        return InstrumentedLLMProvider(
            AnthropicLLM(
                api_key=settings.anthropic_api_key.get_secret_value(),
                model=settings.anthropic_model,
            )
        )
    if settings.llm_provider == "ollama":
        from alam.ai.providers.local.ollama_llm import OllamaLLM

        return InstrumentedLLMProvider(
            OllamaLLM(base_url=settings.ollama_base_url, model=settings.ollama_model)
        )
    raise ValueError(f"unknown llm provider: {settings.llm_provider!r}")


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    settings = settings or get_settings()
    _require_paid_providers_allowed(
        setting_name="embedding_provider",
        kind=settings.embedding_provider,
        allowed=settings.allow_paid_providers,
    )
    if settings.embedding_provider == "fake":
        return FakeEmbeddingProvider()
    if settings.embedding_provider == "voyage":
        from alam.ai.providers.real.voyage_embeddings import VoyageEmbeddingProvider

        assert settings.voyage_api_key is not None  # enforced by Settings
        return VoyageEmbeddingProvider(
            api_key=settings.voyage_api_key.get_secret_value(),
            model=settings.voyage_model,
        )
    if settings.embedding_provider == "local":
        from alam.ai.providers.local.local_embeddings import LocalEmbeddingProvider

        return LocalEmbeddingProvider(model=settings.local_embedding_model)
    raise ValueError(f"unknown embedding provider: {settings.embedding_provider!r}")


def get_stt_provider(settings: Settings | None = None) -> SpeechToTextProvider:
    settings = settings or get_settings()
    _require_paid_providers_allowed(
        setting_name="stt_provider",
        kind=settings.stt_provider,
        allowed=settings.allow_paid_providers,
    )
    if settings.stt_provider == "fake":
        return FakeSpeechToText()
    if settings.stt_provider == "openai":
        from alam.ai.providers.real.openai_stt import OpenAIWhisper

        assert settings.openai_api_key is not None  # enforced by Settings
        return OpenAIWhisper(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.whisper_model,
        )
    if settings.stt_provider == "faster_whisper":
        from alam.ai.providers.local.faster_whisper_stt import FasterWhisperSTT

        return FasterWhisperSTT(
            model=settings.faster_whisper_model,
            compute_type=settings.faster_whisper_compute_type,
        )
    raise ValueError(f"unknown stt provider: {settings.stt_provider!r}")
