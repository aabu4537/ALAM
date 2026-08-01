"""faster-whisper-backed ``SpeechToTextProvider`` (M5.5a task 2). CPU
inference via CTranslate2 — no GPU assumed for a personal dev machine.

Fits the existing Protocol without changes: ``entities`` biasing maps onto
``initial_prompt`` — faster-whisper's actual biasing mechanism. It wraps
the Whisper model directly rather than a hosted API, so it has no
``keywords`` parameter the way ``ai/providers/real/openai_stt.py``'s cloud
client does; ``initial_prompt`` is the whisper.cpp-era mechanism that
implementation moved past.

Same unverified assumption as the real OpenAI implementation:
``captures.audio_data`` has no recorded container format anywhere in the
schema, and no frontend recorder exists yet to check one against. Passed
through as a raw byte stream rather than assumed to be a specific
container — faster-whisper's decoder handles format detection itself, so
this is somewhat more tolerant than hardcoding WAV, but still unverified
against a real capture.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from faster_whisper import WhisperModel

from alam.ai.providers.stt import Transcript

if TYPE_CHECKING:
    from collections.abc import Sequence


class FasterWhisperSTT:
    def __init__(self, *, model: str, compute_type: str) -> None:
        self.model_name = model
        self._model = WhisperModel(model, compute_type=compute_type)

    @property
    def model(self) -> str:
        return self.model_name

    def transcribe(
        self,
        audio: bytes,
        *,
        language: str | None = None,
        entities: Sequence[str] | None = None,
    ) -> Transcript:
        segments, info = self._model.transcribe(
            io.BytesIO(audio),
            language=language,
            initial_prompt=", ".join(entities) if entities else None,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()

        return Transcript(
            text=text,
            model=self.model_name,
            language=language or info.language,
            duration_seconds=info.duration,
        )
