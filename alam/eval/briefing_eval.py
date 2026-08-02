"""``briefing_groundedness`` (M6 session 4) — every claim in a briefing
must cite a ``preference_fact``/``memory`` id that exists and belongs to
the reader. Fully deterministic (existence + ownership check against the
DB, ``domain/recommendation_groundedness.py``, reused unchanged from
recommendations) — no LLM judge needed, unlike ``synthesis_leakage_rate``,
which is inherently a semantic call. Parallel to
``recommendation_eval.py``, simpler in one respect: a briefing is keyed by
``media_item_id``, not by a single per-user row, so each case gets its own
book and its own row — no shelf-snapshot trick is needed to force a second
case to regenerate rather than serve the first case's cached result.

- Case 1: a clean citation is accepted.
- Case 2 — the "not vacuously passing" positive control every eval harness
  in this codebase establishes: a citation to a nonexistent id is actually
  blocked, not silently accepted.

**A third check this session's design rests on lives in
``tests/test_briefing_draft.py`` instead of here**
(``TestResponseSchemaHasNoFreeTextField``, plus
``test_catalog_is_not_a_representable_citation_type``): that the response
schema has no free-text field a book characterization could occupy, and
that ``"catalog"`` isn't even offered as a citable type. Static assertions
on a constant, not generation cases — they need no seeded database, no
``FakeLLM``, and running them through this harness would only add
ceremony around a check that has nothing to do with a particular run.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING
from unittest.mock import patch

from fastapi.testclient import TestClient

from alam.ai.providers.fakes import FakeLLM
from alam.api.dependencies import require_owner_session
from alam.api.main import create_app
from alam.eval.models import BriefingGroundednessReport, GroundednessCaseResult
from alam.persistence.repositories import BriefingRepository, MediaItemRepository, UserRepository
from alam.persistence.repositories.preference_facts import PreferenceFactRepository
from alam.persistence.session import session_scope

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session

_FAKE_FACT_ID = "00000000-0000-0000-0000-000000000000"


def _run_through_endpoint(session: Session, book_id: object, fake_llm: FakeLLM) -> None:
    def _session_override() -> Iterator[Session]:
        yield session

    app = create_app()
    app.dependency_overrides[session_scope] = _session_override
    app.dependency_overrides[require_owner_session] = lambda: None
    try:
        with (
            patch("alam.services.briefing.get_llm_provider", return_value=fake_llm),
            TestClient(app) as client,
        ):
            client.get(f"/books/{book_id}/briefing")
    finally:
        app.dependency_overrides.clear()


def run_briefing_groundedness_eval(session: Session) -> BriefingGroundednessReport:
    owner = UserRepository(session).create(display_name="Groundedness Eval Owner")
    fact = PreferenceFactRepository(session).create(
        user_id=owner.id,
        statement="loves unreliable narrators",
        base_confidence=0.8,
        observed_at=dt.datetime.now(dt.UTC),
        evidence_memory_ids=[],
    )
    book_one = MediaItemRepository(session).create(
        user_id=owner.id, title="Case 1 Book", attributes={"author": "Case Author"}
    )

    clean_response = '{"cites": [{"type": "preference_fact", "id": "' + str(fact.id) + '"}]}'
    _run_through_endpoint(session, book_one.id, FakeLLM(responses=[clean_response]))

    row_one = BriefingRepository(session).get_latest_for_media_item(book_one.id)
    if row_one is None:
        raise AssertionError("generation reported success but persisted no row — a setup bug")

    clean_ungrounded = row_one.status.value != "complete"
    claim_text_matches_stored_fact = bool(
        row_one.claims and row_one.claims[0]["text"] == fact.statement
    )
    clean_result = GroundednessCaseResult(
        label="clean_citation_is_grounded",
        ungrounded=clean_ungrounded or not claim_text_matches_stored_fact,
        ungrounded_citation_ids=() if not clean_ungrounded else (str(fact.id),),
    )

    book_two = MediaItemRepository(session).create(
        user_id=owner.id, title="Case 2 Book", attributes={"author": "Case Author"}
    )
    ungrounded_response = '{"cites": [{"type": "preference_fact", "id": "' + _FAKE_FACT_ID + '"}]}'
    _run_through_endpoint(session, book_two.id, FakeLLM(responses=[ungrounded_response]))

    row_two = BriefingRepository(session).get_latest_for_media_item(book_two.id)
    if row_two is None:
        raise AssertionError("generation reported success but persisted no row — a setup bug")

    blocked = row_two.status.value == "blocked_ungrounded"
    ungrounded_result = GroundednessCaseResult(
        label="nonexistent_citation_is_blocked",
        # Inverted: the case *passes* (ungrounded=False) when the bad
        # citation *was* caught — same framing
        # ``recommendation_eval.py``'s equivalent case uses.
        ungrounded=not blocked,
        ungrounded_citation_ids=() if blocked else (_FAKE_FACT_ID,),
    )

    results = (clean_result, ungrounded_result)
    ungrounded_rate = sum(1 for r in results if r.ungrounded) / len(results)
    return BriefingGroundednessReport(ungrounded_rate=ungrounded_rate, results=results)
