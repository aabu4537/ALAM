"""Real provider implementations (M5.5a): construction and Protocol
conformance only — never ``.complete()`` / ``.transcribe()`` / ``.embed()``,
which would be an actual network call and violate rule 8.

Sockets are blocked outright during these tests, the same guard
``TestNoNetwork`` uses in ``test_providers.py`` — so a real implementation
that turned out to need network I/O at construction time would fail here,
rather than that gap slipping through as "well, nothing exercises it."
"""

from __future__ import annotations

import socket

import pytest

from alam.ai.providers import (
    EmbeddingProvider,
    InstrumentedLLMProvider,
    LLMProvider,
    SpeechToTextProvider,
    get_embedding_provider,
    get_llm_provider,
    get_stt_provider,
)
from alam.ai.providers.real.anthropic_llm import AnthropicLLM
from alam.ai.providers.real.openai_stt import OpenAIWhisper
from alam.ai.providers.real.voyage_embeddings import VoyageEmbeddingProvider
from alam.config.settings import Settings


@pytest.fixture(autouse=True)
def _no_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("constructing a real provider attempted a network connection")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


class TestConstructionRequiresNoNetwork:
    def test_anthropic_llm_constructs(self) -> None:
        llm = AnthropicLLM(api_key="sk-test", model="claude-sonnet-4-5-20250929")

        assert llm.model == "claude-sonnet-4-5-20250929"
        assert isinstance(llm, LLMProvider)

    def test_openai_whisper_constructs(self) -> None:
        stt = OpenAIWhisper(api_key="sk-test", model="whisper-1")

        assert stt.model == "whisper-1"
        assert isinstance(stt, SpeechToTextProvider)

    def test_voyage_embedding_provider_constructs(self) -> None:
        provider = VoyageEmbeddingProvider(api_key="sk-test", model="voyage-3")

        assert provider.model == "voyage-3"
        assert provider.dimensions == 1024
        assert isinstance(provider, EmbeddingProvider)

    def test_voyage_rejects_an_unlisted_model(self) -> None:
        """Fails at construction, not on the first real embed call — the
        same fail-fast preference as everywhere else real providers meet
        unverified assumptions in this milestone."""
        with pytest.raises(ValueError, match="unknown Voyage model"):
            VoyageEmbeddingProvider(api_key="sk-test", model="voyage-nonexistent")


class TestResolversWireUpRealProviders:
    """Settings -> resolver -> concrete instance. Never calls the provider —
    that's the network call this test suite cannot make."""

    def test_llm_provider_anthropic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALAM_LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("ALAM_ANTHROPIC_API_KEY", "sk-test")
        settings = Settings()

        llm = get_llm_provider(settings)

        assert isinstance(llm, InstrumentedLLMProvider)
        assert isinstance(llm.inner, AnthropicLLM)
        assert llm.model == settings.anthropic_model

    def test_embedding_provider_voyage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALAM_EMBEDDING_PROVIDER", "voyage")
        monkeypatch.setenv("ALAM_VOYAGE_API_KEY", "sk-test")
        settings = Settings()

        provider = get_embedding_provider(settings)

        assert isinstance(provider, VoyageEmbeddingProvider)
        assert provider.model == settings.voyage_model

    def test_stt_provider_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ALAM_STT_PROVIDER", "openai")
        monkeypatch.setenv("ALAM_OPENAI_API_KEY", "sk-test")
        settings = Settings()

        stt = get_stt_provider(settings)

        assert isinstance(stt, OpenAIWhisper)
        assert stt.model == settings.whisper_model
