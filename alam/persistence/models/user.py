"""The ``users`` table.

There is no authentication in V1 — this is a single-user system. The table
exists because ``user_id`` is the separation boundary between the owner's real
reading notes and the public demo persona (CLAUDE.md rule 9, ADR-0005). Voice
reflections about books get personal in ways that are easy to underestimate, so
that boundary is structural rather than a convention.
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, false
from sqlalchemy.orm import Mapped, mapped_column

from alam.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    display_name: Mapped[str] = mapped_column(String(200), nullable=False)

    is_demo: Mapped[bool] = mapped_column(
        Boolean, server_default=false(), nullable=False, index=True
    )
    """True for the synthetic persona backing public demo mode.

    Demo traffic must never reach a row belonging to a non-demo user. Indexed
    because every demo-mode query filters on it.
    """

    def __repr__(self) -> str:
        return f"<User id={self.id} display_name={self.display_name!r} is_demo={self.is_demo}>"
