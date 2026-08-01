"""Diagnose extraction accuracy with schema-constrained decoding + the v2
prompt in place (follow-up to tasks A-C). Re-runs the same 8 cases against
llama3.2:3b, using the exact production call shape (response_schema
included, same as capture_pipeline.py and run_extraction_eval), and
classifies each into one of five buckets:

  1. No output / API or runtime error
  2. Output returned but not parseable as JSON
  3. Valid JSON, wrong schema (not a list, or items missing/mistyped fields)
  4. Valid JSON, correct schema, wrong content (memory_type multiset differs)
  5. Correct

llm_calls only records accounting fields, not response text, so this
captures verbatim output itself rather than relying on what's queryable
after the fact.

Not part of the test suite (rule 8) — same reasoning as run_local_eval.py.
"""

from __future__ import annotations

import datetime as dt
import json
import os

os.environ.setdefault("ALAM_LLM_PROVIDER", "ollama")
os.environ.setdefault("ALAM_OLLAMA_MODEL", "llama3.2:3b")
os.environ.setdefault(
    "ALAM_DATABASE_URL",
    os.environ.get(
        "ALAM_TEST_DATABASE_URL", "postgresql+psycopg://alam:alam@localhost:5432/alam_test"
    ),
)

from pydantic import ValidationError
from sqlalchemy import select

from alam.ai.extraction.memories import EXTRACTION_RESPONSE_SCHEMA, ExtractedMemory
from alam.ai.prompts.extraction import PROMPT_VERSION_ID, build_extraction_prompt
from alam.ai.providers import get_llm_provider
from alam.config.settings import get_settings
from alam.eval.extraction_eval import EXTRACTION_CASES
from alam.persistence import session as session_module
from alam.persistence.models.llm_call import LLMCall


def _expected_types(case: object) -> tuple[str, ...]:
    return tuple(sorted(m.memory_type.value for m in case.expected))  # type: ignore[attr-defined]


def main() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    print(f"model={settings.ollama_model}\n")

    started_at = dt.datetime.now(dt.UTC)
    llm = get_llm_provider()
    buckets: dict[int, list[str]] = {1: [], 2: [], 3: [], 4: [], 5: []}

    for case in EXTRACTION_CASES:
        prompt = build_extraction_prompt(case.transcript)
        print(f"=== {case.label} ===")

        try:
            completion = llm.complete(
                prompt,
                prompt_version_id=PROMPT_VERSION_ID,
                response_schema=EXTRACTION_RESPONSE_SCHEMA,
            )
        except Exception as exc:
            print(f"BUCKET 1 (no output / error): {type(exc).__name__}: {exc}")
            buckets[1].append(case.label)
            print()
            continue

        text = completion.text
        print(f"raw output ({len(text)} chars):\n{text}\n")

        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            print(f"BUCKET 2 (not parseable JSON): {exc}")
            buckets[2].append(case.label)
            print()
            continue

        if not isinstance(raw, list):
            kind = type(raw).__name__
            print(f"BUCKET 3 (valid JSON, wrong schema): top-level is {kind}, not a list")
            buckets[3].append(case.label)
            print()
            continue

        try:
            parsed = [ExtractedMemory.model_validate(item) for item in raw]
        except ValidationError as exc:
            print(f"BUCKET 3 (valid JSON, wrong schema): {exc}")
            buckets[3].append(case.label)
            print()
            continue

        actual = tuple(sorted(m.memory_type.value for m in parsed))
        expected = _expected_types(case)
        if actual == expected:
            print(f"BUCKET 5 (correct): {actual}")
            buckets[5].append(case.label)
        else:
            print("BUCKET 4 (valid JSON, correct schema, wrong content):")
            print(f"  expected={expected} actual={actual}")
            buckets[4].append(case.label)
        print()

    print("=== bucket summary ===")
    for n in range(1, 6):
        print(f"bucket {n}: {len(buckets[n])} — {buckets[n]}")

    print()
    print("=== llm_calls recorded this run ===")
    with session_module.get_session_factory()() as session:
        calls = session.scalars(
            select(LLMCall).where(LLMCall.created_at >= started_at).order_by(LLMCall.created_at)
        ).all()
        total_input = sum(c.input_tokens for c in calls)
        total_output = sum(c.output_tokens for c in calls)
        print(f"{len(calls)} calls, {total_input} input tokens, {total_output} output tokens")
        for c in calls:
            print(
                f"  {c.call_site} model={c.model} prompt_version={c.prompt_version_id} "
                f"in={c.input_tokens} out={c.output_tokens} latency_ms={c.latency_ms:.0f}"
            )


if __name__ == "__main__":
    main()
