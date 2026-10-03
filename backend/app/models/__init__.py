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
from app.models.collection import Collection, CollectionItem
from app.models.image_blob import ImageBlob
from app.models.lexicon import Lexeme, LexemeSense, TranslationReport
from app.models.material import Material
from app.models.material_difficulty import MaterialDifficulty
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import QuestionGroup
from app.models.segment import Segment
from app.models.segment_attempt import SegmentAttempt
from app.models.user import User
from app.models.vocabulary import (
    Deck,
    DeckWord,
    LookupEvent,
    MaterialVocabulary,
    SavedWord,
    SavedWordContext,
    VocabularyReviewLog,
    VocabularySettings,
)
from app.models.word_list import UserWordList, WordList, WordListEntry

__all__ = [
    "User",
    "AuthIdentity",
    "Collection",
    "CollectionItem",
    "Material",
    "MaterialDifficulty",
    "Segment",
    "Attempt",
    "SegmentAttempt",
    "AudioBlob",
    "AudioSegment",
    "AudioAsset",
    "ImageBlob",
    "Part",
    "QuestionGroup",
    "Question",
    "QuestionAttempt",
    "LookupEvent",
    "MaterialVocabulary",
    "SavedWord",
    "SavedWordContext",
    "VocabularyReviewLog",
    "Deck",
    "DeckWord",
    "VocabularySettings",
    "Lexeme",
    "LexemeSense",
    "TranslationReport",
    "WordList",
    "WordListEntry",
    "UserWordList",
]
