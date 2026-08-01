"""Recommendation generation and retrieval (M6 session 2, ADR-0014).

Library-wide, not book-scoped — no ``ReaderContext``, resolved by
``user_id`` alone, same as ``services/taste_drift.py``. Candidates are the
reader's own to-read shelf; the LLM selects which of them to recommend and
which of the reader's own facts/memories support each selection (never
prose about the candidate itself — see ``ai/synthesis/recommendations.py``
and ADR-0014). The displayed claim text is composed here, from the cited
record's own stored text, never from anything the LLM wrote.

Row lifecycle, same commit/rollback discipline
``services/journey_summary.py`` established (and the bug session 1 found
the hard way, via manual verification, applied here from the first draft):
a ``pending`` row is written and *committed* before any LLM call, so a
crash or an error response later in the same request cannot roll the write
back with it. Whatever happens next — a parse failure, a blocked
generation, an unhandled exception — rolls back only that attempt's
uncommitted work and commits the row's terminal status on its own,
independent of whether the route ultimately returns 200 or raises.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alam.ai.prompts.recommendations import PROMPT_VERSION_ID as RECOMMENDATIONS_PROMPT_VERSION_ID
from alam.ai.prompts.recommendations import (
    CandidateBook,
    FactForPrompt,
    MemoryForPrompt,
    build_recommendations_prompt,
)
from alam.ai.providers import get_llm_provider
from alam.ai.synthesis.recommendations import (
    RECOMMENDATION_RESPONSE_SCHEMA,
    parse_recommendation_response,
)
from alam.domain.recommendation_groundedness import CitationCheck, find_ungrounded_citations
from alam.domain.synthesis_staleness import is_recommendation_set_stale
from alam.persistence.models.recommendation import Recommendation, RecommendationStatus
from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.memories import MemoryRepository
from alam.persistence.repositories.preference_facts import PreferenceFactRepository
from alam.persistence.repositories.recommendations import RecommendationRepository

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from alam.ai.synthesis.recommendations import RecommendationDraft
    from alam.persistence.models.media_item import MediaItem
    from alam.persistence.models.memory import Memory
    from alam.persistence.models.preference_fact import PreferenceFact


class RecommendationsBlockedError(RuntimeError):
    """A freshly generated recommendation set cited a fact/memory id that
    doesn't exist or doesn't belong to the reader
    (``domain.recommendation_groundedness``). The row is persisted
    ``blocked_ungrounded`` for audit; its candidates must never reach a
    caller. The router turns this into an error response, never a silent
    fallback to a stale cached row."""


class RecommendationsGenerationError(RuntimeError):
    """Generation failed for a reason other than an ungrounded citation — a
    response that didn't parse, most likely. The row is persisted
    ``failed`` with the error recorded, so a retry has something to find."""


def get_or_generate_recommendations(session: Session, *, user_id: uuid.UUID) -> Recommendation:
    """Returns the latest ``complete`` artifact if one exists and is not
    stale; otherwise generates fresh, persists the result, and returns it.

    ``user_id`` is assumed to be a real, existing owner — resolved by the
    caller (``UserRepository.get_owner()``, same as
    ``services/taste_drift.py``) before this is ever called."""
    shelf = _to_read_shelf(session, user_id=user_id)
    shelf_snapshot = frozenset(str(item.id) for item in shelf)
    facts = PreferenceFactRepository(session).list_active_for_user(user_id)
    fact_snapshot = frozenset(str(f.id) for f in facts)

    recommendations = RecommendationRepository(session)
    existing = recommendations.get_latest_for_user(user_id)

    if existing is not None and existing.status is RecommendationStatus.COMPLETE:
        stale = is_recommendation_set_stale(
            generated_shelf_snapshot=frozenset(existing.generated_shelf_snapshot),
            current_shelf_snapshot=shelf_snapshot,
            generated_fact_snapshot=frozenset(existing.generated_fact_snapshot),
            current_fact_snapshot=fact_snapshot,
            artifact_prompt_version_id=existing.prompt_version_id or "",
            current_prompt_version_id=RECOMMENDATIONS_PROMPT_VERSION_ID,
        )
        if not stale:
            return existing

    return _generate(
        session,
        user_id=user_id,
        shelf=shelf,
        shelf_snapshot=shelf_snapshot,
        facts=facts,
        fact_snapshot=fact_snapshot,
    )


def _to_read_shelf(session: Session, *, user_id: uuid.UUID) -> Sequence[MediaItem]:
    items = MediaItemRepository(session).list_for_user(user_id)
    return [item for item in items if item.attributes.get("exclusive_shelf") == "to-read"]


def _generate(
    session: Session,
    *,
    user_id: uuid.UUID,
    shelf: Sequence[MediaItem],
    shelf_snapshot: frozenset[str],
    facts: Sequence[PreferenceFact],
    fact_snapshot: frozenset[str],
) -> Recommendation:
    recommendations = RecommendationRepository(session)

    if not shelf:
        # Nothing to recommend from — no LLM call needed, so no
        # prompt_version_id/model to record (the one case a `complete` row
        # doesn't carry them; see the model docstring and the router).
        row = recommendations.create_pending(
            user_id=user_id,
            generated_shelf_snapshot=sorted(shelf_snapshot),
            generated_fact_snapshot=sorted(fact_snapshot),
        )
        result = recommendations.mark_complete(
            row, candidates=[], model=None, prompt_version_id=None
        )
        session.commit()
        return result

    row = recommendations.create_pending(
        user_id=user_id,
        generated_shelf_snapshot=sorted(shelf_snapshot),
        generated_fact_snapshot=sorted(fact_snapshot),
    )
    session.commit()  # durable before the LLM call — see the module docstring

    memories = MemoryRepository(session).list_for_user(user_id)

    try:
        prompt = build_recommendations_prompt(
            candidates=[
                CandidateBook(
                    media_item_id=str(item.id),
                    title=item.title,
                    author=item.attributes.get("author"),
                )
                for item in shelf
            ],
            facts=[FactForPrompt(id=str(f.id), statement=f.statement) for f in facts],
            memories=[MemoryForPrompt(id=str(m.id), content=m.content) for m in memories],
        )
        completion = get_llm_provider().complete(
            prompt,
            prompt_version_id=RECOMMENDATIONS_PROMPT_VERSION_ID,
            response_schema=RECOMMENDATION_RESPONSE_SCHEMA,
        )
        draft = parse_recommendation_response(completion.text)

        citation_checks = [
            CitationCheck(media_item_id=rec.media_item_id, cites_type=c.type, cites_id=c.id)
            for rec in draft.recommendations
            for c in rec.cites
        ]
        ungrounded = find_ungrounded_citations(
            citation_checks,
            valid_fact_ids=frozenset(str(f.id) for f in facts),
            valid_memory_ids=frozenset(str(m.id) for m in memories),
        )
    except Exception as exc:
        # Same idiom `services/journey_summary.py` uses: rollback first to
        # discard whatever this attempt left uncommitted, then write the
        # failure against a clean transaction.
        session.rollback()
        recommendations.mark_failed(row, error=str(exc))
        session.commit()
        raise RecommendationsGenerationError(str(exc)) from exc

    if ungrounded:
        recommendations.mark_blocked_ungrounded(
            row,
            model=completion.model,
            prompt_version_id=RECOMMENDATIONS_PROMPT_VERSION_ID,
            ungrounded_citations=[
                {
                    "media_item_id": c.media_item_id,
                    "cites_type": c.cites_type,
                    "cites_id": c.cites_id,
                }
                for c in ungrounded
            ],
        )
        session.commit()
        raise RecommendationsBlockedError(
            f"recommendations for user {user_id} contained an ungrounded citation"
        )

    result = recommendations.mark_complete(
        row,
        candidates=_resolve_candidates(
            draft.recommendations, shelf=shelf, facts=facts, memories=memories
        ),
        model=completion.model,
        prompt_version_id=RECOMMENDATIONS_PROMPT_VERSION_ID,
    )
    session.commit()
    return result


def _resolve_candidates(
    draft_recommendations: Sequence[RecommendationDraft],
    *,
    shelf: Sequence[MediaItem],
    facts: Sequence[PreferenceFact],
    memories: Sequence[Memory],
) -> list[dict[str, Any]]:
    """Builds the persisted, reader-facing candidate list from the LLM's
    selection — every claim's ``text`` copied verbatim from the cited
    record's own stored text, never from anything the LLM wrote
    (ADR-0014). A ``media_item_id`` the LLM returned that isn't actually on
    the candidate shelf is dropped rather than surfaced — the schema can't
    constrain it to a specific set of ids, but there is nothing unsafe
    about silently omitting an unrecognized pick, unlike an ungrounded
    citation, which blocks generation outright."""
    shelf_by_id = {str(item.id): item for item in shelf}
    fact_by_id = {str(f.id): f for f in facts}
    memory_by_id = {str(m.id): m for m in memories}

    resolved = []
    for rec in draft_recommendations:
        book = shelf_by_id.get(rec.media_item_id)
        if book is None:
            continue
        claims = [
            {
                "text": (
                    fact_by_id[c.id].statement
                    if c.type == "preference_fact"
                    else memory_by_id[c.id].content
                ),
                "cites_type": c.type,
                "cites_id": c.id,
            }
            for c in rec.cites
        ]
        resolved.append({"media_item_id": rec.media_item_id, "title": book.title, "claims": claims})
    return resolved
