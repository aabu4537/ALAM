"""Parsing and validating the prediction-resolution LLM's response. No
database, no model in the loop — hand-written JSON only."""

from __future__ import annotations

import pytest

from alam.ai.prediction_resolution.outcome import (
    ResolutionError,
    ResolutionOutcome,
    parse_resolution_response,
)


class TestParseResolutionResponse:
    def test_parses_confirmed(self) -> None:
        resolution = parse_resolution_response('{"outcome": "confirmed"}')

        assert resolution.outcome is ResolutionOutcome.CONFIRMED

    def test_parses_refuted(self) -> None:
        resolution = parse_resolution_response('{"outcome": "refuted"}')

        assert resolution.outcome is ResolutionOutcome.REFUTED

    def test_parses_unresolvable(self) -> None:
        resolution = parse_resolution_response('{"outcome": "unresolvable"}')

        assert resolution.outcome is ResolutionOutcome.UNRESOLVABLE

    def test_non_json_raises(self) -> None:
        with pytest.raises(ResolutionError, match="not valid JSON"):
            parse_resolution_response("not json at all")

    def test_unknown_outcome_raises(self) -> None:
        with pytest.raises(ResolutionError, match="did not match"):
            parse_resolution_response('{"outcome": "maybe"}')

    def test_missing_outcome_key_raises(self) -> None:
        with pytest.raises(ResolutionError, match="did not match"):
            parse_resolution_response("{}")

    def test_a_json_array_instead_of_an_object_raises(self) -> None:
        with pytest.raises(ResolutionError, match="did not match"):
            parse_resolution_response('["confirmed"]')
