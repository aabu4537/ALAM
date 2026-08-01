"""Provider Protocols and their fakes.

No database, no network. The final class enforces the second half of that.
"""

from __future__ import annotations

import socket

import pytest

from alam.ai.providers import (
    EmbeddingProvider,
    FakeEmbeddingProvider,
    FakeLLM,
    FakeSpeechToText,
    InstrumentedLLMProvider,
    LLMProvider,
    ProviderError,
    SpeechToTextProvider,
    get_embedding_provider,
    get_llm_provider,
    get_stt_provider,
)

PROMPT_V = "extract-memories@v1"


class TestProtocolConformance:
    def test_fakes_satisfy_their_protocols(self) -> None:
        assert isinstance(FakeLLM(), LLMProvider)
        assert isinstance(FakeEmbeddingProvider(), EmbeddingProvider)
        assert isinstance(FakeSpeechToText(), SpeechToTextProvider)

    def test_resolvers_return_the_fakes(self) -> None:
        """``get_llm_provider()`` wraps the fake in ``InstrumentedLLMProvider``
        (M5.5a) — the underlying fake is still what actually answers, just
        not what the resolver hands back directly."""
        llm = get_llm_provider()
        assert isinstance(llm, InstrumentedLLMProvider)
        assert isinstance(llm.inner, FakeLLM)
        assert isinstance(get_embedding_provider(), FakeEmbeddingProvider)
        assert isinstance(get_stt_provider(), FakeSpeechToText)

    def test_callers_can_depend_on_the_protocol_alone(self) -> None:
        """Type-level intent, checked at runtime: a service should accept any
        provider, never a concrete class."""

        def summarise(llm: LLMProvider, text: str) -> str:
            return llm.complete(text, prompt_version_id=PROMPT_V).text

        assert summarise(FakeLLM(responses=["a summary"]), "some text") == "a summary"


class TestLLM:
    def test_prompt_version_is_echoed_back(self) -> None:
        """Rule 6. The caller cannot obtain a completion without naming a
        prompt version, and gets it back attached to the output it must store.
        """
        result = FakeLLM().complete("hello", prompt_version_id=PROMPT_V)

        assert result.prompt_version_id == PROMPT_V

    def test_prompt_version_is_required(self) -> None:
        with pytest.raises(TypeError):
            FakeLLM().complete("hello")  # type: ignore[call-arg]

    def test_output_records_its_model(self) -> None:
        assert FakeLLM().complete("hello", prompt_version_id=PROMPT_V).model == "fake-llm-v1"

    def test_token_counts_are_populated(self) -> None:
        """M7 needs cost accounting, and it cannot be backfilled."""
        result = FakeLLM().complete("one two three", prompt_version_id=PROMPT_V)

        assert result.input_tokens == 3
        assert result.total_tokens == result.input_tokens + result.output_tokens

    def test_same_prompt_gives_the_same_answer(self) -> None:
        a = FakeLLM().complete("stable", prompt_version_id=PROMPT_V)
        b = FakeLLM().complete("stable", prompt_version_id=PROMPT_V)

        assert a.text == b.text

    def test_different_prompts_give_different_answers(self) -> None:
        a = FakeLLM().complete("one", prompt_version_id=PROMPT_V)
        b = FakeLLM().complete("two", prompt_version_id=PROMPT_V)

        assert a.text != b.text

    def test_queued_responses_are_returned_in_order(self) -> None:
        llm = FakeLLM(responses=["first", "second"])

        assert llm.complete("x", prompt_version_id=PROMPT_V).text == "first"
        assert llm.complete("y", prompt_version_id=PROMPT_V).text == "second"

    def test_calls_are_recorded_for_assertion(self) -> None:
        llm = FakeLLM()
        llm.complete("ask", prompt_version_id=PROMPT_V, temperature=0.7, max_tokens=100)

        assert len(llm.calls) == 1
        assert llm.calls[0].prompt == "ask"
        assert llm.calls[0].temperature == 0.7
        assert llm.calls[0].max_tokens == 100

    def test_failure_can_be_forced(self) -> None:
        """Retry paths are otherwise only exercised in production."""
        llm = FakeLLM(fail_with=ProviderError("upstream is down"))

        with pytest.raises(ProviderError, match="upstream is down"):
            llm.complete("x", prompt_version_id=PROMPT_V)

    def test_completions_are_immutable(self) -> None:
        result = FakeLLM().complete("x", prompt_version_id=PROMPT_V)

        with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError
            result.text = "tampered"  # type: ignore[misc]


class TestEmbeddings:
    def test_model_and_version_are_recorded(self) -> None:
        """Rule 7. Without both, a model migration is stop-the-world because no
        row can be identified as needing re-embedding."""
        [embedding] = FakeEmbeddingProvider().embed(["text"])

        assert embedding.model == "fake-embedding-v1"
        assert embedding.version == "1"

    def test_vector_width_matches_the_declared_dimensions(self) -> None:
        provider = FakeEmbeddingProvider()
        [embedding] = provider.embed(["text"])

        assert len(embedding.vector) == provider.dimensions
        assert embedding.dimensions == provider.dimensions

    def test_dimensions_are_configurable(self) -> None:
        """M3 fixes the pgvector column width from this value."""
        provider = FakeEmbeddingProvider(dimensions_=768)
        [embedding] = provider.embed(["text"])

        assert len(embedding.vector) == 768

    def test_vectors_are_unit_length(self) -> None:
        """Cosine similarity should not depend on how long the text was."""
        [embedding] = FakeEmbeddingProvider().embed(["some text"])
        norm = sum(v * v for v in embedding.vector) ** 0.5

        assert norm == pytest.approx(1.0, abs=1e-9)

    def test_identical_text_gives_an_identical_vector(self) -> None:
        a = FakeEmbeddingProvider().embed(["same"])[0].vector
        b = FakeEmbeddingProvider().embed(["same"])[0].vector

        assert a == b

    def test_different_text_gives_a_different_vector(self) -> None:
        [a, b] = FakeEmbeddingProvider().embed(["one", "two"])

        assert a.vector != b.vector

    def test_batching_preserves_input_order(self) -> None:
        texts = ["alpha", "beta", "gamma"]
        batched = FakeEmbeddingProvider().embed(texts)
        one_at_a_time = [FakeEmbeddingProvider().embed([t])[0] for t in texts]

        assert [e.vector for e in batched] == [e.vector for e in one_at_a_time]

    def test_empty_batch_returns_nothing(self) -> None:
        assert FakeEmbeddingProvider().embed([]) == []

    def test_failure_can_be_forced(self) -> None:
        provider = FakeEmbeddingProvider(fail_with=ProviderError("rate limited"))

        with pytest.raises(ProviderError):
            provider.embed(["x"])


class TestSpeechToText:
    def test_transcript_records_its_model(self) -> None:
        assert FakeSpeechToText().transcribe(b"audio").model == "fake-stt-v1"

    def test_same_audio_gives_the_same_transcript(self) -> None:
        a = FakeSpeechToText().transcribe(b"audio").text
        b = FakeSpeechToText().transcribe(b"audio").text

        assert a == b

    def test_queued_transcripts_let_a_test_supply_real_prose(self) -> None:
        stt = FakeSpeechToText(transcripts=["I think the narrator is lying."])

        assert stt.transcribe(b"...").text == "I think the narrator is lying."

    def test_language_is_passed_through(self) -> None:
        assert FakeSpeechToText().transcribe(b"x", language="en").language == "en"

    def test_failure_can_be_forced(self) -> None:
        stt = FakeSpeechToText(fail_with=ProviderError("audio too short"))

        with pytest.raises(ProviderError):
            stt.transcribe(b"x")

    def test_biasing_entities_are_recorded_for_the_caller_to_assert_on(self) -> None:
        stt = FakeSpeechToText()

        stt.transcribe(b"x", entities=["Muad'Dib", "Arrakis"])

        assert stt.calls[0].entities == ("Muad'Dib", "Arrakis")

    def test_no_entities_records_an_empty_tuple_rather_than_none(self) -> None:
        stt = FakeSpeechToText()

        stt.transcribe(b"x")

        assert stt.calls[0].entities == ()


class TestNoNetwork:
    """Rule 8, enforced rather than asserted.

    Sockets are disabled outright, so a real client smuggled in behind any of
    these Protocols fails here rather than in CI as an intermittent timeout —
    or worse, succeeds and quietly spends money.
    """

    @pytest.fixture(autouse=True)
    def _no_sockets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def blocked(*args: object, **kwargs: object) -> None:
            raise AssertionError("a provider attempted a network connection")

        monkeypatch.setattr(socket, "socket", blocked)
        monkeypatch.setattr(socket, "create_connection", blocked)

    def test_every_fake_works_with_networking_disabled(self) -> None:
        assert FakeLLM().complete("x", prompt_version_id=PROMPT_V).text
        assert FakeEmbeddingProvider().embed(["x"])[0].vector
        assert FakeSpeechToText().transcribe(b"x").text

    def test_the_guard_itself_works(self) -> None:
        """Without this, the test above would pass even if the patch silently
        stopped applying."""
        with pytest.raises(AssertionError, match="network connection"):
            socket.socket()
