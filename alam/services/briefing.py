"""Briefing generation and retrieval (M6 session 4).

Book-scoped, but pre-book — no ``ReaderContext``, since a briefing is only
generated for a book with no active ``ReadingSession`` yet (the router
checks this before calling in; see ``api/routers/books.py``). Personalizes
using the reader's own facts/memories, library-wide (from *other* books),
matched against the candidate's own catalog ``subjects`` if
``CatalogProvider`` (ADR-0015) has fetched them. The LLM only selects which
of the reader's own facts/memories to cite — it never writes prose about
the candidate itself; the teaser shown alongside the citations is always
composed by ALAM from the candidate's own stored catalog entry, never
touched by the LLM. This is why no Layer 3 leak check runs here, the same
deviation ADR-0014 already recorded for recommendations: the response
schema (``ai/synthesis/briefing.py``) has no field an LLM-authored
characterization of the candidate's content could occupy, so groundedness
(citation existence, ``domain/recommendation_groundedness.py``, reused
unchanged) is the only check needed.

Row lifecycle, same commit/rollback discipline ``services/journey_summary.py``
and ``services/recommendations.py`` both already use: a ``pending`` row is
written and *committed* before any LLM call, so a crash or an error response
later in the same request cannot roll the write back with it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alam.ai.prompts.briefing import PROMPT_VERSION_ID as BRIEFING_PROMPT_VERSION_ID
from alam.ai.prompts.briefing import build_briefing_prompt
from alam.ai.prompts.recommendations import FactForPrompt, MemoryForPrompt
from alam.ai.providers import get_llm_provider
from alam.ai.synthesis.briefing import BRIEFING_RESPONSE_SCHEMA, parse_briefing_response
from alam.domain.catalog_metadata import catalog_entry, has_catalog_content
from alam.domain.recommendation_groundedness import CitationCheck, find_ungrounded_citations
from alam.domain.synthesis_staleness import is_briefing_stale
from alam.persistence.models.briefing import Briefing, BriefingStatus
from alam.persistence.repositories.briefings import BriefingRepository
from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.memories import MemoryRepository
from alam.persistence.repositories.preference_facts import PreferenceFactRepository

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

    from alam.persistence.models.media_item import MediaItem
    from alam.persistence.models.memory import Memory
    from alam.persistence.models.preference_fact import PreferenceFact


class UnknownMediaItemError(LookupError):
    """The book a briefing was requested for doesn't exist. Shouldn't
    happen given the router already resolved and owner-checked it, kept
    explicit rather than trusted implicitly."""


class BriefingBlockedError(RuntimeError):
    """A freshly generated briefing cited a fact/memory id that doesn't
    exist or doesn't belong to the reader
    (``domain.recommendation_groundedness``). The row is persisted
    ``blocked_ungrounded`` for audit; its claims must never reach a caller.
    The router turns this into an error response, never a silent fallback
    to a stale cached row."""


class BriefingGenerationError(RuntimeError):
    """Generation failed for a reason other than an ungrounded citation — a
    response that didn't parse, most likely. The row is persisted
    ``failed`` with the error recorded, so a retry has something to find."""


def get_or_generate_briefing(session: Session, *, media_item_id: uuid.UUID) -> Briefing:
    """Returns the latest ``complete`` artifact if one exists and is not
    stale; otherwise generates fresh, persists the result, and returns it.

    ``user_id`` is not a parameter — it's read off the media item itself
    (``MediaItem.user_id``), since a briefing is always scoped to exactly
    one book and there is no separate caller-supplied ownership to
    reconcile it against (the router already did that check before this is
    ever called)."""
    item = MediaItemRepository(session).get(media_item_id)
    if item is None:
        raise UnknownMediaItemError(f"no media item {media_item_id}")

    facts = PreferenceFactRepository(session).list_active_for_user(item.user_id)
    fact_snapshot = frozenset(str(f.id) for f in facts)
    catalog_present = has_catalog_content(item.attributes)

    briefings = BriefingRepository(session)
    existing = briefings.get_latest_for_media_item(media_item_id)

    if existing is not None and existing.status is BriefingStatus.COMPLETE:
        stale = is_briefing_stale(
            generated_fact_snapshot=frozenset(existing.generated_fact_snapshot),
            current_fact_snapshot=fact_snapshot,
            generated_catalog_present=existing.generated_catalog_present,
            current_catalog_present=catalog_present,
            artifact_prompt_version_id=existing.prompt_version_id or "",
            current_prompt_version_id=BRIEFING_PROMPT_VERSION_ID,
        )
        if not stale:
            return existing

    return _generate(
        session,
        item=item,
        facts=facts,
        fact_snapshot=fact_snapshot,
        catalog_present=catalog_present,
    )


def _generate(
    session: Session,
    *,
    item: MediaItem,
    facts: Sequence[PreferenceFact],
    fact_snapshot: frozenset[str],
    catalog_present: bool,
) -> Briefing:
    briefings = BriefingRepository(session)
    memories = MemoryRepository(session).list_for_user(item.user_id)

    if not facts and not memories:
        # Nothing citable exists at all — an LLM call would only ever
        # select from two empty lists. No prompt_version_id/model to
        # record, same as recommendations' empty-shelf short circuit; the
        # teaser (if any) still renders from the item's own catalog entry,
        # composed by the router, independent of this row.
        row = briefings.create_pending(
            media_item_id=item.id,
            generated_fact_snapshot=sorted(fact_snapshot),
            generated_catalog_present=catalog_present,
        )
        result = briefings.mark_complete(row, claims=[], model=None, prompt_version_id=None)
        session.commit()
        return result

    row = briefings.create_pending(
        media_item_id=item.id,
        generated_fact_snapshot=sorted(fact_snapshot),
        generated_catalog_present=catalog_present,
    )
    session.commit()  # durable before the LLM call — see the module docstring

    subjects = (catalog_entry(item.attributes) or {}).get("subjects", [])

    try:
        prompt = build_briefing_prompt(
            book_title=item.title,
            book_author=item.attributes.get("author"),
            subjects=subjects,
            facts=[FactForPrompt(id=str(f.id), statement=f.statement) for f in facts],
            memories=[MemoryForPrompt(id=str(m.id), content=m.content) for m in memories],
        )
        completion = get_llm_provider().complete(
            prompt,
            prompt_version_id=BRIEFING_PROMPT_VERSION_ID,
            response_schema=BRIEFING_RESPONSE_SCHEMA,
        )
        draft = parse_briefing_response(completion.text)

        citation_checks = [
            CitationCheck(media_item_id=str(item.id), cites_type=c.type, cites_id=c.id)
            for c in draft.cites
        ]
        ungrounded = find_ungrounded_citations(
            citation_checks,
            valid_fact_ids=frozenset(str(f.id) for f in facts),
            valid_memory_ids=frozenset(str(m.id) for m in memories),
        )
    except Exception as exc:
        # Same idiom `services/journey_summary.py` and
        # `services/recommendations.py` both use: rollback first to discard
        # whatever this attempt left uncommitted, then write the failure
        # against a clean transaction.
        session.rollback()
        briefings.mark_failed(row, error=str(exc))
        session.commit()
        raise BriefingGenerationError(str(exc)) from exc

    if ungrounded:
        briefings.mark_blocked_ungrounded(
            row,
            model=completion.model,
            prompt_version_id=BRIEFING_PROMPT_VERSION_ID,
            ungrounded_citations=[
                {"cites_type": c.cites_type, "cites_id": c.cites_id} for c in ungrounded
            ],
        )
        session.commit()
        raise BriefingBlockedError(
            f"briefing for media item {item.id} contained an ungrounded citation"
        )

    result = briefings.mark_complete(
        row,
        claims=_resolve_claims(draft.cites, facts=facts, memories=memories),
        model=completion.model,
        prompt_version_id=BRIEFING_PROMPT_VERSION_ID,
    )
    session.commit()
    return result


def _resolve_claims(
    citations: Sequence[Any], *, facts: Sequence[PreferenceFact], memories: Sequence[Memory]
) -> list[dict[str, Any]]:
    """Every claim's displayed text is copied verbatim from the cited
    record's own stored text — never composed or paraphrased here, and
    never anything the LLM wrote (same discipline ADR-0014 established)."""
    fact_by_id = {str(f.id): f for f in facts}
    memory_by_id = {str(m.id): m for m in memories}
    return [
        {
            "text": (
                fact_by_id[c.id].statement
                if c.type == "preference_fact"
                else memory_by_id[c.id].content
            ),
            "cites_type": c.type,
            "cites_id": c.id,
        }
        for c in citations
    ]
