"""Public, unauthenticated read access to the demo persona's library.

No caller-supplied user id — `services.demo_persona.get_demo_library` resolves
the demo user the same way it always has, which is what makes CLAUDE.md rule 9
hold here: this endpoint cannot be pointed at the owner's real data even by
mistake, because it never accepts an id that could name it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from alam.persistence.session import session_scope
from alam.services.demo_persona import get_demo_library

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter(prefix="/demo", tags=["demo"])


class DemoBookResponse(BaseModel):
    id: str
    title: str
    author: str | None
    my_rating: int | None
    exclusive_shelf: str | None
    structure_verified: bool
    chapter_count: int


class DemoLibraryResponse(BaseModel):
    seeded: bool
    persona: str | None
    books: list[DemoBookResponse]


@router.get("/books", response_model=DemoLibraryResponse)
def list_demo_books(session: Session = Depends(session_scope)) -> DemoLibraryResponse:
    library = get_demo_library(session)
    return DemoLibraryResponse(
        seeded=library.seeded,
        persona=library.persona,
        books=[
            DemoBookResponse(
                id=str(b.id),
                title=b.title,
                author=b.author,
                my_rating=b.my_rating,
                exclusive_shelf=b.exclusive_shelf,
                structure_verified=b.structure_verified,
                chapter_count=b.chapter_count,
            )
            for b in library.books
        ],
    )
