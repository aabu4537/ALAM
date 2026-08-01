"""Parsing and validating the journey-summary LLM's response. No database,
no model in the loop — hand-written JSON only."""

from __future__ import annotations

import pytest

from alam.ai.synthesis.journey_summary import (
    JourneySummaryParseError,
    parse_journey_summary_response,
)


class TestParseJourneySummaryResponse:
    def test_parses_the_narrative(self) -> None:
        draft = parse_journey_summary_response('{"narrative": "They loved chapter one."}')

        assert draft.narrative == "They loved chapter one."

    def test_non_json_raises(self) -> None:
        with pytest.raises(JourneySummaryParseError, match="not valid JSON"):
            parse_journey_summary_response("not json at all")

    def test_missing_narrative_key_raises(self) -> None:
        with pytest.raises(JourneySummaryParseError, match="did not match"):
            parse_journey_summary_response("{}")

    def test_wrong_type_raises(self) -> None:
        with pytest.raises(JourneySummaryParseError, match="did not match"):
            parse_journey_summary_response('{"narrative": 123}')

    def test_a_json_array_instead_of_an_object_raises(self) -> None:
        with pytest.raises(JourneySummaryParseError, match="did not match"):
            parse_journey_summary_response('["a narrative"]')
