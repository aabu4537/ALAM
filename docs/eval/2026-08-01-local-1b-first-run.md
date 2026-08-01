# Local-provider eval baseline (M5.5a task 3)

**Date:** 2026-08-01
**LLM:** Ollama, `llama3.2:1b` (1.3GB, pulled fresh for this run)
**Embeddings:** sentence-transformers, `BAAI/bge-small-en-v1.5` (384-dim — verify against the model card if this changes; not printed by this run)
**Prompt version measured:** `extract-memories-v1` (`alam/ai/prompts/extraction.py`) — the only prompt the eval harness covers. `consolidate-preferences-v1` and `resolve-prediction-v1` have no eval cases at all (a pre-existing gap, not introduced by this milestone) — this baseline says nothing about their quality against a real model.
**Runner:** `scripts/run_local_eval.py`, run once, prompts untouched, first-run numbers as instructed.

No prompts were tuned in response to these results. Numbers below are what the harness produced on the first and only run.

## Headline numbers

| Eval | Metric | Result | Elapsed |
|---|---|---|---|
| Extraction | accuracy | **0.000** (0/8) | 606.8s |
| Retrieval | recall@5 | **1.000** | 17.0s |
| Spoiler | leakage rate | **0.000** | 41.3s |

Retrieval and spoiler match the numbers the fake provider already produces (`docs/eval/`'s own docstrings note both are expected to read exactly 1.0 / 0.0) — those two evals test embedding geometry and deterministic fusion/filtering, not model judgment, and a real 384-dim embedding model reproduced the fake's perfect score on this small, hand-crafted case set. **Extraction is the only number that measures something the fake provider structurally cannot** (`FakeLLM` has no extraction capability at all), and it is 0%.

## Token totals and projected cost

From `llm_calls` (all 8 rows, `call_site=alam.eval.extraction_eval.run_extraction_eval`):

- **8 calls, 1,727 input tokens, 12,915 output tokens** (14,642 total)
- Per-call latency ranged from 4.7s to 203.7s — see Divergence, item 2

**Projected cost if this exact run had gone to Haiku 4.5** ($1/M in, $5/M out — verify against Anthropic's current pricing):
- Input: 1,727 × $1/1,000,000 = $0.0017
- Output: 12,915 × $5/1,000,000 = $0.0646
- **Total ≈ $0.066**

This figure is a ceiling, not a realistic estimate — see Divergence item 2. Three of the eight calls ran to the 4,096-token cap without terminating; a competent model produces a short JSON array and stops. Using the five calls that *did* terminate as a proxy for reasonable output length (avg ≈ 157 output tokens/call) and projecting that rate across all eight: ≈1,256 output tokens instead of 12,915, dropping the projected cost to **≈$0.008**.

**Voyage embedding cost:** not projectable from recorded data. `llm_calls` only instruments the LLM choke point (`get_llm_provider()`), per this milestone's task 2 scope — there is no `embedding_calls` table and no token count was recorded for any of the ~50 embed calls this run made (13 memories + 8 queries in retrieval, 19 memories + 10 queries in spoiler). Rough order-of-magnitude: ~50 short phrases (roughly 3,000 characters total, ~750 tokens at a 4-chars/token heuristic) — at Voyage's list pricing (unverified against their current rates from this environment), this is cents, not dollars, but "unmeasured" is the honest answer, not a specific number. **Recommendation, not implemented here:** if embedding cost tracking matters going forward, `llm_calls`' pattern (choke-point wrapper, own table) extends directly to `get_embedding_provider()`.

## Divergence — where the local model behaved differently from the fake

### 1. JSON shape mismatch — object instead of array (4 of 8 cases)

`response_format={"type": "json_object"}` (the JSON-mode contract `OllamaLLM` requests per task 2) guarantees valid JSON. It does **not** guarantee the top-level shape the extraction prompt asks for (`build_extraction_prompt`: "Return ONLY a JSON array of objects") or that `parse_extraction_response` requires (`raise ExtractionError` if `not isinstance(raw, list)`). `llama3.2:1b` consistently returned a single JSON *object* — e.g. for `single_opinion`: `{"memory_type": "opinion", "content": "..."}` instead of `[{"memory_type": "opinion", "content": "..."}]`. Every one of these calls terminated cleanly (105–229 output tokens, 4.7–10s) and was fully well-formed JSON — the failure is entirely a shape mismatch the parser correctly rejects, not a model incoherence problem. `FakeLLM` cannot exhibit this failure mode at all (it returns a fixed non-JSON string when unqueued); this is a real gap only a real provider surfaces.

### 2. Runaway generation hitting the token ceiling (3 of 8 cases)

`single_prediction`, `character_judgment`, and `meta_comment` did not produce a short JSON array and stop — they generated continuously until `_DEFAULT_MAX_TOKENS` (4,096, `alam/ai/providers/local/ollama_llm.py`) cut them off mid-string, each producing `Unterminated string starting at: line 8...` or similar. Latencies: 203.7s, 177.8s, 178.1s — **20–40× longer** than the calls that terminated cleanly (4.7–10s).

This is not just a quality problem — it is an operational one for this project specifically. `alam/config/settings.py`'s `drain_budget_seconds` defaults to 25.0s and `job_lease_seconds` to 120.0s, both sized around the assumption that a job (including its LLM call) finishes well inside a bounded window (ADR-0007). Two of these three calls (177.8s, 178.1s) **exceed the default lease** outright — if `ollama` were ever wired into the real capture pipeline running under the job queue rather than this standalone eval script, a case like this would have its lease reclaimed by a second worker while the first is still actively generating, which is exactly the double-processing race `Settings._lease_must_outlive_the_drain`'s docstring warns about, just triggered by model latency variance the queue's timing assumptions never anticipated. `FakeLLM` cannot exhibit this either — it returns instantly and deterministically.

### 3. Silent token-accounting gap (1 of 8 cases)

The `confusion` case failed with `Expecting ',' delimiter: line 79 column 1 (char 1663)` — real, substantial (1,663-character) malformed content was generated — but the recorded `llm_calls` row shows `input_tokens=0, output_tokens=0`. `OllamaLLM.complete()` (`alam/ai/providers/local/ollama_llm.py`) falls back to `0` when `response.usage` is `None`, and for this call Ollama's OpenAI-compat layer apparently didn't populate `usage` at all, despite returning real content. This means the "I still want the token accounting" goal (task 2's stated reason for keeping local calls instrumented) silently under-reports for at least some Ollama responses — the row exists and looks complete, but the numbers in it are wrong, not missing in an obvious way. Worth flagging distinctly from "no accounting" (which would be visibly absent) — this is *wrong* accounting that reads as valid.

### 4. Retrieval and spoiler mechanics: no divergence found

Both evals matched the fake provider's expected numbers exactly (recall@5=1.0, leakage=0.0) on this case set. The real embedding model's geometry was good enough for RRF fusion and the ordinal spoiler filter to behave identically to the deterministic fake on these ten-ish hand-authored cases. This is a weak signal, not a strong one — the case set is small and not adversarial toward embedding quality specifically (ADR-0002 target is ~200 spoiler cases; this repo has 10) — but it's the honest result of the one comparison this harness can make.

## This is a floor, not a ceiling

`llama3.2:1b` is a 1.3GB, 1-billion-parameter model chosen specifically to run entirely on a personal machine's CPU at $0 cost. Its 0% extraction accuracy here reflects that specific model's limitations — inconsistent structured-output shape, unreliable stopping behavior — not a ceiling on what ALAM's extraction pipeline or prompt template can do. A frontier model (the `anthropic` path built in task 3 of this milestone, gated behind `ALAM_ALLOW_PAID_PROVIDERS`) would very likely score meaningfully higher on both correctness and latency; this baseline should not be read as "ALAM's extraction doesn't work," only as "this specific $0 model, on this specific run, produced these specific failures." Whether the prompt itself needs hardening against shape ambiguity (e.g. explicitly naming `{"type": "json_object"}`-safe wrapper shapes) is a real, separate question this baseline surfaces but does not answer — see Divergence item 1's recommendation implication, not implemented here per instruction.

## Dev-environment only

`ollama` / `local` / `faster_whisper` are local-machine configurations. The Vercel deployment stays on `fake` providers — `faster-whisper`'s CTranslate2 weights and `sentence-transformers`' torch dependency both exceed Vercel's serverless function bundle size limits (even at the 5GB Fluid Compute ceiling, shipping model weights alongside the function is a different problem than what this milestone solved), and there is no way to run a background Ollama server inside a serverless deployment at all. Local providers are a way to get real (if weak) inference numbers on a development machine at $0 — not a deployment target.
