from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from alam.ai.providers.fakes import FakeLLM, FakeSpeechToText, ProviderError
from alam.jobs.job_types import CORRECT_TRANSCRIPT, EXTRACT_MEMORIES
from alam.persistence.models.capture import CaptureStatus
from alam.persistence.models.job import Job
from alam.persistence.repositories import (
    CaptureRepository,
    MediaItemRepository,
    MemoryRepository,
    ReadingSessionRepository,
    StructureUnitRepository,
    UserRepository,
)
from alam.services.capture_pipeline import (
    CapturePipelineError,
    correct_transcript,
    extract_memories,
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

    def test_enqueues_the_extraction_job(
        self, session: Session, capture: Capture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        CaptureRepository(session).mark_transcribed(
            capture, raw_transcript="x", transcript_model="fake-stt-v1"
        )
        monkeypatch.setattr("alam.services.capture_pipeline.get_llm_provider", lambda: FakeLLM())

        correct_transcript(session, {"capture_id": str(capture.id)})

        jobs = session.scalars(select(Job).where(Job.job_type == EXTRACT_MEMORIES)).all()
        assert len(jobs) == 1
        assert jobs[0].payload == {"capture_id": str(capture.id)}

    def test_running_before_transcription_is_rejected(
        self, session: Session, capture: Capture
    ) -> None:
        with pytest.raises(CapturePipelineError, match="not been transcribed"):
            correct_transcript(session, {"capture_id": str(capture.id)})

    def test_unknown_capture_id_is_an_ordinary_failure(self, session: Session) -> None:
        with pytest.raises(CapturePipelineError):
            correct_transcript(session, {"capture_id": str(uuid.uuid4())})


class TestExtractMemories:
    def test_persists_one_memory_row_per_extracted_item_and_advances_status(
        self, session: Session, capture: Capture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        CaptureRepository(session).mark_transcribed(
            capture, raw_transcript="raw", transcript_model="fake-stt-v1"
        )
        CaptureRepository(session).mark_corrected(
            capture, corrected_transcript="I think Jessica is hiding something."
        )
        response = (
            '[{"memory_type": "prediction", "content": "Jessica is hiding something."},'
            ' {"memory_type": "opinion", "content": "The pacing drags here."}]'
        )
        monkeypatch.setattr(
            "alam.services.capture_pipeline.get_llm_provider", lambda: FakeLLM(responses=[response])
        )

        extract_memories(session, {"capture_id": str(capture.id)})

        memories = MemoryRepository(session).list_for_capture(capture.id)
        assert [m.content for m in memories] == [
            "Jessica is hiding something.",
            "The pacing drags here.",
        ]
        assert capture.status is CaptureStatus.EXTRACTED

    def test_memories_inherit_the_captures_structure_ordinal(
        self, session: Session, capture: Capture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        CaptureRepository(session).mark_transcribed(
            capture, raw_transcript="raw", transcript_model="fake-stt-v1"
        )
        CaptureRepository(session).mark_corrected(capture, corrected_transcript="x")
        response = '[{"memory_type": "other", "content": "x"}]'
        monkeypatch.setattr(
            "alam.services.capture_pipeline.get_llm_provider", lambda: FakeLLM(responses=[response])
        )

        extract_memories(session, {"capture_id": str(capture.id)})

        memory = MemoryRepository(session).list_for_capture(capture.id)[0]
        assert memory.structure_ordinal == capture.structure_ordinal
        assert memory.structure_unit_id == capture.structure_unit_id
        assert memory.media_item_id == capture.media_item_id

    def test_records_the_prompt_version_id(
        self, session: Session, capture: Capture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        CaptureRepository(session).mark_transcribed(
            capture, raw_transcript="raw", transcript_model="fake-stt-v1"
        )
        CaptureRepository(session).mark_corrected(capture, corrected_transcript="x")
        response = '[{"memory_type": "other", "content": "x"}]'
        monkeypatch.setattr(
            "alam.services.capture_pipeline.get_llm_provider", lambda: FakeLLM(responses=[response])
        )

        extract_memories(session, {"capture_id": str(capture.id)})

        memory = MemoryRepository(session).list_for_capture(capture.id)[0]
        assert memory.prompt_version_id == "extract-memories-v1"

    def test_an_empty_extraction_is_valid_and_produces_no_memories(
        self, session: Session, capture: Capture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        CaptureRepository(session).mark_transcribed(
            capture, raw_transcript="raw", transcript_model="fake-stt-v1"
        )
        CaptureRepository(session).mark_corrected(capture, corrected_transcript="just rambling")
        monkeypatch.setattr(
            "alam.services.capture_pipeline.get_llm_provider", lambda: FakeLLM(responses=["[]"])
        )

        extract_memories(session, {"capture_id": str(capture.id)})

        assert MemoryRepository(session).list_for_capture(capture.id) == []
        assert capture.status is CaptureStatus.EXTRACTED

    def test_a_malformed_llm_response_fails_the_job_rather_than_silently_dropping_memories(
        self, session: Session, capture: Capture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        CaptureRepository(session).mark_transcribed(
            capture, raw_transcript="raw", transcript_model="fake-stt-v1"
        )
        CaptureRepository(session).mark_corrected(capture, corrected_transcript="x")
        monkeypatch.setattr(
            "alam.services.capture_pipeline.get_llm_provider",
            lambda: FakeLLM(responses=["not json"]),
        )

        with pytest.raises(CapturePipelineError):
            extract_memories(session, {"capture_id": str(capture.id)})

        assert capture.status is CaptureStatus.CORRECTED  # unchanged

    def test_running_before_correction_is_rejected(
        self, session: Session, capture: Capture
    ) -> None:
        with pytest.raises(CapturePipelineError, match="not been corrected"):
            extract_memories(session, {"capture_id": str(capture.id)})

    def test_unknown_capture_id_is_an_ordinary_failure(self, session: Session) -> None:
        with pytest.raises(CapturePipelineError):
            extract_memories(session, {"capture_id": str(uuid.uuid4())})
