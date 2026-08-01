"""Layer 3: structured spoiler-leak classifier (M6, ADR-0002, ADR-0013).

Not a second freeform generation — a schema-constrained classification call
over a draft plus the content the ordinal filter excluded from it. Shared by
every M6 synthesis artifact type; built here (journey summaries, session 1)
since it has no prior caller, reused unchanged by every later session.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError


class LeakCheckResult(BaseModel):
    model_config = {"frozen": True}

    leaked: bool
    spans: list[str]
    """Verbatim substrings of the draft that leak excluded content. Empty
    when ``leaked`` is ``False``."""


LEAK_CHECK_RESPONSE_SCHEMA: dict[str, Any] = TypeAdapter(LeakCheckResult).json_schema()
"""Generated from ``LeakCheckResult`` itself — same reasoning as
``ai/extraction/memories.py``'s ``EXTRACTION_RESPONSE_SCHEMA``."""


class LeakCheckParseError(ValueError):
    """The classifier's response isn't valid JSON, or doesn't match the
    expected shape. Treated as a failed generation (``status=failed``), not
    as ``leaked=False`` — a check that didn't run is not the same as a check
    that passed, and defaulting to "safe" here would silently disable Layer
    3 on any parse failure."""


def parse_leak_check_response(text: str) -> LeakCheckResult:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LeakCheckParseError(f"response is not valid JSON: {exc}") from exc

    try:
        return LeakCheckResult.model_validate(raw)
    except ValidationError as exc:
        raise LeakCheckParseError(f"response did not match the expected schema: {exc}") from exc
