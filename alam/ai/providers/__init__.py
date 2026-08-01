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
from alam.config.settings import get_settings

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
    "SpeechToTextProvider",
    "Transcript",
    "get_embedding_provider",
    "get_llm_provider",
    "get_stt_provider",
]


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    if settings.llm_provider == "fake":
        return InstrumentedLLMProvider(FakeLLM())
    raise ValueError(f"unknown llm provider: {settings.llm_provider!r}")


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    settings = settings or get_settings()
    if settings.embedding_provider == "fake":
        return FakeEmbeddingProvider()
    raise ValueError(f"unknown embedding provider: {settings.embedding_provider!r}")


def get_stt_provider(settings: Settings | None = None) -> SpeechToTextProvider:
    settings = settings or get_settings()
    if settings.stt_provider == "fake":
        return FakeSpeechToText()
    raise ValueError(f"unknown stt provider: {settings.stt_provider!r}")
