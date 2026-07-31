"""Speech-to-text provider Protocol.

Audio in, text out. Nothing more.

Kept narrow on purpose. M2 needs a per-book entity list passed as a biasing
prompt — proper nouns invented by a novel are exactly what a general STT model
mangles — but that parameter is not added here. There is no caller for it yet,
and the kickoff's instruction is to widen when one exists. Adding a keyword
argument later is backward compatible; guessing its shape now is not free.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


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

    def transcribe(self, audio: bytes, *, language: str | None = None) -> Transcript: ...
