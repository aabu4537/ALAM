"""Briefing draft shape (M6 session 4).

Parses and validates an LLM's schema-constrained response. Pure — no I/O, no
ORM — same reasoning ``ai/synthesis/recommendations.py`` gives.

Narrower than ``RecommendationDraft``: ``type`` is
``Literal["preference_fact", "memory"]``, not the three-way
``..., "catalog"]`` recommendations uses. A briefing's teaser (the
candidate's own cached blurb/subjects) is always ALAM-composed, never
LLM-cited — so ``"catalog"`` is never a valid option in the schema shown to
the model in the first place, not merely rejected after the fact. Same
"no field for unsourced content to occupy" discipline ADR-0014 established,
applied here to the *set of citable types* rather than to a free-text field.
``domain/recommendation_groundedness.py`` is reused unchanged: it is already
citation-type-generic, and a stray ``"catalog"`` citation — impossible from
this schema, but checked anyway as defense in depth — fails closed against
the always-empty default ``valid_catalog_media_item_ids`` rather than being
silently accepted.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, TypeAdapter, ValidationError


class BriefingCitationRef(BaseModel):
    model_config = {"frozen": True}

    type: Literal["preference_fact", "memory"]
    id: str


class BriefingDraft(BaseModel):
    model_config = {"frozen": True}

    cites: list[BriefingCitationRef]
    """Which of the reader's own facts/memories — about *other* books —
    plausibly connect to this candidate. May be empty: a candidate with
    nothing to personalize is still shown, teaser-only."""


BRIEFING_RESPONSE_SCHEMA: dict[str, Any] = TypeAdapter(BriefingDraft).json_schema()
"""Generated from ``BriefingDraft`` itself, not hand-written — same pattern
as ``ai/synthesis/recommendations.py``'s ``RECOMMENDATION_RESPONSE_SCHEMA``."""


class BriefingParseError(ValueError):
    """The LLM's response isn't valid JSON, or doesn't match the expected
    shape. Generation fails visibly (``status=failed``) rather than
    persisting a briefing nobody validated."""


def parse_briefing_response(text: str) -> BriefingDraft:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BriefingParseError(f"response is not valid JSON: {exc}") from exc

    try:
        return BriefingDraft.model_validate(raw)
    except ValidationError as exc:
        raise BriefingParseError(f"response did not match the expected schema: {exc}") from exc
