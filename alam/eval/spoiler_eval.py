"""Adversarial spoiler set: leakage rate over ``retrieve_memories`` (M3,
ADR-0002 Layer 4).

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

from typing import TYPE_CHECKING

from alam.ai.retrieval.hybrid import retrieve_memories
from alam.domain.spoiler_filter import is_visible
from alam.eval.models import SeedMemory, SpoilerCase, SpoilerCaseResult, SpoilerEvalReport
from alam.eval.seeding import seed_case_memories

if TYPE_CHECKING:
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
        book_id, by_label = seed_case_memories(session, case.memories)
        id_to_label = {memory.id: label for label, memory in by_label.items()}

        retrieved = retrieve_memories(
            session,
            media_item_id=book_id,
            query=case.query,
            current_ordinal=case.current_ordinal,
            limit=len(case.memories),
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
