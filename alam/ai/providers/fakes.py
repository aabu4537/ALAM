"""Fake providers. The only implementations that exist in M0.

Three properties matter, and all three are why the fakes are written before any
real client (docs/milestones.md, M0):

**Deterministic.** The same input always produces the same output, derived by
hashing rather than by randomness. A fake that returns arbitrary values makes
every downstream test flaky for reasons unrelated to what it is testing.

**Observable.** Each records its calls, so a test can assert what a service
asked for — including that a prompt version was supplied — without a network
capture.

**Controllable.** Each can be told to fail, so retry and error paths are
testable. Those paths are otherwise only exercised in production.

No network, no API keys, no client libraries. ``tests/test_providers.py``
enforces that by disabling sockets.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from alam.ai.providers.embeddings import Embedding
from alam.ai.providers.llm import Completion
from alam.ai.providers.stt import Transcript

if TYPE_CHECKING:
    from collections.abc import Sequence

FAKE_LLM_MODEL = "fake-llm-v1"
FAKE_EMBEDDING_MODEL = "fake-embedding-v1"
FAKE_EMBEDDING_VERSION = "1"
FAKE_STT_MODEL = "fake-stt-v1"

DEFAULT_DIMENSIONS = 1536
"""Matches the width of common production embedding models, so the pgvector
column M3 creates is realistic rather than a toy that has to be migrated."""


class ProviderError(RuntimeError):
    """Raised by a fake told to fail. Stands in for any provider-side error."""


def _digest(*parts: str) -> bytes:
    return hashlib.sha256("\x1f".join(parts).encode()).digest()


@dataclass
class LLMCall:
    prompt: str
    prompt_version_id: str
    max_tokens: int | None
    temperature: float


@dataclass
class FakeLLM:
    """Deterministic stand-in for a language model.

    Returns queued responses if any were supplied, otherwise a stable string
    derived from the prompt.
    """

    responses: list[str] = field(default_factory=list)
    fail_with: Exception | None = None
    calls: list[LLMCall] = field(default_factory=list)

    @property
    def model(self) -> str:
        return FAKE_LLM_MODEL

    def complete(
        self,
        prompt: str,
        *,
        prompt_version_id: str,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> Completion:
        self.calls.append(LLMCall(prompt, prompt_version_id, max_tokens, temperature))

        if self.fail_with is not None:
            raise self.fail_with

        text = self.responses.pop(0) if self.responses else self._default_text(prompt)

        return Completion(
            text=text,
            model=self.model,
            prompt_version_id=prompt_version_id,
            input_tokens=len(prompt.split()),
            output_tokens=len(text.split()),
        )

    @staticmethod
    def _default_text(prompt: str) -> str:
        return f"fake completion {_digest(prompt).hex()[:12]}"


@dataclass
class FakeEmbeddingProvider:
    """Deterministic unit vectors derived from the input text.

    Unit length because cosine similarity is what M3 will use, and vectors of
    varying magnitude would make similarity scores depend on text length.
    Identical text yields an identical vector; different text yields a
    different one — enough to test retrieval plumbing without pretending to
    model semantics.
    """

    dimensions_: int = DEFAULT_DIMENSIONS
    fail_with: Exception | None = None
    calls: list[list[str]] = field(default_factory=list)

    @property
    def model(self) -> str:
        return FAKE_EMBEDDING_MODEL

    @property
    def version(self) -> str:
        return FAKE_EMBEDDING_VERSION

    @property
    def dimensions(self) -> int:
        return self.dimensions_

    def embed(self, texts: Sequence[str]) -> list[Embedding]:
        self.calls.append(list(texts))

        if self.fail_with is not None:
            raise self.fail_with

        return [
            Embedding(
                vector=self._vector(text),
                model=self.model,
                version=self.version,
                dimensions=self.dimensions_,
            )
            for text in texts
        ]

    def _vector(self, text: str) -> list[float]:
        # Stretch the digest to the required width, then normalise.
        raw: list[float] = []
        counter = 0
        while len(raw) < self.dimensions_:
            block = _digest(text, str(counter))
            raw.extend((b - 127.5) / 127.5 for b in block)
            counter += 1
        raw = raw[: self.dimensions_]

        norm = math.sqrt(sum(v * v for v in raw))
        if norm == 0:  # pragma: no cover - unreachable for sha256 output
            return raw
        return [v / norm for v in raw]


@dataclass
class STTCall:
    audio: bytes
    language: str | None
    entities: tuple[str, ...]


@dataclass
class FakeSpeechToText:
    """Deterministic transcription.

    Real audio never reaches this, so the transcript is derived from the bytes.
    Queued transcripts let a test supply realistic prose where the content
    matters — extraction tests, mainly.
    """

    transcripts: list[str] = field(default_factory=list)
    fail_with: Exception | None = None
    calls: list[STTCall] = field(default_factory=list)

    @property
    def model(self) -> str:
        return FAKE_STT_MODEL

    def transcribe(
        self,
        audio: bytes,
        *,
        language: str | None = None,
        entities: Sequence[str] | None = None,
    ) -> Transcript:
        self.calls.append(STTCall(audio=audio, language=language, entities=tuple(entities or ())))

        if self.fail_with is not None:
            raise self.fail_with

        text = (
            self.transcripts.pop(0)
            if self.transcripts
            else f"fake transcript {hashlib.sha256(audio).hexdigest()[:12]}"
        )

        return Transcript(
            text=text,
            model=self.model,
            language=language,
            duration_seconds=len(audio) / 16000.0,
        )
