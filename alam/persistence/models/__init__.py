"""SQLAlchemy models.

Importing this package registers every model on ``Base.metadata``, which is what
Alembic autogenerate reads. A model that is not imported here is invisible to
migrations.
"""

from alam.persistence.base import Base
from alam.persistence.models.capture import Capture, CaptureStatus
from alam.persistence.models.job import Job, JobStatus
from alam.persistence.models.journey_summary import JourneySummary, JourneySummaryStatus
from alam.persistence.models.llm_call import LLMCall
from alam.persistence.models.media_item import MediaItem, MediaType
from alam.persistence.models.media_structure_unit import (
    MediaStructureUnit,
    StructureUnitType,
)
from alam.persistence.models.memory import Memory, MemoryType
from alam.persistence.models.memory_embedding import MemoryEmbedding
from alam.persistence.models.prediction import Prediction, PredictionStatus
from alam.persistence.models.prediction_evidence import PredictionEvidence
from alam.persistence.models.preference_fact import PreferenceFact
from alam.persistence.models.preference_fact_evidence import PreferenceFactEvidence
from alam.persistence.models.reading_session import ReadingSession, ReadingSessionStatus
from alam.persistence.models.user import User

__all__ = [
    "Base",
    "Capture",
    "CaptureStatus",
    "Job",
    "JobStatus",
    "JourneySummary",
    "JourneySummaryStatus",
    "LLMCall",
    "MediaItem",
    "MediaStructureUnit",
    "MediaType",
    "Memory",
    "MemoryEmbedding",
    "MemoryType",
    "Prediction",
    "PredictionEvidence",
    "PredictionStatus",
    "PreferenceFact",
    "PreferenceFactEvidence",
    "ReadingSession",
    "ReadingSessionStatus",
    "StructureUnitType",
    "User",
]
