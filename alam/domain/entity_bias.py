"""Per-book entity list for STT biasing and transcript correction (M2).

Nothing has been extracted from the text yet — no character list, no named
entities — so this is deliberately the cheapest available signal: the book's
title, its author, and its chapter labels. Real proper nouns a novel invents
("Muad'Dib") often show up verbatim in chapter titles, which is exactly the
case a general STT model mangles without a hint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def book_entity_list(*, title: str, author: str | None, chapter_labels: Sequence[str]) -> list[str]:
    """De-duplicated, order-preserving: title, then author, then chapter
    labels in ordinal order. Order matters for a biasing prompt built by
    joining this list — the most useful terms come first in case a provider
    truncates."""
    seen: set[str] = set()
    entities: list[str] = []
    for value in (title, author, *chapter_labels):
        if not value or value in seen:
            continue
        seen.add(value)
        entities.append(value)
    return entities
