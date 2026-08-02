# Milestones

Each milestone has a definition of done. Work outside the current milestone is
out of scope — see `CLAUDE.md`.

---

## M0 — Foundation *(complete)*

- Docker Compose: Postgres + pgvector, app container
- Alembic wired; first migration creates the `vector` extension, `users`,
  `media_items`, `media_structure_units`
- Typed settings via `pydantic-settings`; `.env.example` committed
- FastAPI skeleton, `GET /health`, structured logging with a trace id per request
- Job queue: `jobs` table, `enqueue()`, worker loop using
  `FOR UPDATE SKIP LOCKED`, retry with exponential backoff, one no-op handler
- **A test that runs two workers concurrently and asserts no double-claim**
- `pytest`, `ruff`, `mypy --strict` on `domain/`; CI green on push
- Provider Protocols for LLM, embeddings, and STT — **fake implementations only**,
  no real API calls
- **Deployed:** web service live on the real URL, health endpoint responding,
  queue drained by `pg_cron` on a bounded schedule rather than a standing
  worker process (ADR-0007 supersedes the always-on worker in ADR-0005)

Defining the provider Protocols with fakes in M0 is what makes every later
milestone testable offline, with no API spend and no flaky tests. It also forces
the interface decision while changing it is still free.

---

## M1 — Import and structure *(complete)*

- **Goodreads CSV upload:** deterministic dedupe key
  (ISBN13 → ISBN10 → normalized title+author), upsert semantics, diff preview
  before commit
- **EPUB ingestion:** container parsing proposes a chapter structure from
  spine order
- **Chapter extraction with structure preview and manual correction
  (ADR-0004):** merge/split/relabel/exclude, expressed as one operation —
  submit the desired final structure, diffed against what's persisted
- **Seeded demo persona generator** (doubles as cold-start bootstrap): a
  fixed, invented reading history on the `is_demo` user, reachable at
  `GET /demo/books` with no authentication

**Resolved open question:** checked a real Goodreads export — 0 of 16 books
had review text, ratings on 10/16, ISBNs on 10/16. Cold start and the
importer are built on ratings, shelves, and dates; review text is ingested
opportunistically when present but nothing depends on it.

---

## M2 — Capture and voice *(complete)*

- **Transcription:** the STT provider is biased with a per-book entity list —
  title, author, and chapter labels, the cheapest available signal, since
  nothing has been extracted from the text itself yet
- **Entity correction:** the same entity list drives a post-hoc LLM pass that
  fixes misheard proper nouns in the raw transcript
- **Structured extraction into typed memories:** fixed enum
  (`prediction`/`opinion`/`emotional_reaction`/`confusion`/
  `character_judgment`/`favorite_moment`/`meta_comment`/`other`), one capture
  fanning out to many memory rows from a single LLM call
- Capture → transcribe → correct → extract runs as three independently
  retryable jobs on the M0 queue, not one long request

**Deferred, by explicit decision:** the PWA recording UI and its IndexedDB
offline queue. CLAUDE.md's "do not build yet" list rules out frontend work
before M7, and M2's own DoD called for exactly that PWA — rather than pick a
side of that conflict silently, it was raised and resolved with the human:
M2 ships as a backend capability only (an audio-upload API plus the
transcribe/correct/extract pipeline), and the recording surface itself is
built when frontend work starts at M7.

**A gap this milestone surfaced and fixed:** `reading_sessions.current_ordinal`,
`captures.structure_ordinal`, and `memories.structure_ordinal` are all
denormalized from `media_structure_units.ordinal` (rule 1). Structure
re-verification (M1, ADR-0004) can renumber a unit any of those rows already
point at; `services/structure_plan.py` now resyncs all three after every
renumber. Excluding or merging away a unit that already has a session,
capture, or memory against it still fails loudly via the foreign key — no
`ondelete` cascade — rather than silently orphaning data. That remains a real
limitation, just a safe one.

---

## M3 — Memory and retrieval *(complete)*

- Embeddings with `embedding_model` / `embedding_version` recorded
- Hybrid retrieval: pgvector cosine + Postgres full-text, fused with reciprocal
  rank fusion. Pure vector search misses invented proper nouns.
- Spoiler filter (ADR-0002)
- **Evaluation harness:** golden retrieval set (recall@k), adversarial spoiler
  set (leakage rate), extraction accuracy against hand-labeled transcripts.
  Runs in CI.

M3 is the milestone that makes this a portfolio project rather than a personal
tool. Stopping after M3 with a working eval harness beats stopping after M6
without one.

---

## M4 — Profile *(complete)*

- Weekly consolidation job
- Confidence decay and reinforcement
- Supersede logic for contradictions
- Taste drift view

---

## M5 — Predictions *(complete)*

- Lifecycle: created → pending → confirmed / refuted / unresolvable
- Resolution triggered when progress crosses `made_at_ordinal + N`, scanning only
  memories in that window — so predictions resolve during the journey, not only
  at the end (ADR-0009: memories, not `content_chunks`, which still doesn't
  exist)
- Evidence memory linking
- `unresolvable` is a real outcome. Vague predictions exist; forcing every one
  into confirmed/refuted manufactures false precision.

---

## M6 — Synthesis *(complete)*

- Spoiler-safe pre-book briefings
- Reading journey summaries
- Recommendations with explanations
- ~~**Reconsider an agent here.**~~ **Resolved, 2026-08-01: no.** Explicitly
  decided against, not just deferred by default — asked directly at M6's
  start, given CLAUDE.md rule 4 marks "no autonomous agent in V1" as a
  settled decision this milestone was named as the place to revisit. M6
  stays the deterministic pipeline (input → processing → retrieval →
  synthesis → memory update), same shape as M0-M5. Revisit only if a
  concrete orchestration problem actually shows up while building M6, not
  speculatively.
- No `content_chunks` / raw book text — declined for M6, see
  [ADR-0010](adr/0010-no-content-chunk-storage.md). Knowledge sources are
  `media_items.attributes`, `memories` (via `retrieve_memories`),
  `preference_facts` (via `get_taste_drift`), `predictions` (via
  `list_predictions_for_book`) — all four already exist and are
  `ReaderContext`-scoped where relevant.

---

## M7 — Polish *(complete)*

- Frontend
- Observability: per-request token accounting, cost view
- README with architecture diagram, the ADRs, real eval numbers, and an honest
  limitations section

More people will read the README than will use the app.
