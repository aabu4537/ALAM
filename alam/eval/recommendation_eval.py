"""``recommendation_groundedness`` (M6 session 2, ADR-0014) — every claim in
a recommendation must cite a ``preference_fact``/``memory`` id that exists
and belongs to the reader. Fully deterministic (existence + ownership
check against the DB, ``domain/recommendation_groundedness.py``) — no LLM
judge needed, unlike ``synthesis_leakage_rate``, which is inherently a
semantic call.

Two cases here, exercised through the real ``GET /recommendations``
endpoint, run **against one owner in sequence** — unlike
``journey_summary_eval.py``'s per-case owner, ``GET /recommendations``
resolves ``UserRepository.get_owner()`` with no caller-supplied id
(CLAUDE.md rule 9, this is a single-user system by design), so two
independent owners in the same database is not a scenario the endpoint can
even distinguish. Case 2 adds a second to-read candidate, which changes the
shelf snapshot and forces ``is_recommendation_set_stale`` to regenerate
rather than serve case 1's cached row — the same "latest wins" flow real
usage would hit, not a special case for this harness.

- Case 1: a clean citation is accepted.
- Case 2 — the "not vacuously passing" positive control
  ``journey_summary_eval.py`` established: a citation to a nonexistent id
  is actually blocked, not silently accepted.

**A third check ADR-0014's design rests on lives in
``tests/test_recommendation_draft.py`` instead of here**
(``TestResponseSchemaHasNoFreeTextField``): that the response schema has no
free-text field a book characterization could occupy at all. It's a static
assertion on a constant (``RECOMMENDATION_RESPONSE_SCHEMA``), not a
generation case — it needs no seeded database, no ``FakeLLM``, and running
it through this harness would only add ceremony around a check that has
nothing to do with a particular run.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from unittest.mock import patch

from fastapi.testclient import TestClient

from alam.ai.providers.fakes import FakeLLM
from alam.api.main import create_app
from alam.eval.models import GroundednessCaseResult, RecommendationGroundednessReport
from alam.persistence.repositories import (
    MediaItemRepository,
    PreferenceFactRepository,
    RecommendationRepository,
    UserRepository,
)
from alam.persistence.session import session_scope

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session

_FAKE_FACT_ID = "00000000-0000-0000-0000-000000000000"


def _run_through_endpoint(session: Session, fake_llm: FakeLLM) -> None:
    def _session_override() -> Iterator[Session]:
        yield session

    app = create_app()
    app.dependency_overrides[session_scope] = _session_override
    try:
        with (
            patch("alam.services.recommendations.get_llm_provider", return_value=fake_llm),
            TestClient(app) as client,
        ):
            client.get("/recommendations")
    finally:
        app.dependency_overrides.clear()


def run_recommendation_groundedness_eval(session: Session) -> RecommendationGroundednessReport:
    owner = UserRepository(session).create(display_name="Groundedness Eval Owner")
    fact = PreferenceFactRepository(session).create(
        user_id=owner.id,
        statement="loves unreliable narrators",
        base_confidence=0.8,
        observed_at=dt.datetime.now(dt.UTC),
        evidence_memory_ids=[],
    )
    book_one = MediaItemRepository(session).create(
        user_id=owner.id,
        title="Case 1 Book",
        attributes={"exclusive_shelf": "to-read", "author": "Case Author"},
    )

    clean_response = (
        '{"recommendations": [{"media_item_id": "'
        + str(book_one.id)
        + '", "cites": [{"type": "preference_fact", "id": "'
        + str(fact.id)
        + '"}]}]}'
    )
    _run_through_endpoint(session, FakeLLM(responses=[clean_response]))

    row_one = RecommendationRepository(session).get_latest_for_user(owner.id)
    if row_one is None:
        raise AssertionError("generation reported success but persisted no row — a setup bug")

    clean_ungrounded = row_one.status.value != "complete"
    claim_text_matches_stored_fact = bool(
        row_one.candidates and row_one.candidates[0]["claims"][0]["text"] == fact.statement
    )
    clean_result = GroundednessCaseResult(
        label="clean_citation_is_grounded",
        ungrounded=clean_ungrounded or not claim_text_matches_stored_fact,
        ungrounded_citation_ids=() if not clean_ungrounded else (str(fact.id),),
    )

    # A second to-read candidate changes the shelf snapshot, forcing
    # regeneration rather than serving `row_one` from cache — see the
    # module docstring.
    book_two = MediaItemRepository(session).create(
        user_id=owner.id,
        title="Case 2 Book",
        attributes={"exclusive_shelf": "to-read", "author": "Case Author"},
    )
    ungrounded_response = (
        '{"recommendations": [{"media_item_id": "'
        + str(book_two.id)
        + '", "cites": [{"type": "preference_fact", "id": "'
        + _FAKE_FACT_ID
        + '"}]}]}'
    )
    _run_through_endpoint(session, FakeLLM(responses=[ungrounded_response]))

    row_two = RecommendationRepository(session).get_latest_for_user(owner.id)
    if row_two is None or row_two.id == row_one.id:
        raise AssertionError("case 2 did not regenerate against a fresh row — a setup bug")

    blocked = row_two.status.value == "blocked_ungrounded"
    ungrounded_result = GroundednessCaseResult(
        label="nonexistent_citation_is_blocked",
        # Inverted: the case *passes* (ungrounded=False) when the bad
        # citation *was* caught — same "did the eval case's assertion
        # hold" framing `SpoilerCaseResult.leaked` uses.
        ungrounded=not blocked,
        ungrounded_citation_ids=() if blocked else (_FAKE_FACT_ID,),
    )

    results = (clean_result, ungrounded_result)
    ungrounded_rate = sum(1 for r in results if r.ungrounded) / len(results)
    return RecommendationGroundednessReport(ungrounded_rate=ungrounded_rate, results=results)
