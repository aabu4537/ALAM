"""Golden retrieval set: recall@k over ``retrieve_memories`` (M3, ADR-0002
Layer 4 / docs/milestones.md's "Evaluation harness").

A starter set — roughly a dozen hand-authored cases, not the couple hundred a
mature eval suite would carry. Every case is reachable through Postgres
full-text search alone; several are written so an invented proper noun
(``Muad'Dib``) or an exact-text query only the vector branch could nail
exercises both branches, per the "pure vector search misses invented proper
nouns" rationale in docs/milestones.md. Deterministic end to end — full-text
ranking, RRF, and the fake embedding provider's vectors are all pure
functions of their input — so ``recall_at_k`` is a real regression signal,
not a noisy estimate: it is expected to read exactly 1.0, and a drop means
something in the retrieval path broke.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alam.ai.retrieval.hybrid import retrieve_memories
from alam.eval.models import RetrievalCase, RetrievalCaseResult, RetrievalEvalReport, SeedMemory
from alam.eval.seeding import seed_case_memories

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

DEFAULT_K = 5

RETRIEVAL_CASES: tuple[RetrievalCase, ...] = (
    RetrievalCase(
        label="single_keyword_match",
        memories=(
            SeedMemory("target", "Paul must control the sandworm before the Fremen accept him", 2),
            SeedMemory("distractor", "The spice must flow through the desert trade routes", 2),
        ),
        query="sandworm control",
        current_ordinal=2,
        relevant_labels=("target",),
    ),
    RetrievalCase(
        label="invented_proper_noun",
        memories=(SeedMemory("target", "Muad'Dib is the name the Fremen give Paul Atreides", 3),),
        query="Muad'Dib Fremen name",
        current_ordinal=3,
        relevant_labels=("target",),
    ),
    RetrievalCase(
        label="multiple_relevant_memories",
        memories=(
            SeedMemory(
                "opinion_1",
                "Paul's decision to drink the Water of Life feels reckless and brave",
                5,
            ),
            SeedMemory(
                "opinion_2",
                "Drinking the Water of Life nearly kills Paul and awakens his prescience",
                5,
            ),
            SeedMemory(
                "distractor", "Duncan Idaho trains the Fremen in weirding combat techniques", 5
            ),
        ),
        query="Water of Life Paul",
        current_ordinal=5,
        relevant_labels=("opinion_1", "opinion_2"),
    ),
    RetrievalCase(
        label="exact_and_partial_text_fused",
        memories=(
            SeedMemory("exact", "the emperor's Sardaukar legions land on Arrakis", 6),
            SeedMemory("partial", "Sardaukar troops in disguise infiltrate House Atreides", 6),
        ),
        query="the emperor's Sardaukar legions land on Arrakis",
        current_ordinal=6,
        relevant_labels=("exact", "partial"),
    ),
    RetrievalCase(
        label="confusion_memory",
        memories=(
            SeedMemory(
                "target",
                "I'm confused about why Jessica defied the Bene Gesserit breeding program",
                4,
            ),
        ),
        query="Jessica defied breeding program",
        current_ordinal=4,
        relevant_labels=("target",),
    ),
    RetrievalCase(
        label="character_judgment",
        memories=(
            SeedMemory(
                "target", "Baron Harkonnen is portrayed as grotesquely cruel and manipulative", 7
            ),
        ),
        query="Baron Harkonnen cruel manipulative",
        current_ordinal=7,
        relevant_labels=("target",),
    ),
    RetrievalCase(
        label="favorite_moment_with_distractor",
        memories=(
            SeedMemory(
                "target", "My favorite moment is when Paul rides the sandworm for the first time", 8
            ),
            SeedMemory("distractor", "The desert stretches endlessly toward the horizon", 8),
        ),
        query="Paul rides the sandworm first time",
        current_ordinal=8,
        relevant_labels=("target",),
    ),
    RetrievalCase(
        label="meta_comment",
        memories=(
            SeedMemory("target", "This chapter's pacing feels rushed compared to earlier ones", 1),
        ),
        query="chapter pacing rushed",
        current_ordinal=1,
        relevant_labels=("target",),
    ),
)


def run_retrieval_eval(
    session: Session,
    *,
    cases: tuple[RetrievalCase, ...] = RETRIEVAL_CASES,
    k: int = DEFAULT_K,
) -> RetrievalEvalReport:
    results = []
    for case in cases:
        book_id, by_label = seed_case_memories(session, case.memories)
        retrieved_ids = {
            memory.id
            for memory in retrieve_memories(
                session,
                media_item_id=book_id,
                query=case.query,
                current_ordinal=case.current_ordinal,
                limit=k,
            )
        }
        relevant = set(case.relevant_labels)
        found = {
            label
            for label, memory in by_label.items()
            if label in relevant and memory.id in retrieved_ids
        }
        recall = len(found) / len(relevant) if relevant else 1.0
        results.append(
            RetrievalCaseResult(
                label=case.label,
                recall=recall,
                missing_labels=tuple(sorted(relevant - found)),
            )
        )

    recall_at_k = sum(r.recall for r in results) / len(results) if results else 0.0
    return RetrievalEvalReport(k=k, recall_at_k=recall_at_k, results=tuple(results))
