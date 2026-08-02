"""MVP core models.

Importing every model here ensures they are all registered on
``SQLModel.metadata`` whenever ``app.models`` is imported — which is what
Alembic's autogenerate and the app both rely on.
"""

from app.models.attempt import Attempt
from app.models.audio_asset import AudioAsset
from app.models.audio_blob import AudioBlob
from app.models.audio_segment import AudioSegment
from app.models.auth_identity import AuthIdentity
from app.models.material import Material
from app.models.segment import Segment
from app.models.segment_attempt import SegmentAttempt
from app.models.user import User

__all__ = [
    "User",
    "AuthIdentity",
    "Material",
    "Segment",
    "Attempt",
    "SegmentAttempt",
    "AudioBlob",
    "AudioSegment",
    "AudioAsset",
]
