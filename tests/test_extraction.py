from __future__ import annotations

import json

import pytest

from alam.ai.extraction.memories import ExtractionError, MemoryType, parse_extraction_response


class TestParseExtractionResponse:
    def test_parses_a_well_formed_array(self) -> None:
        text = json.dumps(
            [
                {"memory_type": "prediction", "content": "The steward will betray the king."},
                {"memory_type": "opinion", "content": "The pacing in part two drags."},
            ]
        )

        memories = parse_extraction_response(text)

        assert len(memories) == 2
        assert memories[0].memory_type is MemoryType.PREDICTION
        assert memories[0].content == "The steward will betray the king."
        assert memories[1].memory_type is MemoryType.OPINION

    def test_empty_array_is_valid(self) -> None:
        assert parse_extraction_response("[]") == []

    def test_every_fixed_enum_value_round_trips(self) -> None:
        text = json.dumps([{"memory_type": t.value, "content": "x"} for t in MemoryType])

        memories = parse_extraction_response(text)

        assert {m.memory_type for m in memories} == set(MemoryType)

    def test_not_json_is_rejected(self) -> None:
        with pytest.raises(ExtractionError, match="not valid JSON"):
            parse_extraction_response("not json at all")

    def test_a_json_object_instead_of_an_array_is_rejected(self) -> None:
        with pytest.raises(ExtractionError, match="JSON array"):
            parse_extraction_response(json.dumps({"memory_type": "opinion", "content": "x"}))

    def test_an_unknown_memory_type_is_rejected(self) -> None:
        """The fixed enum is the point (ADR-0001) — a value outside it must
        fail loudly, not silently coerce to `other`, or extraction accuracy
        stops being measurable."""
        text = json.dumps([{"memory_type": "spoiler_alert", "content": "x"}])

        with pytest.raises(ExtractionError, match="schema"):
            parse_extraction_response(text)

    def test_a_missing_content_field_is_rejected(self) -> None:
        text = json.dumps([{"memory_type": "opinion"}])

        with pytest.raises(ExtractionError, match="schema"):
            parse_extraction_response(text)

    def test_markdown_fenced_json_is_rejected_rather_than_unwrapped(self) -> None:
        """The prompt asks for no fencing; if a model adds it anyway, that is
        a real extraction failure worth surfacing and retrying, not something
        to paper over here."""
        text = "```json\n[]\n```"

        with pytest.raises(ExtractionError, match="not valid JSON"):
            parse_extraction_response(text)
