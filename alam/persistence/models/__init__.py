"""SQLAlchemy models.

Importing this package registers every model on ``Base.metadata``, which is what
Alembic autogenerate reads. A model that is not imported here is invisible to
migrations.
"""

from alam.persistence.base import Base
from alam.persistence.models.media_item import MediaItem, MediaType
from alam.persistence.models.media_structure_unit import (
    MediaStructureUnit,
    StructureUnitType,
)
from alam.persistence.models.user import User

__all__ = [
    "Base",
    "MediaItem",
    "MediaStructureUnit",
    "MediaType",
    "StructureUnitType",
    "User",
]
