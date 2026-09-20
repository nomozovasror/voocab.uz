"""What the vocabulary endpoints send and accept.

One entry shape, used by all three screens that show a word — the lookup
panel mid-paper, the review's list, the learner's saved words — because they
are showing the same thing and a second shape would be a second set of
fields to keep in step.

What the wire deliberately does NOT carry is ``frequency_band``. It is the
figure the difficulty arithmetic reads and it means nothing to a learner:
"NGSL rank 2400" is a fact about a corpus. ``cefr_level`` is the one that
travels, because B2 is a scale they already have a feel for.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class VocabularyEntryOut(BaseModel):
    """One word or phrase, in this passage's sense."""

    id: uuid.UUID
    lemma: str
    #: The form as it stands in the passage. Not printed on its own — the
    #: reader can see it — and carried so the client can mark the right
    #: occurrence without asking again.
    surface: str
    pos: str
    meaning_en: str
    meaning_uz: str
    #: The sentence from the passage that contains it. Absent from the lookup
    #: panel by design (the reader is looking at it) and the whole value of a
    #: saved word on the review page.
    example: str
    cefr_level: str
    is_phrase: bool
    #: Where it stands, in the coordinates the reading highlights use.
    paragraph_index: int
    offset_start: int
    offset_end: int
    #: Whether the passage has been edited since this was glossed, so the
    #: offsets may no longer point at the right words. Derived, never stored.
    stale: bool = False
    #: Whether this learner already has it on their list. Absent (false) for
    #: a caller asking about somebody else's material.
    saved: bool = False


class LookupIn(BaseModel):
    """One word a reader tapped.

    ``paragraph_index`` and ``offset`` are optional but nearly always sent,
    and they are what makes the answer exact: an entry whose span contains
    that point needs no string matching at all, and a phrase is recognised
    by exactly the same test. Without them the word is matched by its
    spelling, which is right most of the time and cannot tell which
    occurrence was meant.
    """

    word: str = Field(min_length=1, max_length=80)
    paragraph_index: int | None = Field(default=None, ge=0)
    offset: int | None = Field(default=None, ge=0)


class LookupOut(BaseModel):
    """What to show for one tapped word.

    Both may be filled, and where they are the phrase is shown first: a
    reader who tapped ``rise`` inside ``give rise to`` is reading the phrase
    whatever their finger landed on. Both may be empty, which is an ordinary
    answer — a name, a number, or a morning the dictionary is unreachable.
    """

    word: VocabularyEntryOut | None = None
    phrase: VocabularyEntryOut | None = None


class VocabularySummaryOut(BaseModel):
    """How much there is to learn in one material, for the page that is
    choosing between materials."""

    total: int
    #: B1 / B2 / C1 counts. A spread, not an average: "B2: 30" is something a
    #: learner can act on and "mean CEFR 2.3" is not.
    levels: dict[str, int]


class VocabularyListOut(BaseModel):
    """A material's whole vocabulary, for the review page."""

    material_id: uuid.UUID
    total: int
    levels: dict[str, int]
    entries: list[VocabularyEntryOut]


class SaveWordsIn(BaseModel):
    """Words to put on the learner's list, from one material.

    A list rather than one word, because the review offers "save all" and
    "save the ones I looked up" beside the per-row button, and three
    endpoints for one verb is three places for the rules to drift.
    """

    material_id: uuid.UUID
    lemmas: list[str] = Field(min_length=1, max_length=200)


class SavedContextOut(BaseModel):
    """One place a saved word was met, with the sense it had there."""

    material_id: uuid.UUID
    material_title: str = ""
    surface: str
    pos: str
    meaning_en: str
    meaning_uz: str
    example: str
    cefr_level: str
    is_phrase: bool
    created_at: datetime


class SavedWordOut(BaseModel):
    """One word the learner is studying, with every passage it came from."""

    lemma: str
    created_at: datetime
    contexts: list[SavedContextOut]


class SavedWordsOut(BaseModel):
    total: int
    words: list[SavedWordOut]
