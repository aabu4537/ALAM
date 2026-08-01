"""Parsing and validating the consolidation LLM's response. No database, no
model in the loop — hand-written JSON only."""

from __future__ import annotations

import json
import uuid

import pytest
from pydantic import ValidationError

from alam.ai.consolidation.actions import (
    ConsolidationAction,
    ConsolidationActionType,
    ConsolidationError,
    parse_consolidation_response,
)

MEMORY_ID = str(uuid.uuid4())
FACT_ID = str(uuid.uuid4())


class TestParseConsolidationResponse:
    def test_parses_a_new_action(self) -> None:
        text = json.dumps(
            [
                {
                    "action": "new",
                    "statement": "prefers unreliable narrators",
                    "memory_ids": [MEMORY_ID],
                }
            ]
        )

        [action] = parse_consolidation_response(text)

        assert action.action is ConsolidationActionType.NEW
        assert action.statement == "prefers unreliable narrators"
        assert action.fact_id is None

    def test_parses_a_reinforce_action(self) -> None:
        text = json.dumps([{"action": "reinforce", "fact_id": FACT_ID, "memory_ids": [MEMORY_ID]}])

        [action] = parse_consolidation_response(text)

        assert action.action is ConsolidationActionType.REINFORCE
        assert str(action.fact_id) == FACT_ID
        assert action.statement is None

    def test_parses_a_supersede_action(self) -> None:
        text = json.dumps(
            [
                {
                    "action": "supersede",
                    "fact_id": FACT_ID,
                    "statement": "now appreciates slow openings",
                    "memory_ids": [MEMORY_ID],
                }
            ]
        )

        [action] = parse_consolidation_response(text)

        assert action.action is ConsolidationActionType.SUPERSEDE
        assert str(action.fact_id) == FACT_ID
        assert action.statement == "now appreciates slow openings"

    def test_empty_batch_is_a_valid_no_op(self) -> None:
        assert parse_consolidation_response("[]") == []

    def test_non_json_raises_consolidation_error(self) -> None:
        with pytest.raises(ConsolidationError, match="not valid JSON"):
            parse_consolidation_response("not json at all")

    def test_a_bare_object_instead_of_an_array_raises(self) -> None:
        with pytest.raises(ConsolidationError, match="expected a JSON array"):
            parse_consolidation_response('{"action": "new"}')

    def test_unknown_action_type_raises(self) -> None:
        text = json.dumps([{"action": "delete", "memory_ids": [MEMORY_ID]}])

        with pytest.raises(ConsolidationError):
            parse_consolidation_response(text)

    def test_new_without_a_statement_raises(self) -> None:
        text = json.dumps([{"action": "new", "memory_ids": [MEMORY_ID]}])

        with pytest.raises(ConsolidationError, match="requires a non-empty statement"):
            parse_consolidation_response(text)

    def test_reinforce_without_a_fact_id_raises(self) -> None:
        text = json.dumps([{"action": "reinforce", "memory_ids": [MEMORY_ID]}])

        with pytest.raises(ConsolidationError, match="requires a fact_id"):
            parse_consolidation_response(text)

    def test_an_action_with_no_memory_ids_raises(self) -> None:
        text = json.dumps(
            [{"action": "new", "statement": "prefers unreliable narrators", "memory_ids": []}]
        )

        with pytest.raises(ConsolidationError, match="at least one supporting memory"):
            parse_consolidation_response(text)


class TestConsolidationActionValidation:
    def test_can_be_constructed_directly(self) -> None:
        action = ConsolidationAction(
            action=ConsolidationActionType.NEW,
            statement="prefers unreliable narrators",
            memory_ids=[uuid.UUID(MEMORY_ID)],
        )

        assert action.action is ConsolidationActionType.NEW

    def test_supersede_without_fact_id_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ConsolidationAction(
                action=ConsolidationActionType.SUPERSEDE,
                statement="now appreciates slow openings",
                memory_ids=[uuid.UUID(MEMORY_ID)],
            )
