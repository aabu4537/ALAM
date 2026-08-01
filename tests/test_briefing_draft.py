"""Parsing and validating the briefing LLM's response, and the structural
claim this session's plan rests on (same move ADR-0014 made for
recommendations): the response schema has no field an LLM-authored
characterization of the candidate book could occupy, and — narrower than
recommendations — no ``"catalog"`` citation type exists for the model to
attempt either, since the teaser is always ALAM-composed. No database, no
model in the loop — hand-written JSON only."""

from __future__ import annotations

from typing import Any

import pytest

from alam.ai.synthesis.briefing import (
    BRIEFING_RESPONSE_SCHEMA,
    BriefingParseError,
    parse_briefing_response,
)


def _walk_schema_string_property_paths(
    schema: dict[str, Any], defs: dict[str, Any], path: str = ""
) -> list[str]:
    """Every property in the schema (following ``$ref``s into ``$defs``)
    whose type is ``string`` and whose name isn't an id/type field — i.e.
    any place free text could land. Same walker
    ``tests/test_recommendation_draft.py`` uses."""
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
        if resolved.get("type") == "string" and name not in {"id", "type"}:
            paths.append(prop_path)
        if resolved.get("type") == "object":
            paths.extend(_walk_schema_string_property_paths(resolved, defs, prop_path))
        if resolved.get("type") == "array" and "items" in resolved:
            paths.extend(_walk_schema_string_property_paths(resolved["items"], defs, prop_path))
    return paths


class TestResponseSchemaHasNoFreeTextField:
    def test_no_string_field_exists_for_a_book_characterization_to_occupy(self) -> None:
        defs = BRIEFING_RESPONSE_SCHEMA.get("$defs", {})
        offending = _walk_schema_string_property_paths(BRIEFING_RESPONSE_SCHEMA, defs)

        assert offending == []

    def test_catalog_is_not_a_representable_citation_type(self) -> None:
        """Narrower than ``RECOMMENDATION_RESPONSE_SCHEMA``: a briefing's
        teaser is always ALAM-composed, never LLM-cited, so ``"catalog"``
        must not even appear as an allowed value of the ``type`` field — the
        model should never be *offered* the option, not just have it
        rejected after the fact."""
        defs = BRIEFING_RESPONSE_SCHEMA.get("$defs", {})
        citation_ref = defs.get("BriefingCitationRef", {})
        type_enum = citation_ref.get("properties", {}).get("type", {}).get("enum", [])

        assert "catalog" not in type_enum
        assert set(type_enum) == {"preference_fact", "memory"}


class TestParseBriefingResponse:
    def test_parses_a_fact_citation(self) -> None:
        draft = parse_briefing_response('{"cites": [{"type": "preference_fact", "id": "fact-1"}]}')

        assert len(draft.cites) == 1
        assert draft.cites[0].type == "preference_fact"
        assert draft.cites[0].id == "fact-1"

    def test_parses_a_memory_citation(self) -> None:
        draft = parse_briefing_response('{"cites": [{"type": "memory", "id": "memory-1"}]}')

        assert draft.cites[0].type == "memory"

    def test_parses_an_empty_citation_list(self) -> None:
        draft = parse_briefing_response('{"cites": []}')

        assert draft.cites == []

    def test_non_json_raises(self) -> None:
        with pytest.raises(BriefingParseError, match="not valid JSON"):
            parse_briefing_response("not json at all")

    def test_missing_cites_key_raises(self) -> None:
        with pytest.raises(BriefingParseError, match="did not match"):
            parse_briefing_response("{}")

    def test_a_catalog_citation_type_raises(self) -> None:
        """Rejected at parse time too, not just absent from the schema —
        defense in depth in case a provider ever ignores ``response_schema``
        and free-forms a response anyway."""
        with pytest.raises(BriefingParseError, match="did not match"):
            parse_briefing_response('{"cites": [{"type": "catalog", "id": "book-1"}]}')

    def test_an_invalid_citation_type_raises(self) -> None:
        with pytest.raises(BriefingParseError, match="did not match"):
            parse_briefing_response('{"cites": [{"type": "not_a_real_type", "id": "x"}]}')
