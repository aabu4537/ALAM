# Milestones

Each milestone has a definition of done. Work outside the current milestone is
out of scope — see `CLAUDE.md`.

---

## M0 — Foundation *(current)*

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

## M2 — Capture and voice

- PWA recording with IndexedDB offline queue, syncing on reconnect
- Transcription
- Entity correction: per-book entity list passed as a biasing prompt, plus a
  post-hoc correction pass
- Structured extraction into typed memories (fixed enum, one capture → many
  memories)

---

## M3 — Memory and retrieval

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

## M4 — Profile

- Nightly consolidation job
- Confidence decay and reinforcement
- Supersede logic for contradictions
- Taste drift view

---

## M5 — Predictions

- Lifecycle: created → pending → resolved / unresolved
- Resolution triggered when progress crosses `made_at_ordinal + N`, scanning only
  chunks in that window — so predictions resolve during the journey, not only at
  the end
- Evidence chunk linking
- `unresolvable` is a real outcome. Vague predictions exist; forcing every one
  into confirmed/refuted manufactures false precision.

---

## M6 — Synthesis

- Spoiler-safe pre-book briefings
- Reading journey summaries
- Recommendations with explanations
- **Reconsider an agent here.** By M6 there are multiple knowledge sources —
  memories, book text, profile, external metadata, prior recommendations — and
  deciding what to retrieve becomes a real orchestration problem. An agent
  introduced because the data demanded it is a better decision than one present
  from the start.

---

## M7 — Polish

- Frontend
- Observability: per-request token accounting, cost view
- README with architecture diagram, the ADRs, real eval numbers, and an honest
  limitations section

More people will read the README than will use the app.
