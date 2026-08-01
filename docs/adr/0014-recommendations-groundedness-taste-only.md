# ADR-0014: Recommendations use deterministic groundedness instead of Layer 3, and are taste-only until CatalogProvider exists

**Status:** Accepted
**Date:** 2026-08-01

## Context

M6 session 2 (recommendations) is the second synthesis artifact built on
ADR-0013's shared pattern: persisted rows, a staleness check, and a safety
check that runs once per generation before a draft is ever returned.
Session 1 (journey summaries) used Layer 3 (`ai/synthesis/leak_check.py`) —
a schema-constrained classifier checking a draft against the specific
content the ordinal filter excluded from that book's prompt — for its
safety check. The session 2 plan sketch (written during M6's kickoff,
before this session's design pass) assumed recommendations would reuse
Layer 3 unchanged. Two things surfaced during this session's planning that
made that assumption wrong.

**First: there is no excluded-content set for Layer 3 to check a draft
against.** Layer 3's whole shape depends on a single book and a reader
ordinal — "did the draft leak anything from *this specific set* of
memories/predictions the ordinal filter excluded." Recommendations are
library-wide (no `ReaderContext`, no ordinal, no single book — same
difference `taste_drift` already has from `journey_summary`), and
`CatalogProvider` (session 3) doesn't exist yet, so no information about a
to-read candidate's plot ever enters the prompt at all. There is nothing
for Layer 3 to check a draft against except an always-empty set, which
would make every verdict `leaked=False` unconditionally — a check that
cannot fail is worse than no check, since it would read as a real
guarantee.

**Second, found in review after an initial design that reused
`recommendation_groundedness` as originally sketched — a citation-existence
check alone doesn't catch what matters:** it catches a claim citing an id
that doesn't exist. It does not catch a claim that cites a *real*
`preference_fact` but characterizes the *candidate book* — "its slow-burn
political intrigue matches your taste," citing a genuine fact about the
reader liking slow-burn political intrigue. The citation resolves; the
assertion about the book's content is invented; a citation-existence check
alone passes it. `response_schema` (schema-constrained decoding) enforces
shape, not the semantic content of a free-text string, so no `text: str`
field can be constrained to "only ever paraphrases the cited record, never
characterizes anything else."

## Decision

### The response schema has no field for a book characterization to occupy

Rather than police a free-text field's content, the field is removed. The
LLM call's output (`ai/synthesis/recommendations.py`) is a **selection, not
prose**:

```python
class CitationRef(BaseModel):
    type: Literal["preference_fact", "memory"]
    id: str


class RecommendationDraft(BaseModel):
    media_item_id: str
    cites: list[CitationRef]  # ids only — no text field anywhere in this schema


class RecommendationSetDraft(BaseModel):
    recommendations: list[RecommendationDraft]
```

The only things the model produces are: which to-read candidate, and which
of the reader's own `preference_fact`/`memory` ids support recommending it.
There is no field anywhere in the schema an LLM-authored sentence about a
candidate's plot, genre, or themes could land in, regardless of what the
model attempts — the same move `VisibleStructureUnitResponse`
(`api/routers/books.py`) makes by omitting `first_lines` entirely rather
than filtering it out of a shared response shape. This is what makes a
hallucinated characterization of a to-read book **structurally
unrepresentable**, not merely detected after the fact.

### The displayed claim text is composed by ALAM, never by the LLM

`services/recommendations.py` resolves each cited id, after the LLM call
returns, to that record's own stored text — `PreferenceFact.statement` or
`Memory.content` — and uses that verbatim as the claim's `text`. The only
text a reader ever sees in a recommendation is text that already existed
*before this call ran*, written by an earlier consolidation or extraction
pass. Nothing the recommendations LLM call writes is ever serialized to a
caller.

### Groundedness narrows to citation-existence, and that's now sufficient

With the schema change above, the only thing left for
`domain/recommendation_groundedness.py` to check is whether a cited id
actually exists and belongs to the reader — a plain DB existence/ownership
lookup, fully deterministic, no LLM judge, exactly the framing the M6 plan
sketch already gave `recommendation_groundedness` before this session's
design pass narrowed what it needs to cover:

```python
def find_ungrounded_citations(
    citations: Sequence[CitationCheck],
    *,
    valid_fact_ids: frozenset[str],
    valid_memory_ids: frozenset[str],
) -> list[CitationCheck]: ...
```

Any ungrounded citation blocks the whole recommendation set
(`status=blocked_ungrounded`) — same all-or-nothing severity
`blocked_leaked` uses today, not a partial response with some candidates
silently dropped. This is strictly cheaper than Layer 3 too: one DB query
against ids already fetched to build the prompt, no second LLM call.

### Recommendations are deliberately taste-only in session 2

Every claim a recommendation makes is about the *reader* — what they've
said or been observed to prefer — never about the *candidate book*. This is
not a temporary gap being silently accepted; it's the direct consequence of
`CatalogProvider` not existing yet (M6's build order, `docs/milestones/M6-open-questions.md`):
ALAM has no legitimate source for a to-read book's plot, genre, or themes
until session 3 builds one, so recommendations in session 2 make no claims
about that at all. **`CatalogProvider` (session 3) is what unblocks any
claim about a candidate's actual content** — the same dependency briefings
(session 4) have, and for the same reason: neither artifact type can
honestly say anything about a book's content without a real source for it.

## Consequences

**Positive.** A hallucinated plot/genre/theme claim about a to-read book is
impossible to serialize, not just unlikely to slip through a check — the
schema itself is the guarantee. Cheaper than Layer 3 (no second LLM call).
Recommendations are honest about what they're grounded in: taste evidence
the reader already produced, nothing invented about the book itself.

**Negative.** Recommendations in session 2 can't yet say anything like "you
might like this because it's got the political intrigue you enjoy" in the
persuasive, book-aware way a reader might expect from a recommendation —
every claim reads as "here's something you said/were observed to like,"
not a synthesis connecting that to the candidate's actual content. That's
the taste-only limitation above, not a bug; it lifts once `CatalogProvider`
exists.

**Amendment, M6 session 3 (ADR-0015): this lifted, per-candidate, not all
at once.** `CatalogProvider` now exists; a candidate the backfill has
reached can be cited with a real, catalog-sourced claim about its own
content (`type="catalog"`), using the identical "no field for unsourced
content" structural discipline this ADR established — the citation schema
widened rather than gaining an exception. A candidate not yet backfilled
is still exactly taste-only, as described above; nothing here changed for
it.

## Alternatives considered

**Reuse Layer 3 unchanged, as the session 2 sketch originally assumed.**
Rejected — there is no excluded-content set for a library-wide artifact
with no `CatalogProvider`, so this would only be a classifier that always
sees an empty set and always returns `leaked=False`. A check that cannot
fail provides negative value: it reads as a real guarantee while providing
none.

**Keep a free-text `text` field on `Claim` and rely on citation-existence
groundedness alone**, as this session's own first draft did before review.
Rejected — demonstrated insufficient by direct counterexample: a claim can
cite a real fact while asserting something invented about the candidate,
and an existence check on the citation alone cannot see that. The fix had
to remove the field the assertion would occupy, not add a second check on
top of it.

**Keep the free-text field but add an LLM-based classifier (Layer-3-shaped)
checking whether a claim's text stays "on-topic" about the reader rather
than the book.** Rejected as unnecessary complexity once the schema-level
fix was found: a semantic classifier is the right tool when the thing being
checked is inherently semantic (Layer 3's actual job — "does this leak
*specific* excluded content"); whether a field exists at all is not a
semantic question, and solving it structurally is strictly simpler and
strictly stronger than solving it with another model call.
