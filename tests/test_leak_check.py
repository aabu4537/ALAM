"""Parsing and validating the Layer 3 leak-check LLM's response. No database,
no model in the loop — hand-written JSON only."""

from __future__ import annotations

import pytest

from alam.ai.synthesis.leak_check import LeakCheckParseError, parse_leak_check_response


class TestParseLeakCheckResponse:
    def test_parses_a_clean_verdict(self) -> None:
        result = parse_leak_check_response('{"leaked": false, "spans": []}')

        assert result.leaked is False
        assert result.spans == []

    def test_parses_a_leaked_verdict_with_spans(self) -> None:
        result = parse_leak_check_response(
            '{"leaked": true, "spans": ["the steward betrays the king"]}'
        )

        assert result.leaked is True
        assert result.spans == ["the steward betrays the king"]

    def test_non_json_raises(self) -> None:
        with pytest.raises(LeakCheckParseError, match="not valid JSON"):
            parse_leak_check_response("not json at all")

    def test_missing_keys_raise(self) -> None:
        with pytest.raises(LeakCheckParseError, match="did not match"):
            parse_leak_check_response("{}")

    def test_wrong_type_raises(self) -> None:
        with pytest.raises(LeakCheckParseError, match="did not match"):
            parse_leak_check_response('{"leaked": false, "spans": "not a list"}')
