# Local-provider eval baseline (M5.5a follow-up)

**Date:** 2026-08-01
**LLM:** Ollama, `llama3.2:3b` (2GB) — the largest model this development
machine's 8GB of RAM can run at reasonable speed. Not a ceiling on the
pipeline; a hardware ceiling on this particular baseline.
**Embeddings:** sentence-transformers, `BAAI/bge-small-en-v1.5` (384-dim) —
unchanged from the prior run; not re-measured here since embedding
behavior doesn't depend on which LLM is configured alongside it.
**Prompt version measured:** `extract-memories-v2` (`alam/ai/prompts/extraction.py`).
**Schema:** `response_schema` passed on every call —
`EXTRACTION_RESPONSE_SCHEMA` (`alam/ai/extraction/memories.py`), generated
from `ExtractedMemory` via Pydantic's `TypeAdapter`, not hand-written.
**Runner:** `scripts/diagnose_extraction.py`, run twice (once for the
bucket classification and verbatim output, once more to capture
`llm_calls` token accounting before a `pytest` run wiped the shared test
database's rows) — both runs produced byte-identical bucket results.
**Supersedes:** [`2026-08-01-local-1b-first-run.md`](2026-08-01-local-1b-first-run.md),
the first run against `llama3.2:1b` before `response_schema`, the v2
prompt, and the metric split existed. Kept for history; not updated to
match this one.

No prompts were tuned in response to these results.

## Extraction: bucket breakdown

| Bucket | Count | Cases |
|---|---|---|
| 1 — no output/error | 0 | — |
| 2 — not parseable JSON | 0 | — |
| 3 — valid JSON, wrong schema | 0 | — |
| 4 — valid JSON, correct schema, wrong content | 4 | `emotional_reaction`, `confusion`, `meta_comment`, `two_distinct_memories_in_one_transcript` |
| 5 — correct | 4 | `single_opinion`, `single_prediction`, `character_judgment`, `favorite_moment` |

**`parse_success_rate = 1.0` (8/8). `type_accuracy = 0.5` (4/8). `accuracy = 0.5`.**
`type_accuracy` and `accuracy` coincide here because nothing failed to
parse — every response was well-formed against the schema, so this 0.5 is
a fully-assessable content-quality number, not one diluted by unassessable
cases the way the 1B run's `0.0` was.

## The 4 wrong-content cases, expected vs. actual

| Case | Expected | Actual | Failure mode |
|---|---|---|---|
| `emotional_reaction` | `{emotional_reaction}` | `{emotional_reaction, other}` | Wrong count — correct type kept, one spurious extra memory appended (empty-content `other`) |
| `confusion` | `{confusion}` | `{opinion}` | Wrong type — count matches, category misclassified |
| `meta_comment` | `{meta_comment}` | `{opinion, prediction}` | Wrong count *and* wrong type — split into two, neither matches, one is fabricated content not supported by the transcript |
| `two_distinct_memories_in_one_transcript` | `{confusion, favorite_moment}` | `{confusion, opinion}` | Wrong type — count matches, one of two memories miscategorized |

2 of 4 are pure category misclassification at the correct count; 2 of 4
extract the wrong *number* of memories (over-extraction in both cases —
splitting or inventing an extra memory, never merging or dropping one).

## Token totals and projected cost

From `llm_calls`, all 8 rows, `call_site=__main__.main`:

- **8 calls, 2,453 input tokens, 311 output tokens** (2,764 total)
- Per-call latency: 2.7s–13.1s — no runaway generation this time; the 1B
  run's repetition-loop failure mode (203s+ per stuck call) didn't recur.

**Projected cost if this exact run had gone to Haiku 4.5** ($1/M in, $5/M
out — verify against Anthropic's current pricing):
- Input: 2,453 × $1/1,000,000 = $0.0025
- Output: 311 × $5/1,000,000 = $0.0016
- **Total ≈ $0.004**

No tuning-for-cost caveat needed this time — every call terminated
normally, so this figure isn't inflated by wasted tokens the way the 1B
projection was.

**Voyage embedding cost: not measured by this run.** Extraction makes zero
embedding calls; only `retrieve_memories` (via `seed_case_memories`) does,
and neither was re-run in this session (see above — embedding behavior is
unchanged from the prior run). The archived 1B doc has a rough
order-of-magnitude estimate from that earlier retrieval/spoiler run
(~50 embed calls, unmeasured token count) if a Voyage figure is needed;
it wasn't refreshed here rather than restated as more precise than it is.

## Retrieval and spoiler: unchanged, not re-run

The prior run's `recall@5 = 1.000` and `leakage_rate = 0.000`
(`2026-08-01-local-1b-first-run.md`) depend on the embedding provider, not
the LLM, and the embedding provider (`bge-small-en-v1.5`) is identical
here. Re-running would exercise the same code path against the same model
and could only reproduce the same result — noted rather than repeated.

## What changed since the 1B run, and why it mattered

Buckets 1–3 (unparseable, wrong shape) went from 8/8 to 0/8. That's the
`response_schema` + prompt-v2 fix working as intended — schema-constrained
decoding fixes the wire *shape*; the prompt rewrite fixes which categories
a model chooses to fill in. Neither fix, by itself, would have caught the
other's failure mode: a stricter schema alone doesn't stop a model from
correctly-formatted overgeneration (see `emotional_reaction`'s spurious
`other` entry — schema-valid, still wrong), and a clearer prompt alone
doesn't stop a model from returning a bare object when nothing enforces
array shape.

What's left — 4/8 wrong content, all schema-valid — is the honest residual
capability gap for a 2GB model: occasional placeholder residue, and real
semantic miscategorization or mild hallucination on transcripts with a
less clear-cut single category. That gap is a property of `llama3.2:3b`,
not of the pipeline; no paid, frontier-scale model has been run against
this harness to compare against.

---

## Journey summary (Layer 3 leak-check) — first real run, 2026-08-02

**LLM:** Ollama, `llama3.2:3b` (unchanged from above; re-run alongside
extraction/retrieval/spoiler in the same `scripts/run_local_eval.py`
invocation).
**Prompt versions measured:** `journey-summary-v1` (narrative generation)
and `leak-check-v1` (Layer 3 verdict) — `alam/ai/prompts/`.
**What changed to make this possible:** `run_journey_summary_spoiler_eval`
(`alam/eval/journey_summary_eval.py`) previously always constructed its
own `FakeLLM` regardless of `ALAM_LLM_PROVIDER`; it now takes an optional
`llm` parameter, defaulting to the same fake for the CI/test-suite path
(`tests/persistence/test_eval_spoiler.py`, unaffected) but routing both
calls through a real provider when one is passed. This is the one eval
harness that reaches Layer 3 (`alam/ai/synthesis/leak_check.py`) rather
than exercising its own canned-clean plumbing — the gap
[ADR-0013](../adr/0013-synthesis-artifacts-and-layer3.md) and this
project's README both explicitly flagged as still-fake.

**A second, unrelated bug surfaced running this against a shared local
database:** `scripts/run_local_eval.py` runs all four evals against one
committed session, but `reader_context_dependency` resolves "the owner"
via `UserRepository.get_owner()` — the earliest-created non-demo user.
Under `pytest`, every test gets its own rolled-back transaction so this
is never ambiguous; here, the extraction/retrieval/spoiler sections above
each leave their own "Eval Owner" row behind, and the journey-summary
section's book belonged to a *different*, later-created owner — a 404,
not a leak, but a real test-isolation bug the script didn't have before
this section existed. Fixed by clearing non-demo `users` (cascading to
their books/sessions/memories via `ondelete="CASCADE"`) immediately
before the journey-summary section runs, once the earlier sections'
reports have already been printed.

**Case:** one book, a visible memory at ordinal 1 ("I loved the opening
chapters on Arrakis"), a spoiler-shaped memory at ordinal 9 (a
distinctive, book-ending reveal phrase), reader repositioned to ordinal
3 — the reveal sits well past the reader's current position and must
never appear in the generated narrative.

**Result: `synthesis_leakage_rate = 0.000` (0/2), both real for the first
time.** `layer3_verdict_clean` — the model's own leak-check verdict on
its own narrative — came back `{"leaked": false, "spans": []}`.
`distinctive_language_not_in_draft` — the defense-in-depth substring
check, real regardless of what Layer 3 says — also passed: the reveal
phrase does not appear in the persisted draft.

**The generated narrative, verbatim** (`journey_summaries.draft`):

> The reader has enjoyed the opening chapters of 'Eval Book', finding them
> engaging. They have yet to make any predictions about the book's
> content.

Two `llm_calls` rows: the narrative generation (208 input / 37 output
tokens, 5.7s) and the Layer 3 leak-check itself (235 input / 13 output
tokens, 3.4s) — both well inside the 25s `ALAM_DRAIN_BUDGET_SECONDS` and
120s `ALAM_JOB_LEASE_SECONDS` defaults, unlike the archived 1B run's
runaway-generation failures (this endpoint runs synchronously in-request,
not through the job queue, but the latency headroom is the same
comparison point).

**This is one clean case, not a clearance.** The spoiler content here is
a single, unambiguous, distinctively-worded reveal at a fixed ordinal
distance — not an adversarial set built to find where a 3B model's
judgment breaks. ADR-0002's ~200-case target applies to Layer 1's memory
retrieval set; Layer 3 has exactly one case, here run for the first time
against a real model instead of canned data. A model correctly declining
to volunteer information it wasn't asked about is a much lower bar than a
model correctly refusing to leak when a reader's own reflection nudges
toward a spoiler-adjacent topic. Read this result as "the plumbing now
produces a real, model-backed verdict, and this one case passes," not as
"Layer 3 is proven robust."
