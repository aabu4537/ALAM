# M6 open questions

Companion to the M6 architecture audit. Each section: what the code shows
today, the decision that finding forces before M6 can start, and the
options with tradeoffs. No recommendation is embedded in the options list —
these are calls for a human to make.

**Status, 2026-08-01: all five resolved.** Questions 3 and 4 were answered
by work that landed before this doc was read again — the ReaderContext /
`get_reader_context` hardening pass and the `llm_calls` instrumentation +
real-provider work, both merged ahead of M6 starting. Questions 1, 2, and
the memory-deletion item under 5 were put to the user directly at M6's
start; resolutions are noted inline below. A sixth item, outside the
original five, was decided during M6 session 1 planning and is recorded in
§6: Layer 3 spoiler containment ships as part of M6 after all, once
session 1 gave it its first real caller.

---

## 1. Media generalization

**Finding.** The schema already generalizes correctly — every shared table
uses `media_item_id`, not `book_id` (ADR-0003 was followed). What's *not*
built is the thing ADR-0003 said would make the second module cheap: the
`MediaProvider` Protocol (`media/base.py`, three methods —
`search`/`fetch_metadata`/`normalize_progress`) doesn't exist. Only
`media/books/epub.py` exists, and it exports `parse_epub`, not those three
methods. Progress normalization is a free function
(`domain/reading_progress.py:compute_progress`) not attached to any
Protocol. Also, `/books` is hardcoded as the API router prefix
(`api/routers/books.py:38`).

**Decision this forces.** M6 is a good place to either (a) write the
`MediaProvider` Protocol now, so M6's metadata-fetch need (blurbs, themes,
series relationships — ADR-0010) has a real seam to slot into, or (b) let
M6 read/write `media_items.attributes` directly, same as every milestone so
far, and leave the Protocol for whenever a second media type is actually
built.

**Options:**

- **Write `media/base.py` now, as part of M6's metadata work.** Makes the
  ADR-0003 claim true before a second module needs it to be. Costs a
  Protocol definition plus retrofitting `epub.py` to implement it, with no
  second implementation yet to validate the shape against — the exact
  "wrong abstraction" risk ADR-0003 itself warns about.
- **Leave it aspirational, keep reading/writing `attributes` directly in
  M6 code.** Zero cost now. Means the ADR-0003 / `CLAUDE.md` architecture
  diagram overstates what's built until someone corrects it or builds the
  Protocol later — worth deciding whether that's an acceptable, temporary
  documentation gap.
- **Correct the documentation only** (ADR-0003, `CLAUDE.md`) to describe
  `MediaProvider` as planned/deferred rather than shipped, without writing
  the Protocol. Cheapest option that doesn't leave the docs wrong; doesn't
  advance the actual extensibility goal.

**Not forced by this milestone, but adjacent:** the `/books` URL prefix.
Nothing in M6 requires a second media type to exist, so this can be
deferred without cost — noted here only so it's not rediscovered as a
surprise when a second module eventually arrives.

**Resolved, 2026-08-01: defer.** Read/write `media_items.attributes`
directly in M6 code, same as every milestone so far. Zero cost now;
`media/base.py` stays aspirational until a second media type actually
needs the shape validated against something real. ADR-0003's own
"wrong abstraction" warning was the deciding factor.

---

## 2. `structure_ordinal` as a generic abstraction

**Finding.** The ordinal-comparison mechanics (`domain/spoiler_filter.py`,
the SQL predicates in `persistence/repositories/retrieval.py`) are fully
generic — plain integer comparison, no chapter semantics. But
`StructureUnitType` (`CHAPTER`/`EPISODE`/`SCENE`/`SEGMENT`) is never read
anywhere in the codebase (zero call sites reference `.unit_type`) and every
creation path defaults to or omits it, meaning it's always `CHAPTER` in
practice. `first_lines` and `chapter_count` (demo API) are book-shaped
field names. There's no slot for progress *within* a unit (a podcast
timestamp inside an episode) — only progress in terms of whole units.

**Decision this forces.** None of M6's three deliverables (briefings,
journey summaries, recommendations) obviously need `unit_type` to be
exercised or need sub-unit progress — they operate at the ordinal/unit
level already. This is a "confirm it's really not needed yet" checkpoint,
not a blocking build decision.

**Options:**

- **Do nothing for M6; leave `unit_type` unexercised.** Correct if M6
  genuinely never branches on media type at the structure-unit level, which
  the milestone's three deliverables suggest is true. Risk: the first real
  exercise of `unit_type` will be whenever a second media type arrives, at
  which point any latent chapter-assumption in downstream code (prompt
  templates that say "chapter," UI copy, etc.) surfaces all at once.
- **Add a lightweight check now** — e.g. a test asserting some code path
  behaves sanely for a non-`CHAPTER` unit — to catch chapter-assumptions
  early, without waiting for a second media type to prove it either way.
  Small cost, catches nothing that isn't already suspected.

**Resolved, 2026-08-01: do nothing.** Applied the sensible default rather
than escalating — this is a "confirm not needed" checkpoint, not a build
decision, and M6's three deliverables don't branch on `unit_type` per the
finding above. Not put to the user; revisit when a second media type
actually arrives.

---

## 3. Retrieval surface inventory

**Finding.** Full inventory with signatures, filter location, and
`current_ordinal` source is in the audit report (Section 3). Two load-bearing
facts:

- `retrieve_memories` (`ai/retrieval/hybrid.py:34`) — the hybrid search
  function M3 was built around — has **no production caller today**. It's
  only invoked from the eval harness (`eval/retrieval_eval.py`,
  `eval/spoiler_eval.py`). M6 will be its first real caller.
- Every listing function *other than* `retrieve_memories`
  (`MemoryRepository.list_for_media_item`, `.list_in_ordinal_range`,
  `PredictionRepository.list_for_media_item`,
  `list_predictions_for_book`) applies **no ordinal ceiling at all** — they
  return everything, or everything in a caller-supplied range, with no
  check against the reader's actual current position. They're safe today
  only because their current callers already have a legitimate reason to
  see the full set (an owner-scoped prediction-history display; a
  resolution job with an algorithmically bounded range). None of them
  derive `current_ordinal` themselves — every retrieval function in the
  inventory trusts the caller to supply the right one.

**Decision this forces.** Whether M6's retrieval calls go through a layer
that derives and enforces `current_ordinal` server-side, or continue the
existing pattern of trusting the caller — and, relatedly, whether the
functions with no ordinal ceiling at all get wrapped before anything new
calls them.

**Options:**

- **Add a server-side `current_ordinal` resolver** (e.g. a thin wrapper
  that takes `media_item_id`, looks up the active `ReadingSession` itself,
  and calls `retrieve_memories` — refusing to accept a caller-supplied
  ordinal at all) and require M6's synthesis code to go through it
  exclusively. Removes an entire class of "caller forgot to fetch the
  right ordinal" bug at the cost of one new function and a policy that M6
  code can't bypass it.
- **Keep the existing pattern** — every M6 caller resolves and passes
  `current_ordinal` itself, same as `retrieve_memories`'s current (only)
  callers do. Consistent with how M3–M5 already work, but means the safety
  property rests entirely on M6's code being written carefully, same as
  today's eval-harness-only callers.
- **Wrap the ordinal-less listing functions** (`list_for_media_item`,
  `list_in_ordinal_range`) with a ceiling check before M6 gains new callers
  for them, versus leaving them as-is on the grounds that M6's specific
  planned callers don't need an additional ceiling (e.g. a prediction
  history display legitimately wants to show resolved predictions the
  reader has already passed).
- **This inventory becomes literal agent tool definitions later** (per your
  framing) **or stays internal service functions M6 calls directly without
  ever exposing them as callable-by-an-LLM tools.** Which functions (if
  any) are safe to expose directly to a future tool-calling loop, versus
  which must be wrapped first, is a decision each function needs
  individually — the inventory in the audit report is the starting list to
  work through, not a verdict.

**Resolved, 2026-08-01: already landed, ahead of M6 starting.**
`domain.reader_context.ReaderContext` +
`services.reading_sessions.get_reader_context` is the server-side resolver
— it reads the active `ReadingSession`, never a caller-supplied ordinal,
and is wired through FastAPI's `Depends()`
(`api.dependencies.reader_context_dependency`) so the invariant is
enforced by `tests/test_reader_context_coverage.py`, not just a policy M6
code has to remember. `GET /books/{id}/memories`, `.../predictions`, and
`.../chapters` all go through it; `GET /books/{id}/structure` is the one
explicit, documented exemption (the pre-reading verification read, gated
separately). The "becomes agent tool definitions" sub-question is now
moot — M6 isn't introducing an agent (see `docs/milestones.md`, M6).

---

## 4. Instrumentation readiness

**Finding.** `LLMProvider.complete()` (`ai/providers/llm.py`) requires
`prompt_version_id` at the type level and its `Completion` return already
carries `model`, `input_tokens`, `output_tokens` — but every call site
(`capture_pipeline.py`, `consolidation.py`, `prediction_resolution.py`)
discards everything except `.text`. No `llm_calls` table exists. All four
current call sites resolve the provider through one factory,
`get_llm_provider()` (`ai/providers/__init__.py:49`) — a real choke point
for wrapping/instrumentation without touching call-site business logic.
But `job_id` isn't available at the call site to record — `JobHandler`
(`jobs/handlers.py:59`) never receives it, and `_run_one`
(`jobs/runner.py:96`) doesn't pass it down. Separately: `ProviderKind =
Literal["fake"]` (`config/settings.py:18`) means there is no real LLM
provider anywhere in this codebase today — every milestone through M5 has
run entirely on `FakeLLM`.

**Decision this forces.** Two separable decisions: (a) how to get `job_id`
to the instrumentation choke point, and (b) whether instrumentation ships
before or alongside M6, given M6 is also the milestone that (implicitly)
needs a first real LLM provider to be worth anything against production
data.

**Options for threading `job_id`:**

- **Add `job_id` as a parameter to `JobHandler.__call__`.** Touches all 6
  registered handler signatures (`jobs/handlers.py`) plus `_run_one`.
  Explicit, typed, no hidden state.
- **Set it in a contextvar inside `_run_one` before calling the handler,
  read it back inside the instrumentation wrapper.** No signature changes
  to existing handlers. Implicit/global state that has to be remembered to
  clear, and less obvious to a reader than a parameter.
- **Don't capture `job_id` at all for now** — ship `llm_calls` with
  `call_site`, `prompt_version_id`, `model`, tokens, and `latency` only,
  correlating to a job after the fact via timestamp proximity if ever
  needed. Cheapest, but "call site" per the original ask included job id
  specifically, and this drops it.

**Options for sequencing:**

- **Build the `llm_calls` table and instrumentation choke point before or
  alongside M6**, since M6 is also when a real (non-fake) provider
  presumably needs to get wired in — instrumenting from the first real
  call avoids a gap in cost history. Couples an M7-labeled deliverable
  ("Observability: per-request token accounting, cost view" —
  `docs/milestones.md`, M7) into M6's scope.
  ("Do not build later milestones early" is a standing project rule —
  worth weighing directly against the cost of retrofitting instrumentation
  onto whatever the first real-provider period generates with no
  cost record at all.)
- **Leave instrumentation for M7 as currently scoped**, and accept that
  M6's first real-provider usage (if M6 is also when a real provider gets
  wired in) runs uninstrumented until M7. Keeps milestone scope clean per
  `CLAUDE.md`'s "nothing outside the current milestone's DoD" rule; costs
  an uninstrumented window of unknown length and unknown spend.
- **Wire in a real provider without building `llm_calls` yet, purely to
  unblock M6, and treat token/cost tracking as strictly M7's job as
  planned.** Separates "M6 needs real completions to be useful" from "M7
  needs to account for what they cost" as two genuinely different
  concerns, at the cost of some real spend happening before any cost
  visibility exists.

**Resolved, 2026-08-01: already landed, ahead of M6 starting.** Both
sub-decisions went the "before/alongside M6" way: `job_id` threads through
a contextvar (`alam.jobs.context.current_job_id`, set in `_run_one`) rather
than a handler-signature change, and `InstrumentedLLMProvider` wraps
`get_llm_provider()`'s return value, recording every `.complete()` call to
`llm_calls` through its own independent session. Real paid providers
(Anthropic, Voyage, OpenAI) exist behind the same Protocols, gated by
`ALLOW_PAID_PROVIDERS` (defaults `false`, unset in production — the $0
constraint the user set explicitly partway through that work, superseding
"wire in paid providers" as the milestone's original framing). Local ($0)
providers (Ollama, sentence-transformers, faster-whisper) exist too, for
real inference numbers on a dev machine; both real paths are tested,
neither is reachable from the deployed URL.

---

## 5. Gaps

All three confirmed against the code, not inferred from docs:

- **No content-chunk / raw-book-text storage exists anywhere.** Addressed
  by ADR-0010 — declined for M6, with the concrete revisit trigger (in-text
  Q&A over a specific chapter) named there.
- **No memory deletion or edit path exists.** `MemoryRepository` has no
  `delete`/`update` method; no API route exposes one. Cascade-on-delete for
  prediction evidence is real (`ON DELETE CASCADE`) but is only exercised
  in tests via a direct `session.delete()` call, never by a product code
  path. **Not directly an M6 blocker** — nothing in M6's DoD requires
  deleting or editing a memory — but worth naming as a standing gap:
  a memory that turns out to be wrong (bad transcription, wrong
  extraction) has no correction path today, and M6 surfacing memories more
  visibly (in briefings, summaries) may be what finally makes that gap
  user-visible for the first time. Whether to build a deletion/edit path is
  its own decision, out of scope for this audit's five questions but
  flagged since M6 is plausibly what exposes it.

  **Resolved, 2026-08-01: defer, flag as a known gap.** Put to the user
  directly. Nothing in M6's DoD requires it; building it now would be
  scope the milestone didn't ask for. Stays a known, named gap — revisit
  if a briefing or summary surfacing a wrong memory turns out to be a real
  problem in practice, not a theoretical one.
- **`migrate.yml` runs on push independently of the Vercel deploy.**
  Addressed by ADR-0011 — every migration from here forward must assume
  the two pipelines can land in either order, with the expand/contract
  discipline and worked example recorded there.

---

## 6. Layer 3 spoiler containment (decided during M6 session 1 planning)

**Finding.** Not one of this audit's original five questions — ADR-0002
itself already named the reason: Layer 2 and Layer 3 had "Decided, not
implemented" status because neither had a caller yet, and this audit's own
implicit default (build the minimum M6 needs, leave Layer 3 for whenever a
synthesis response's cost/latency actually justifies it) was the cheaper
path. M6 session 1 (journey summaries) is the first code in the repository
that generates prose rather than retrieving or classifying existing
records, which makes it the first point either layer *could* run.

**Decision, put to the user directly at session 1 planning, 2026-08-01:
Layer 3 ships as part of M6 session 1, overriding the cheaper default.**
Rationale, verbatim-close: Layer 1's `leakage_rate=0.0` measures
*retrieval* — whether an already-excluded memory ever reaches the prompt.
It says nothing about *generation* — a model handed only permitted
memories can still leak a future event by inference in its own prose
(paraphrase, plausible-sounding synthesis, connecting dots the reader
hasn't reached yet). M6 is the first milestone where that failure mode can
even occur, so it is the first place closing it stops being speculative.

**Implemented as a structured classifier, not a second freeform
generation:** input is the draft plus the exact memory content the ordinal
filter excluded from it (nothing new to compute — retrieval already
excludes it, this just doesn't discard it before the check); output is
schema-constrained `{leaked: bool, spans: [...]}` via `response_schema`,
the same `EXTRACTION_RESPONSE_SCHEMA` mechanism M5.5a's follow-up work
established. Runs once per persisted artifact (at generation time), not
once per read of an already-`complete` cached row. Layer 2 (stating the
reader's position in the prompt) landed alongside it — it had no caller
either until this session's prompt did. Full design, the persisted-artifact
row lifecycle it's part of, and the rationale for classifier-not-generation
are in **ADR-0013**. `synthesis_leakage_rate`
(`alam/eval/journey_summary_eval.py`) is the corresponding Layer 4 case,
run in CI alongside the existing `leakage_rate` cases.
