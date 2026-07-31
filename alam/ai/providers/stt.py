"""Speech-to-text provider Protocol.

Audio in, text out — plus an optional biasing entity list, widened here now
that M2 session 2 is the caller the original docstring deferred to. Proper
nouns invented by a novel are exactly what a general STT model mangles; a
per-book list of chapter labels, title, and author (``domain/entity_bias.py``)
is the cheapest available signal to bias toward, given nothing else has been
extracted yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from collections.abc import Sequence


class Transcript(BaseModel):
    model_config = {"frozen": True}

    text: str

    model: str
    """Which model produced this. Transcription quality varies enough between
    versions that a memory extracted from a bad transcript needs to be
    traceable to it."""

    language: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)


@runtime_checkable
class SpeechToTextProvider(Protocol):
    @property
    def model(self) -> str: ...

    def transcribe(
        self,
        audio: bytes,
        *,
        language: str | None = None,
        entities: Sequence[str] | None = None,
    ) -> Transcript: ...
