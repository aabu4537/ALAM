"""OpenAI Whisper-backed ``SpeechToTextProvider`` (M5.5a).

Fits the existing Protocol without changes: ``entities`` biasing maps onto
the installed SDK's ``keywords`` parameter — a dedicated vocabulary-biasing
mechanism, more precise than stuffing the same list into ``prompt`` (an
older Whisper idiom this SDK version has moved past). Exactly what
``domain/entity_bias.py`` builds a list for. ``response_format="verbose_json"``
is what makes ``duration`` available; the default JSON response doesn't
include it, and ``Transcript.duration_seconds`` needs a real value, not a
guess from the byte count the way the fake derives one.

Optional parameters are omitted from the call entirely rather than passed
as ``None`` — the SDK types them ``str | Omit`` / ``SequenceNotStr[str] |
Omit``, not ``... | None``, and ``None`` is not a verified-equivalent value
for "not given" in this SDK version.

**Unverified assumption, not a Protocol gap:** ``captures.audio_data``
stores raw bytes with no captured content-type or container format
anywhere in the schema (no frontend recorder exists yet — M2 deferred the
PWA to M7, so nothing has ever produced a real capture to check this
against). This implementation assumes WAV. If the eventual recording
client produces something else (webm/opus is the common
``MediaRecorder`` default in browsers), this assumption is wrong and
transcription will fail or garble — flagged here rather than silently
shipped as solved.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

import openai

from alam.ai.providers.stt import Transcript

if TYPE_CHECKING:
    from collections.abc import Sequence


class OpenAIWhisper:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.model_name = model
        self._client = openai.OpenAI(api_key=api_key)

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
        # See the module docstring: WAV is an unverified assumption, not a
        # confirmed fact about what a real capture actually contains.
        audio_file = io.BytesIO(audio)
        audio_file.name = "capture.wav"

        optional_args: dict[str, Any] = {}
        if language is not None:
            optional_args["language"] = language
        if entities:
            optional_args["keywords"] = list(entities)

        response = self._client.audio.transcriptions.create(
            model=self.model_name,
            file=audio_file,
            response_format="verbose_json",
            **optional_args,
        )

        return Transcript(
            text=response.text,
            model=self.model_name,
            language=language,
            duration_seconds=getattr(response, "duration", None),
        )
