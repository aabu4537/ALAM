"""Seeds the public demo persona: a fixed, invented reading history so the
demo surface (`GET /demo/books`) has something real to show without touching
the owner's data (CLAUDE.md rule 9) or costing anything to generate.

This is the reading-history backbone — books, ratings, shelves, dates, one
fully verified chapter structure (M1), and one seeded voice reflection
carried all the way through to extracted memories (M2) — each demonstrating
its milestone's pipeline end-to-end without a frontend, real audio, or a
network call. Profile facts don't exist yet (M4) and are not part of what
this seeds.

Idempotent: safe to call more than once. Matches existing demo books by title
rather than re-creating them, and never touches a book it didn't create.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

from alam.ai.extraction.memories import ExtractedMemory, MemoryType
from alam.domain.reading_progress import compute_progress
from alam.persistence.models.media_item import MediaType
from alam.persistence.repositories.captures import CaptureRepository
from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.memories import MemoryRepository
from alam.persistence.repositories.reading_sessions import ReadingSessionRepository
from alam.persistence.repositories.structure_units import StructureUnitRepository
from alam.persistence.repositories.users import UserRepository

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session

    from alam.persistence.models import MediaStructureUnit, User

DEMO_DISPLAY_NAME = "Demo Reader"
DEMO_PROMPT_VERSION_ID = "demo-seed"
"""Not a real prompt version (rule 6 is about LLM outputs; this data was
never produced by one) — a recognizable sentinel so a seeded memory is never
mistaken for a genuine extraction in a downstream accuracy count."""


@dataclass(frozen=True, slots=True)
class DemoReflectionSeed:
    chapter_index: int
    """0-based index into the book's ``chapters`` tuple."""
    raw_transcript: str
    corrected_transcript: str
    memories: tuple[ExtractedMemory, ...]


@dataclass(frozen=True, slots=True)
class DemoBookSeed:
    title: str
    author: str
    my_rating: int | None
    exclusive_shelf: str
    date_added: str
    date_read: str | None
    chapters: tuple[str, ...] = ()
    """Non-empty only for the books meant to demonstrate a fully verified
    structure — most demo books don't need it, mirroring how most real books
    in a library sit unverified until the reader actually opens one."""
    reflection: DemoReflectionSeed | None = None
    """Demonstrates the M2 capture -> transcribe -> correct -> extract
    pipeline for one book, the same way ``chapters`` demonstrates ADR-0004's
    structure verification. Requires ``chapters`` to be non-empty."""


DEMO_LIBRARY: tuple[DemoBookSeed, ...] = (
    DemoBookSeed(
        title="Dune",
        author="Frank Herbert",
        my_rating=5,
        exclusive_shelf="read",
        date_added="2025-08-03",
        date_read="2025-08-20",
        chapters=("Part One: Dune", "Part Two: Muad'Dib", "Part Three: The Prophet"),
        reflection=DemoReflectionSeed(
            chapter_index=0,
            raw_transcript=(
                "I think the mud dib guy is hiding something big from his mom, "
                "and honestly the pacing here is so slow."
            ),
            corrected_transcript=(
                "I think Muad'Dib is hiding something big from his mom, "
                "and honestly the pacing here is so slow."
            ),
            memories=(
                ExtractedMemory(
                    memory_type=MemoryType.PREDICTION,
                    content="Paul is concealing something significant from Jessica.",
                ),
                ExtractedMemory(
                    memory_type=MemoryType.OPINION,
                    content="The pacing in Part One feels slow.",
                ),
            ),
        ),
    ),
    DemoBookSeed(
        title="The Left Hand of Darkness",
        author="Ursula K. Le Guin",
        my_rating=5,
        exclusive_shelf="read",
        date_added="2025-09-10",
        date_read="2025-09-28",
        chapters=("Chapter 1", "Chapter 2", "Chapter 3", "Chapter 4"),
    ),
    DemoBookSeed(
        title="Piranesi",
        author="Susanna Clarke",
        my_rating=4,
        exclusive_shelf="read",
        date_added="2025-10-05",
        date_read="2025-10-12",
    ),
    DemoBookSeed(
        title="Klara and the Sun",
        author="Kazuo Ishiguro",
        my_rating=4,
        exclusive_shelf="read",
        date_added="2025-11-01",
        date_read="2025-11-18",
    ),
    DemoBookSeed(
        title="Project Hail Mary",
        author="Andy Weir",
        my_rating=5,
        exclusive_shelf="read",
        date_added="2025-12-02",
        date_read="2025-12-22",
    ),
    DemoBookSeed(
        title="A Memory Called Empire",
        author="Arkady Martine",
        my_rating=3,
        exclusive_shelf="read",
        date_added="2026-01-15",
        date_read="2026-02-01",
    ),
    DemoBookSeed(
        title="Circe",
        author="Madeline Miller",
        my_rating=4,
        exclusive_shelf="read",
        date_added="2026-03-01",
        date_read="2026-03-19",
    ),
    DemoBookSeed(
        title="Tomorrow, and Tomorrow, and Tomorrow",
        author="Gabrielle Zevin",
        my_rating=5,
        exclusive_shelf="read",
        date_added="2026-04-04",
        date_read="2026-04-25",
    ),
    DemoBookSeed(
        title="The Fifth Season",
        author="N.K. Jemisin",
        my_rating=None,
        exclusive_shelf="currently-reading",
        date_added="2026-07-10",
        date_read=None,
    ),
    DemoBookSeed(
        title="The Song of Achilles",
        author="Madeline Miller",
        my_rating=None,
        exclusive_shelf="to-read",
        date_added="2026-07-28",
        date_read=None,
    ),
)


@dataclass(frozen=True, slots=True)
class DemoSeedResult:
    user: User
    created_book_titles: tuple[str, ...]
    skipped_book_titles: tuple[str, ...]


def _seed_reflection(
    session: Session,
    *,
    item_id: uuid.UUID,
    units: list[MediaStructureUnit],
    reflection: DemoReflectionSeed,
) -> None:
    """Builds a capture already at ``EXTRACTED`` directly, rather than
    enqueueing jobs for the fake providers to run — seeding must be
    deterministic and free of any queue-drain timing, and the point is to
    demonstrate the pipeline's *output*, not re-run it."""
    unit = units[reflection.chapter_index]
    progress = compute_progress(unit.ordinal, len(units))

    reading_session = ReadingSessionRepository(session).get_or_create_active(
        item_id, structure_unit_id=unit.id, ordinal=unit.ordinal, progress=progress
    )
    capture = CaptureRepository(session).create(
        reading_session_id=reading_session.id,
        media_item_id=item_id,
        structure_unit_id=unit.id,
        structure_ordinal=unit.ordinal,
        audio_data=b"",
    )
    CaptureRepository(session).mark_transcribed(
        capture, raw_transcript=reflection.raw_transcript, transcript_model=DEMO_PROMPT_VERSION_ID
    )
    CaptureRepository(session).mark_corrected(
        capture, corrected_transcript=reflection.corrected_transcript
    )
    MemoryRepository(session).create_many(
        capture_id=capture.id,
        media_item_id=item_id,
        structure_unit_id=unit.id,
        structure_ordinal=unit.ordinal,
        prompt_version_id=DEMO_PROMPT_VERSION_ID,
        extracted=list(reflection.memories),
    )
    CaptureRepository(session).mark_extracted(capture)


def seed_demo_persona(session: Session) -> DemoSeedResult:
    user = UserRepository(session).get_or_create_demo(DEMO_DISPLAY_NAME)

    items = MediaItemRepository(session)
    existing_titles = {b.title for b in items.list_for_user(user.id)}

    created: list[str] = []
    skipped: list[str] = []

    for seed in DEMO_LIBRARY:
        if seed.title in existing_titles:
            skipped.append(seed.title)
            continue

        item = items.create(
            user_id=user.id,
            title=seed.title,
            media_type=MediaType.BOOK,
            attributes={
                "author": seed.author,
                "my_rating": seed.my_rating,
                "exclusive_shelf": seed.exclusive_shelf,
                "date_added": seed.date_added,
                "date_read": seed.date_read,
            },
        )

        book_units = []
        if seed.chapters:
            units = StructureUnitRepository(session)
            book_units = [
                units.create(media_item_id=item.id, ordinal=ordinal, label=label)
                for ordinal, label in enumerate(seed.chapters, start=1)
            ]
            items.mark_structure_verified(item, at=dt.datetime.now(dt.UTC))

        if seed.reflection:
            _seed_reflection(session, item_id=item.id, units=book_units, reflection=seed.reflection)

        created.append(seed.title)

    return DemoSeedResult(
        user=user, created_book_titles=tuple(created), skipped_book_titles=tuple(skipped)
    )


@dataclass(frozen=True, slots=True)
class DemoBook:
    id: uuid.UUID
    title: str
    author: str | None
    my_rating: int | None
    exclusive_shelf: str | None
    structure_verified: bool
    chapter_count: int


@dataclass(frozen=True, slots=True)
class DemoLibrary:
    seeded: bool
    persona: str | None
    books: tuple[DemoBook, ...]


def get_demo_library(session: Session) -> DemoLibrary:
    """Read-only view of the demo persona's library. Resolves the demo user
    the same way seeding does — never accepts a caller-supplied id, which is
    what keeps this endpoint incapable of reaching the owner's real data
    (CLAUDE.md rule 9)."""
    demo_user = UserRepository(session).get_demo_user()
    if demo_user is None:
        return DemoLibrary(seeded=False, persona=None, books=())

    items = MediaItemRepository(session)
    units = StructureUnitRepository(session)

    books = tuple(
        DemoBook(
            id=item.id,
            title=item.title,
            author=item.attributes.get("author"),
            my_rating=item.attributes.get("my_rating"),
            exclusive_shelf=item.attributes.get("exclusive_shelf"),
            structure_verified=item.structure_is_verified,
            chapter_count=len(units.list_for_media_item(item.id)),
        )
        for item in items.list_for_user(demo_user.id)
    )

    return DemoLibrary(seeded=True, persona=demo_user.display_name, books=books)
