# ADR-0016: Briefings are pre-book, and reuse recommendations' groundedness scheme instead of Layer 3

**Status:** Accepted
**Date:** 2026-08-01

## Context

M6 session 4 (briefings) is the last of M6's three deliverables
(`docs/milestones.md`: spoiler-safe pre-book briefings, reading journey
summaries, recommendations with explanations). Unlike the prior two
sessions, no ADR or milestone doc defines what a "briefing" actually
generates or how it's triggered — this session designs that from scratch,
the same way session 2 designed recommendations' groundedness scheme.

Two things needed deciding, both derived from re-reading ADR-0010 closely
(its running example: *"this opens similarly to the book you read last
spring" — a claim from metadata and memory similarity, not from having
read either book*) and ADR-0002's own note ("It now matters for pre-book
briefings and between-session questions, not for live chat").

## Decision

### A briefing is for a book the reader has not started — "pre-book," literally

Trigger condition: no active `ReadingSession` exists yet for the media
item (`ReadingSessionRepository.get_active_for_media_item` returns
`None`). This is the universal, media-source-agnostic version of "not
started" — it works for EPUB-ingested books too, not just Goodreads'
`exclusive_shelf == "to-read"` (which recommendations uses, but which no
EPUB-only book ever has). `GET /books/{id}/briefing` refuses with `409`
once an active session exists, pointing at `.../journey-summary` instead —
same "two routes, not a mode switch" precedent `GET /structure` vs
`GET /chapters` already established for the identical shaped problem
(ADR-0002 amendment).

Because there is no reading position, there is no `ReaderContext` to
construct — `.../briefing` is a documented `tests/test_reader_context_coverage.py`
exemption, same category as `/recommendations` and `/preferences/taste-drift`.

### Layer 3 does not apply here either — same deviation ADR-0014 already recorded for recommendations, for the identical underlying reason

ADR-0013's Consequences section, written at session 3, predicted Layer 3
would return once `CatalogProvider` gave briefings "real book content an
ordinal filter can exclude from." It doesn't, for the same reason session
2 found for recommendations: there is no ordinal for a book not yet
started, and the only content available — the candidate's own catalog
`blurb`/`subjects` — is fetched once, whole-book, not staged by reading
position. There is no fixed, enumerable "excluded content" list a
classifier could check a draft against.

The actual spoiler risk here is structurally identical to recommendations':
an LLM asked to write personalized prose about *why this book fits the
reader* could invent or paraphrase in a real plot spoiler from its
parametric knowledge, and Layer 3 has nothing to check that against. This
ADR applies the fix ADR-0014 already validated: **structural
unrepresentability, not detection.**

```python
# Narrower than RecommendationDraft's CitationRef — no "catalog" option
# is ever offered.
class BriefingCitationRef(BaseModel):
    type: Literal["preference_fact", "memory"]
    id: str


class BriefingDraft(BaseModel):
    cites: list[BriefingCitationRef]
```

The LLM never writes prose about the candidate book at all — only the
teaser (the candidate's own cached `blurb`/`subjects`) is shown, and that
text is Open Library's own, composed by ALAM directly in the router, never
touched by the briefing LLM. The one LLM call a briefing makes only
selects which of the reader's own `preference_fact`/`memory` ids (from
*other* books) are worth citing as personalization.

`BriefingCitationRef.type` is deliberately narrower than
`RecommendationDraft`'s `CitationRef.type` — it excludes `"catalog"`
outright, not merely by validating a stray citation to failure. A
briefing's teaser is never LLM-cited, so offering `"catalog"` as an option
would be exactly the kind of "detect after the fact" gap this project's
structural-unrepresentability discipline exists to avoid. Groundedness
(citation existence) is the only check needed, reusing
`domain/recommendation_groundedness.py` unchanged — it was already
citation-type-generic, not recommendation-specific despite the module
name.

### Personalization draws on the reader's library-wide facts/memories, matched against the candidate's subjects

The prompt (`ai/prompts/briefing.py`) gives the model the candidate's
`subjects` (never its `blurb` — subjects are enough for relevance-matching,
and keeping blurb text out of the prompt removes any reason for the model
to echo or paraphrase it) plus the reader's active facts and memories,
library-wide — same `list_active_for_user`/`list_for_user` calls
recommendations already makes, no book-scoped filter needed since a
not-yet-started book has no memories of its own to accidentally include.
The model selects 0-3 citations; nothing else.

### Staleness has no ordinal to threshold against either

`domain/synthesis_staleness.is_briefing_stale` is a third shape, set-equality
on the reader's active fact ids (same as `is_recommendation_set_stale`, no
memory-set tracking either — matching that function's existing scope
decision) plus whether the candidate's catalog entry went from absent to
present — a real gap: a briefing generated before the session-3 backfill
reaches a book has no teaser to show; once the backfill populates it, the
next read should regenerate to surface it rather than serve a
personalization-only row forever.

## Consequences

**Positive.** Reuses, rather than reinvents, every mechanism ADR-0014
already validated: the citation-only schema shape, `find_ungrounded_citations`,
the "ALAM composes displayed text" discipline, the `blocked_ungrounded`
severity. A hallucinated claim about a not-yet-started book's plot is
structurally impossible to serialize, not just unlikely to slip through a
check.

**Negative.** Same limitation recommendations had before `CatalogProvider`
existed, now permanent rather than temporary for the *personalization*
half of a briefing specifically: it can never say anything like "the
opening chapters focus on X" — only "this connects to something you said
about another book," plus whatever the candidate's own official blurb
says verbatim. Two prior predictions in this codebase turned out wrong in
the same direction (ADR-0013 for recommendations, then again here) —
worth registering as a pattern: **an ordinal-scoped classifier
(Layer 3) is the right tool for a book the reader has an actual position
in; every other M6 artifact type so far has turned out to need the
schema-level fix instead.**

## Alternatives considered

**Let the model write a short teaser paraphrasing the official blurb,
checked by a groundedness-shaped classifier ("does this teaser assert
anything the blurb doesn't support").** Considered, since it would produce
a more natural-reading briefing than pasting Open Library's blurb
verbatim. Rejected: it reintroduces a free-text field and a second LLM
call to do exactly what removing the field does for free, and this
project's established preference (session 2's explicit feedback) is
structural prevention over detection whenever a schema-level fix exists.

**Trigger a briefing off `exclusive_shelf == "to-read"` instead of "no
active `ReadingSession`."** Rejected — no EPUB-ingested book (this
project's other real ingestion path, alongside Goodreads CSV import) ever
has `exclusive_shelf` set, which would make briefings silently
Goodreads-only. The reading-session check is the media-source-agnostic
version of the same "not started" concept.
