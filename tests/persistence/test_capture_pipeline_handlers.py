from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from alam.ai.providers.fakes import FakeLLM, FakeSpeechToText, ProviderError
from alam.jobs.job_types import CORRECT_TRANSCRIPT
from alam.persistence.models.capture import CaptureStatus
from alam.persistence.models.job import Job
from alam.persistence.repositories import (
    CaptureRepository,
    MediaItemRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)
from alam.services.capture_pipeline import (
    CapturePipelineError,
    correct_transcript,
    transcribe_capture,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from alam.persistence.models import Capture, MediaItem, MediaStructureUnit, User


@pytest.fixture
def owner(session: Session) -> User:
    return UserRepository(session).create(display_name="Owner")


@pytest.fixture
def book(session: Session, owner: User) -> MediaItem:
    return MediaItemRepository(session).create(
        user_id=owner.id, title="Dune", attributes={"author": "Frank Herbert"}
    )


@pytest.fixture
def chapters(session: Session, book: MediaItem) -> list[MediaStructureUnit]:
    repo = StructureUnitRepository(session)
    return [
        repo.create(media_item_id=book.id, ordinal=i, label=label)
        for i, label in enumerate(["Part One: Dune", "Part Two: Muad'Dib"], start=1)
    ]


@pytest.fixture
def capture(session: Session, book: MediaItem, chapters: list[MediaStructureUnit]) -> Capture:
    reading_session = ReadingSessionRepository(session).get_or_create_active(
        book.id, structure_unit_id=chapters[0].id, ordinal=1, progress=0.5
    )
    return CaptureRepository(session).create(
        reading_session_id=reading_session.id,
        media_item_id=book.id,
        structure_unit_id=chapters[0].id,
        structure_ordinal=1,
        audio_data=b"raw-audio-bytes",
    )


class TestTranscribeCapture:
    def test_records_the_transcript_and_advances_status(
        self, session: Session, capture: Capture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_stt = FakeSpeechToText(transcripts=["I think the guy is lying about the water."])
        monkeypatch.setattr("alam.services.capture_pipeline.get_stt_provider", lambda: fake_stt)

        transcribe_capture(session, {"capture_id": str(capture.id)})

        assert capture.raw_transcript == "I think the guy is lying about the water."
        assert capture.transcript_model == fake_stt.model
        assert capture.status is CaptureStatus.TRANSCRIBED

    def test_biases_on_title_author_and_chapter_labels(
        self, session: Session, capture: Capture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_stt = FakeSpeechToText()
        monkeypatch.setattr("alam.services.capture_pipeline.get_stt_provider", lambda: fake_stt)

        transcribe_capture(session, {"capture_id": str(capture.id)})

        assert fake_stt.calls[0].entities == (
            "Dune",
            "Frank Herbert",
            "Part One: Dune",
            "Part Two: Muad'Dib",
        )

    def test_enqueues_the_correction_job(
        self, session: Session, capture: Capture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "alam.services.capture_pipeline.get_stt_provider", lambda: FakeSpeechToText()
        )

        transcribe_capture(session, {"capture_id": str(capture.id)})

        jobs = session.scalars(select(Job).where(Job.job_type == CORRECT_TRANSCRIPT)).all()
        assert len(jobs) == 1
        assert jobs[0].payload == {"capture_id": str(capture.id)}

    def test_provider_failure_propagates_for_the_runner_to_record(
        self, session: Session, capture: Capture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "alam.services.capture_pipeline.get_stt_provider",
            lambda: FakeSpeechToText(fail_with=ProviderError("audio too short")),
        )

        with pytest.raises(ProviderError):
            transcribe_capture(session, {"capture_id": str(capture.id)})

    def test_unknown_capture_id_is_an_ordinary_failure(self, session: Session) -> None:
        with pytest.raises(CapturePipelineError):
            transcribe_capture(session, {"capture_id": str(uuid.uuid4())})


class TestCorrectTranscript:
    def test_records_the_corrected_transcript_and_advances_status(
        self, session: Session, capture: Capture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        CaptureRepository(session).mark_transcribed(
            capture, raw_transcript="the mud dib guy", transcript_model="fake-stt-v1"
        )
        fake_llm = FakeLLM(responses=["The Muad'Dib guy"])
        monkeypatch.setattr("alam.services.capture_pipeline.get_llm_provider", lambda: fake_llm)

        correct_transcript(session, {"capture_id": str(capture.id)})

        assert capture.corrected_transcript == "The Muad'Dib guy"
        assert capture.status is CaptureStatus.CORRECTED

    def test_prompt_includes_the_entity_list(
        self, session: Session, capture: Capture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        CaptureRepository(session).mark_transcribed(
            capture, raw_transcript="the mud dib guy", transcript_model="fake-stt-v1"
        )
        fake_llm = FakeLLM()
        monkeypatch.setattr("alam.services.capture_pipeline.get_llm_provider", lambda: fake_llm)

        correct_transcript(session, {"capture_id": str(capture.id)})

        assert "Muad'Dib" in fake_llm.calls[0].prompt
        assert "the mud dib guy" in fake_llm.calls[0].prompt

    def test_records_the_prompt_version_id(
        self, session: Session, capture: Capture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        CaptureRepository(session).mark_transcribed(
            capture, raw_transcript="x", transcript_model="fake-stt-v1"
        )
        fake_llm = FakeLLM()
        monkeypatch.setattr("alam.services.capture_pipeline.get_llm_provider", lambda: fake_llm)

        correct_transcript(session, {"capture_id": str(capture.id)})

        assert fake_llm.calls[0].prompt_version_id == "entity-correction-v1"

    def test_running_before_transcription_is_rejected(
        self, session: Session, capture: Capture
    ) -> None:
        with pytest.raises(CapturePipelineError, match="not been transcribed"):
            correct_transcript(session, {"capture_id": str(capture.id)})

    def test_unknown_capture_id_is_an_ordinary_failure(self, session: Session) -> None:
        with pytest.raises(CapturePipelineError):
            correct_transcript(session, {"capture_id": str(uuid.uuid4())})
