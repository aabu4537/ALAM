from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from alam.persistence.models.user import User

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, display_name: str, is_demo: bool = False) -> User:
        user = User(display_name=display_name, is_demo=is_demo)
        self._session.add(user)
        self._session.flush()
        return user

    def get(self, user_id: uuid.UUID) -> User | None:
        return self._session.get(User, user_id)

    def list_all(self) -> Sequence[User]:
        return self._session.scalars(select(User).order_by(User.created_at)).all()

    def get_demo_user(self) -> User | None:
        """The single demo persona, if it has been seeded.

        Demo mode resolves its user through this method rather than accepting a
        user id from the caller — the boundary in CLAUDE.md rule 9 is only worth
        anything if public traffic cannot name which user it wants.
        """
        return self._session.scalars(
            select(User).where(User.is_demo.is_(True)).order_by(User.created_at).limit(1)
        ).first()

    def delete(self, user: User) -> None:
        self._session.delete(user)
