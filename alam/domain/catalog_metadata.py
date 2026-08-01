"""Pure reads over a media item's cached ``attributes["catalog"]`` entry
(ADR-0015).

Extracted from ``services/recommendations.py`` (M6 session 3) once briefings
(M6 session 4) became a second real caller of the identical logic. Takes the
raw ``attributes`` dict, never a ``MediaItem`` ORM instance — CLAUDE.md rule
3: no ORM import here, plain data in and out.
"""

from __future__ import annotations

from typing import Any


def catalog_entry(attributes: dict[str, Any]) -> dict[str, Any] | None:
    entry = attributes.get("catalog")
    return entry if isinstance(entry, dict) else None


def has_catalog_content(attributes: dict[str, Any]) -> bool:
    """``attributes["catalog"]`` existing isn't enough — a definite
    "checked, found nothing" result (``blurb=None``, ``subjects=[]``) has
    nothing a citation or teaser could actually reference (M6 session 3,
    ADR-0015)."""
    entry = catalog_entry(attributes)
    if entry is None:
        return False
    return bool(entry.get("blurb")) or bool(entry.get("subjects"))
