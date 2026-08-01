"""Adversarial spoiler set: leakage rate over ``retrieve_memories`` (M3,
ADR-0002 Layer 4), and again over ``GET /books/{id}/memories`` (pre-M6
hardening task 4) — the same cases, run through the real endpoint instead of
calling the function directly, so a regression in the router or in
``get_reader_context`` would show up here even if the function itself is
still correct in isolation.

Every case seeds at least one memory past ``current_ordinal`` chosen to be
textually as close as possible to the query — near-duplicate phrasing, or in
a few cases the exact same content as an earlier, visible memory — so that if
the ordinal filter were ever missing or broken, the adversarial memory is
exactly what both the vector and full-text branches would rank first. A
starter set of ten, not ADR-0002's target of roughly two hundred.

"Leaked" is defined with the same predicate the retrieval path itself uses
for its defense-in-depth check (``domain.spoiler_filter.is_visible``) — one
definition of visibility, not two that could quietly drift apart.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from alam.ai.retrieval.hybrid import retrieve_memories
from alam.api.main import create_app
from alam.domain.reader_context import ReaderContext
from alam.domain.spoiler_filter import is_visible
from alam.eval.models import SeedMemory, SpoilerCase, SpoilerCaseResult, SpoilerEvalReport
from alam.eval.seeding import seed_case_memories
from alam.persistence.repositories.users import UserRepository
from alam.persistence.session import session_scope

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session

ADVERSARIAL_SPOILER_CASES: tuple[SpoilerCase, ...] = (
    SpoilerCase(
        label="near_duplicate_phrasing",
        memories=(
            SeedMemory("seen", "the sandworm attacks the harvester", 1),
            SeedMemory("spoiler", "the sandworm attacks the harvester again later", 5),
        ),
        query="sandworm attacks harvester",
        current_ordinal=1,
    ),
    SpoilerCase(
        label="identical_content_different_ordinals",
        memories=(
            SeedMemory("seen", "Paul drinks the Water of Life", 2),
            SeedMemory("spoiler", "Paul drinks the Water of Life", 9),
        ),
        query="Paul drinks the Water of Life",
        current_ordinal=2,
    ),
    SpoilerCase(
        label="spoiler_is_a_continuation",
        memories=(
            SeedMemory("seen", "Jessica is pregnant", 3),
            SeedMemory(
                "spoiler", "Jessica gives birth to Alia, who is born with full awareness", 10
            ),
        ),
        query="Jessica pregnant birth Alia",
        current_ordinal=3,
    ),
    SpoilerCase(
        label="only_a_spoiler_exists",
        memories=(SeedMemory("spoiler", "the emperor abdicates the throne to Paul", 12),),
        query="the emperor abdicates the throne to Paul",
        current_ordinal=1,
    ),
    SpoilerCase(
        label="character_arc_resolution",
        memories=(
            SeedMemory("seen", "Feyd-Rautha is introduced as ambitious", 2),
            SeedMemory("spoiler", "Feyd-Rautha's ambitious duel with Paul ends in his death", 15),
        ),
        query="Feyd-Rautha ambitious duel death",
        current_ordinal=2,
    ),
    SpoilerCase(
        label="boundary_one_past_current",
        memories=(
            SeedMemory("seen", "Stilgar leads the Fremen council", 4),
            SeedMemory("spoiler", "Stilgar leads the Fremen council to accept Paul as Muad'Dib", 5),
        ),
        query="Stilgar leads Fremen council",
        current_ordinal=4,
    ),
    SpoilerCase(
        label="multiple_future_memories",
        memories=(
            SeedMemory("seen", "Paul has a vision of jihad", 3),
            SeedMemory("spoiler_1", "Paul's jihad begins across the galaxy", 20),
            SeedMemory("spoiler_2", "the jihad kills billions in Paul's name", 25),
        ),
        query="Paul jihad vision",
        current_ordinal=3,
    ),
    SpoilerCase(
        label="query_describes_a_future_event_directly",
        memories=(SeedMemory("spoiler", "Alia kills the Baron Harkonnen", 18),),
        query="Alia kills the Baron",
        current_ordinal=6,
    ),
    SpoilerCase(
        label="far_future_grief",
        memories=(
            SeedMemory("seen", "Chani mourns quietly", 6),
            SeedMemory("spoiler", "Chani mourns Paul's fallen son", 7),
        ),
        query="Chani mourns",
        current_ordinal=6,
    ),
    SpoilerCase(
        label="identical_ritual_text_far_apart",
        memories=(
            SeedMemory("seen", "the Reverend Mother tests Paul with the gom jabbar", 1),
            SeedMemory("spoiler", "the Reverend Mother tests Paul with the gom jabbar", 9),
        ),
        query="gom jabbar test",
        current_ordinal=1,
    ),
)


def run_spoiler_eval(
    session: Session,
    *,
    cases: tuple[SpoilerCase, ...] = ADVERSARIAL_SPOILER_CASES,
) -> SpoilerEvalReport:
    results = []
    for case in cases:
        book_id, owner_id, by_label = seed_case_memories(session, case.memories)
        id_to_label = {memory.id: label for label, memory in by_label.items()}
        reader_context = ReaderContext(
            media_item_id=book_id, user_id=owner_id, current_ordinal=case.current_ordinal
        )

        retrieved = retrieve_memories(
            session, reader_context, query=case.query, limit=len(case.memories)
        )
        leaked_labels = tuple(
            id_to_label[memory.id]
            for memory in retrieved
            if not is_visible(
                structure_ordinal=memory.structure_ordinal, current_ordinal=case.current_ordinal
            )
        )
        results.append(
            SpoilerCaseResult(
                label=case.label, leaked=bool(leaked_labels), leaked_labels=leaked_labels
            )
        )

    leakage_rate = sum(1 for r in results if r.leaked) / len(results) if results else 0.0
    return SpoilerEvalReport(leakage_rate=leakage_rate, results=tuple(results))


def run_spoiler_eval_via_endpoint(
    session: Session,
    *,
    cases: tuple[SpoilerCase, ...] = ADVERSARIAL_SPOILER_CASES,
) -> SpoilerEvalReport:
    """Same cases and same leakage definition as ``run_spoiler_eval``, but
    each case is checked by issuing a real ``GET /books/{id}/memories``
    request rather than calling ``retrieve_memories`` directly —
    ``session_scope`` is overridden to hand the request this same session
    (still rolled back by the caller), so this exercises the actual router,
    ``get_reader_context``, and response serialization, not just the
    retrieval function in isolation.

    All cases share one owner, created once up front: ``GET
    /books/{id}/memories`` resolves the owner via ``UserRepository.get_owner``
    with no id in the request (CLAUDE.md rule 9), so every case's book must
    belong to that same single owner or it would 404 as someone else's.
    ``current_ordinal`` is never a request parameter here either — each
    case's seeded reading session is repositioned to ``case.current_ordinal``
    so the endpoint resolves the same ordinal the direct-function eval is
    handed explicitly.
    """

    def _session_override() -> Iterator[Session]:
        yield session

    app = create_app()
    app.dependency_overrides[session_scope] = _session_override
    owner_id = UserRepository(session).create(display_name="Eval Owner").id

    results = []
    try:
        with TestClient(app) as client:
            for case in cases:
                book_id, _, by_label = seed_case_memories(
                    session,
                    case.memories,
                    owner_id=owner_id,
                    current_ordinal=case.current_ordinal,
                )
                id_to_label = {memory.id: label for label, memory in by_label.items()}

                response = client.get(
                    f"/books/{book_id}/memories",
                    params={"query": case.query, "limit": len(case.memories)},
                )
                response.raise_for_status()
                retrieved_ids = {uuid.UUID(row["id"]) for row in response.json()}

                leaked_labels = tuple(
                    label
                    for memory_id, label in id_to_label.items()
                    if memory_id in retrieved_ids
                    and not is_visible(
                        structure_ordinal=by_label[label].structure_ordinal,
                        current_ordinal=case.current_ordinal,
                    )
                )
                results.append(
                    SpoilerCaseResult(
                        label=case.label, leaked=bool(leaked_labels), leaked_labels=leaked_labels
                    )
                )
    finally:
        app.dependency_overrides.clear()

    leakage_rate = sum(1 for r in results if r.leaked) / len(results) if results else 0.0
    return SpoilerEvalReport(leakage_rate=leakage_rate, results=tuple(results))
