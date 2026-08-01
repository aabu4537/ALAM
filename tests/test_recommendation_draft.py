"""Parsing and validating the recommendations LLM's response, and the
structural claim ADR-0014 rests on: the response schema has no field an
LLM-authored characterization of a candidate book could occupy. No
database, no model in the loop — hand-written JSON only."""

from __future__ import annotations

from typing import Any

import pytest

from alam.ai.synthesis.recommendations import (
    RECOMMENDATION_RESPONSE_SCHEMA,
    RecommendationParseError,
    parse_recommendation_response,
)


def _walk_schema_string_property_paths(
    schema: dict[str, Any], defs: dict[str, Any], path: str = ""
) -> list[str]:
    """Every property in the schema (following ``$ref``s into ``$defs``)
    whose type is ``string`` and whose name isn't an id/type/enum field —
    i.e. any place free text could land."""
    paths: list[str] = []
    if "$ref" in schema:
        ref_name = schema["$ref"].rsplit("/", 1)[-1]
        return _walk_schema_string_property_paths(defs[ref_name], defs, path)

    properties = schema.get("properties", {})
    for name, prop in properties.items():
        prop_path = f"{path}.{name}" if path else name
        resolved = prop
        if "$ref" in prop:
            ref_name = prop["$ref"].rsplit("/", 1)[-1]
            resolved = defs[ref_name]
        if resolved.get("type") == "string" and name not in {"id", "media_item_id", "type"}:
            paths.append(prop_path)
        if resolved.get("type") == "object":
            paths.extend(_walk_schema_string_property_paths(resolved, defs, prop_path))
        if resolved.get("type") == "array" and "items" in resolved:
            paths.extend(_walk_schema_string_property_paths(resolved["items"], defs, prop_path))
    return paths


class TestResponseSchemaHasNoFreeTextField:
    def test_no_string_field_exists_for_a_book_characterization_to_occupy(self) -> None:
        """ADR-0014's structural claim: every string-typed field in the
        schema is an id or a type discriminator, never a place for the model
        to write a new sentence describing a candidate's content."""
        defs = RECOMMENDATION_RESPONSE_SCHEMA.get("$defs", {})
        offending = _walk_schema_string_property_paths(RECOMMENDATION_RESPONSE_SCHEMA, defs)

        assert offending == []


class TestParseRecommendationResponse:
    def test_parses_a_recommendation_with_a_fact_citation(self) -> None:
        draft = parse_recommendation_response(
            '{"recommendations": [{"media_item_id": "book-1", '
            '"cites": [{"type": "preference_fact", "id": "fact-1"}]}]}'
        )

        assert len(draft.recommendations) == 1
        assert draft.recommendations[0].media_item_id == "book-1"
        assert draft.recommendations[0].cites[0].type == "preference_fact"
        assert draft.recommendations[0].cites[0].id == "fact-1"

    def test_parses_a_recommendation_with_a_memory_citation(self) -> None:
        draft = parse_recommendation_response(
            '{"recommendations": [{"media_item_id": "book-1", '
            '"cites": [{"type": "memory", "id": "memory-1"}]}]}'
        )

        assert draft.recommendations[0].cites[0].type == "memory"

    def test_parses_an_empty_recommendation_list(self) -> None:
        draft = parse_recommendation_response('{"recommendations": []}')

        assert draft.recommendations == []

    def test_non_json_raises(self) -> None:
        with pytest.raises(RecommendationParseError, match="not valid JSON"):
            parse_recommendation_response("not json at all")

    def test_missing_recommendations_key_raises(self) -> None:
        with pytest.raises(RecommendationParseError, match="did not match"):
            parse_recommendation_response("{}")

    def test_an_invalid_citation_type_raises(self) -> None:
        with pytest.raises(RecommendationParseError, match="did not match"):
            parse_recommendation_response(
                '{"recommendations": [{"media_item_id": "book-1", '
                '"cites": [{"type": "not_a_real_type", "id": "x"}]}]}'
            )

    def test_a_missing_cites_key_raises(self) -> None:
        with pytest.raises(RecommendationParseError, match="did not match"):
            parse_recommendation_response('{"recommendations": [{"media_item_id": "book-1"}]}')
