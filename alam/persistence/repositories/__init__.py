"""Repositories.

Each takes a ``Session`` and never opens or commits one — transaction
boundaries belong to the caller in ``services/``, so a single unit of work can
span several repositories.
"""

from alam.persistence.repositories.captures import CaptureRepository
from alam.persistence.repositories.media_items import MediaItemRepository
from alam.persistence.repositories.memories import MemoryRepository
from alam.persistence.repositories.reading_sessions import ReadingSessionRepository
from alam.persistence.repositories.structure_units import StructureUnitRepository
from alam.persistence.repositories.users import UserRepository

__all__ = [
    "CaptureRepository",
    "MediaItemRepository",
    "MemoryRepository",
    "ReadingSessionRepository",
    "StructureUnitRepository",
    "UserRepository",
]
