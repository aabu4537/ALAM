# ADR-0013: Persisted synthesis artifacts, and Layer 3 ships in M6

**Status:** Accepted
**Date:** 2026-08-01

## Context

M6 is ALAM's synthesis milestone — the first milestone that generates prose
(a journey summary, later a recommendation's explanation, later a
pre-book briefing) rather than retrieving or classifying records that
already exist. Two things needed deciding before session 1 (journey
summaries) could be built, neither settled by an earlier ADR:

**What does generating and returning one of these look like, end to end?**
Every prior milestone's writes are either extraction (memory rows derived
1:1 from a transcript) or lifecycle updates (a prediction's status). A
journey summary has neither shape — it is freeform text, generated
on-demand, that should not be silently regenerated on every read (cost,
latency) but also should not be served stale forever.

**Does Layer 2 and Layer 3 of ADR-0002's four-layer spoiler containment
scheme ship now, or stay deferred?** ADR-0002 built Layer 1 (the ordinal
SQL predicate) and Layer 4 (the adversarial eval set) at M3, and recorded
Layer 2 (a system prompt stating the reader's position) and Layer 3 (a
classifier checking a draft against excluded content) as "Decided, not
implemented" — correctly, at the time, because no synthesis response
existed anywhere in the codebase for either layer to apply to. `alam/
services/journey_summary.py` is the first such response. The M6 readiness
audit (`docs/milestones/M6-open-questions.md`) didn't cover this directly;
it surfaced during session 1 planning and was put to the user explicitly
(see that doc's §6 for the resolution note).

## Decision

### Persisted-artifact pattern

Each synthesis artifact type gets its own table — `journey_summaries` for
session 1 — matching the project's existing style of one table per concept
(`memories`, `predictions`, `preference_facts`) rather than one polymorphic
table. Common shape:

```
journey_summaries
  id                    UUIDv7 PK
  media_item_id         FK -> media_items, ON DELETE CASCADE
  status                enum: pending | complete | failed | blocked_leaked
  generated_at_ordinal  int, the reader's current_ordinal at row creation
  prompt_version_id     str, nullable until complete
  model                 str, nullable until complete
  draft                 text, nullable until complete
  layer3_leaked         bool, nullable until the Layer 3 check runs
  layer3_spans          JSONB, what Layer 3 flagged, if anything
  excluded_snapshot     JSONB, the memory ids/content retrieved but
                         excluded by the ordinal filter, kept for audit
  error                 text, nullable, set on status=failed
  created_at / updated_at
```

Generation is **synchronous, inside the API request** — these are
on-demand reads ("summarize my journey so far"), not background
maintenance like consolidation or prediction resolution, so there is no
reason to push them through the job queue.

Row lifecycle, all inside one request:

1. Write the row `status=pending`, `generated_at_ordinal` captured now, and
   flush it before calling the LLM. A crash or timeout after this point
   leaves a `pending` row a retry can find and overwrite, not a lost call
   with no record — the same "nothing is thrown away" instinct behind
   every other append-mostly table in this schema.
2. Build the prompt from `ReaderContext`-scoped memories (and whatever else
   the artifact type needs — journey summaries add predictions via
   `services.predictions.list_predictions_for_book`, already
   ordinal-masked per ADR-0012). Call the LLM with `response_schema`
   (schema-constrained decoding, `ai/extraction/memories.py`'s pattern —
   not the older plain-JSON-in-prompt pattern `consolidation.py`/
   `prediction_resolution.py` use, since this is new code with no reason to
   propagate the weaker one).
3. Run the Layer 3 classifier against the draft.
4. `leaked=True` → `status=blocked_leaked`. The draft is retained on the
   row for audit but is never serialized in the API response — the service
   raises instead of returning it, and the router turns that into a 503,
   never a silent fallback to a stale cached row.
5. Else → `status=complete` with the draft, model, and `prompt_version_id`.

### Staleness

A cached artifact is stale — regenerate on next read rather than serve it
— when the reader's `current_ordinal` has advanced past a per-artifact-type
threshold since `generated_at_ordinal`, or when the artifact's
`prompt_version_id` no longer matches the prompt currently in use:

```python
def is_artifact_stale(
    *,
    generated_at_ordinal: int,
    current_ordinal: int,
    ordinal_threshold: int,
    artifact_prompt_version_id: str,
    current_prompt_version_id: str,
) -> bool:
    return (
        current_ordinal - generated_at_ordinal >= ordinal_threshold
        or artifact_prompt_version_id != current_prompt_version_id
    )
```

Not on every new memory — that would regenerate (and re-spend an LLM call)
on every single capture. Lives in `alam/domain/synthesis_staleness.py`
(CLAUDE.md rule 3: pure, no I/O), unit-tested in isolation, same shape as
`domain/prediction_resolution.is_due_for_resolution`. `ordinal_threshold`
is a per-artifact-type constant (`journey_summary.py`'s `ORDINAL_THRESHOLD
= 5`), not a setting — tuned per type as each is built, not speculatively
now; a journey summary and a future briefing have no reason to share one
number.

### Layer 3: structured leak classifier ships in M6, not deferred further

**Decision, put to the user directly, overriding the cheaper default of
leaving it for whenever cost/latency forced the question: Layer 3 ships as
part of M6 session 1.**

Rationale, verbatim-close: Layer 1's `leakage_rate=0.0` measures
*retrieval* — whether a memory past the reader's ordinal ever reaches a
prompt. It says nothing about *generation*. A model handed a prompt
containing only permitted memories can still leak a future event by
inference in its own prose — paraphrase, a plausible-sounding synthesis, or
connecting dots the reader hasn't reached yet, none of which Layer 1 has
any way to catch since the excluded content never entered the prompt in
the first place. M6 is the first milestone where that failure mode can
even occur, which makes it the first place closing it stops being
speculative work built ahead of a concrete need (the same
build-ahead-of-need pattern ADR-0003 and the M6 audit both already
flagged once).

**Not a second freeform generation — a schema-constrained classification
call.** Input: the draft, plus the content the ordinal filter excluded
during retrieval (`excluded_snapshot` above — nothing new to compute, the
generation step already has this list, it just has to not discard it
before the check runs). Output via `response_schema`:

```python
class LeakCheckResult(BaseModel):
    leaked: bool
    spans: list[str]  # verbatim substrings of the draft that leak, empty if leaked=False
```

Lives in `alam/ai/synthesis/leak_check.py`, parallel to `ai/extraction/`
and `ai/consolidation/`, with its own prompt (`ai/prompts/leak_check.py`)
and its own `PROMPT_VERSION_ID` — rule 6 applies to this call exactly as it
does to the one that produced the draft being checked, since it is a
separate LLM call with its own provenance. Runs once per persisted
artifact (generation time), never once per read of an already-`complete`
cached row — a cached artifact is never re-checked until staleness forces
regeneration.

**Layer 2 landed alongside it, for the same reason: it had no caller
either.** `ai/prompts/journey_summary.py` states the reader's current
position and instructs the model not to draw on anything past it or on
outside knowledge of the book. Layer 2 alone is not a guarantee — nothing
stops a model from ignoring the instruction, which is exactly why Layer 3
checks the *output* rather than trusting the *instruction*.

### Eval: `synthesis_leakage_rate`

M6's headline number, parallel to M3's `leakage_rate`, added in
`alam/eval/journey_summary_eval.py`. An adversarial case where the reader
is mid-book and a spoiler-shaped memory sits past their ordinal (excluded
from the prompt); asserts the Layer 3 verdict on the generated draft is
`leaked=False` and, as defense-in-depth on the check itself, that the
excluded memory's distinctive language does not appear verbatim in the
draft actually returned. Extended per artifact type as later M6 sessions
add recommendations and briefings.

Same caveat `extraction_eval.py` already documents for its own accuracy
number: **not a real quality signal while `ALAM_LLM_PROVIDER=fake`.**
`FakeLLM` has no real judgment about what constitutes a spoiler; the
harness supplies a canned, schema-valid narrative and a canned, clean
Layer 3 verdict so the plumbing — seeding, ordinal exclusion, prompt
assembly, the persisted row, the endpoint's response — is exercised end to
end. The substring check is real regardless of provider, though: it is a
plain check on the draft that was actually persisted and returned, so it
would catch a canned response that accidentally echoed spoiler text even
under `FakeLLM`.

## Consequences

**Positive.** One artifact lifecycle and one staleness *shape*, reused by
every later M6 session, rather than each session re-deriving its own
version of "when is this cached and safe to serve" from nothing. (Amendment,
M6 session 2: the Layer 3 classifier itself turned out not to generalize to
every artifact type — recommendations have no excluded-content set to check
a draft against, since they're library-wide with no ordinal and no
`CatalogProvider` yet. ADR-0014 covers what recommendations use instead and
why; Layer 3 was expected to apply again for briefings, session 4, once
`CatalogProvider` gave them real book content an ordinal filter could
exclude from.

Amendment, M6 session 4: it didn't, for the same underlying reason session
2 found — there is still no ordinal (a briefing is for a book with no
active reading session, i.e. no reading position at all) and no fixed,
enumerable "excluded content" list a classifier could check a draft
against. Briefings apply the same structural fix ADR-0014 validated
rather than inventing a new one; full design and rationale in ADR-0016.)

A `blocked_leaked` draft is never lost — it's on the row for audit — but
is also never one response-model field away from an accidental leak,
since the service raises instead of ever handing the row back to the
router in that status.

**Negative.** Layer 3 adds a second LLM call and its own latency to every
fresh generation, exactly the cost ADR-0002's "Negative consequences"
section already named before any caller existed to spend it. Neither Layer
2 nor Layer 3 can be made perfect against a model's parametric knowledge of
a well-known book — the README must keep saying so. `synthesis_leakage_rate`
inherits the same "not real under `FakeLLM`" caveat every eval number in
this codebase carries until a real provider is configured.

## Alternatives considered

**Leave Layer 3 deferred, ship M6 session 1 on Layer 1 + Layer 4 alone.**
The cheaper default this ADR overrides. Rejected because M6 session 1 is
exactly the trigger ADR-0002 named for revisiting the deferral — generation
exists now, and Layer 1's 0.0 leakage rate would otherwise be read as a
stronger guarantee than it actually provides for generated text.

**A second freeform generation ("write this again, but check yourself for
spoilers") instead of a structured classifier.** Rejected — unmeasurable,
and doubles the chance of the second call itself introducing a new spoiler
rather than catching one. A narrow, schema-constrained classification
question ("does this leak *this specific excluded content*") is the
tractable version of the problem, per ADR-0002's own framing.

**One polymorphic `synthesis_artifacts` table instead of one table per
type.** Rejected for the same reason `memories`/`predictions`/
`preference_facts` are separate tables already — a shared table makes every
artifact-specific column (a briefing's catalog metadata, a recommendation's
citation list) either nullable noise on every other type's rows or a JSONB
blob that loses the schema validation a real column gives for free.
