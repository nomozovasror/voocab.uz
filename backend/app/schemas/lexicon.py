"""Wire shapes for Studio's admin review tab and the public licences page
(`brief-lexicon.md` §6.2, §9). See `app.services.lexicon_review` for the
queue/approve/fix logic and `app.services.lexicon_licences` for the
attribution registry these are generated from.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ExposurePartsOut(BaseModel):
    """Exposure's three summed parts (A1) -- shown on hover/peek beside the
    row's own `exposure` total, so a reviewer can tell "a thousand lookups"
    apart from "a thousand saves" without a second request. See
    `app.services.lexicon_review`'s own docstring for exactly what each
    counts."""

    attempters: int
    lookups: int
    saves: int


class ReviewRowOut(BaseModel):
    """One `LexemeSense`, in the shape the review table draws a row from."""

    sense_id: uuid.UUID
    lexeme_id: uuid.UUID
    lemma: str
    pos: str
    is_phrase: bool
    cefr: str | None
    frequency_band: str | None
    sense_rank: int
    definition_en: str
    meaning_uz: str
    #: CALD's own level for the sense's CALD definition, where it has one
    #: (`LexemeSense.cald_cefr`) -- shown beside ``cefr`` for a sense flagged
    #: ``cald_cefr_far`` (ours was kept against it).
    cald_cefr: str | None = None
    #: The other translator's candidate -- empty where the judge agreed or
    #: the sense was never machine-translated (a material copy).
    meaning_uz_alt: str
    #: The material's own Uzbek this sense's meaning was copied from --
    #: empty for a translated (list-only) sense.
    meaning_uz_material: str
    review_reasons: list[str]
    needs_review: bool
    provisional: bool
    approved_by: uuid.UUID | None
    #: Who that was, by display name -- "Claude review" for a decision of the
    #: AI-assisted review (`lexicon_ai_review`), so a person can tell which
    #: approvals to look at again.
    approved_by_name: str | None = None
    approved_at: datetime | None
    #: Why the AI-assisted review left this sense for a person (empty if it
    #: did not) -- the review row shows it beside the reasons.
    review_note: str = ""
    #: How many `material_vocabulary` rows use this sense -- what the "peek
    #: sentences" link is offered on (zero means nothing to show).
    material_example_count: int
    #: How many OPEN "this translation is wrong" reports this sense
    #: currently carries (P4) -- zero for the ordinary row, and what puts a
    #: row in the "Reported" bucket ahead of everything else.
    report_count: int = 0
    #: The non-empty notes those open reports carry, so a reviewer reads
    #: what a learner actually said without a second request.
    report_notes: list[str] = []
    #: How many learners have actually met this sense (A1) -- the new
    #: ordering's own key: an unweighted sum of `exposure_parts`'s three
    #: numbers. What decides the queue's order now, ahead of flag type.
    exposure: int = 0
    #: The three counts `exposure` sums -- see `ExposurePartsOut` and
    #: `app.services.lexicon_review`'s module docstring for what each one
    #: counts.
    exposure_parts: ExposurePartsOut
    #: How many DISTINCT materials gloss this sense -- exposure's own
    #: tie-break, and the one signal left to rank by while exposure is
    #: commonly zero across the board.
    material_count: int = 0


class ReviewQueueOut(BaseModel):
    total: int
    reason_counts: dict[str, int]
    #: Top-frequency lexemes' rank-1 sense, never approved and not flagged --
    #: the queue's second bucket (`brief-lexicon.md` §6.2), counted
    #: separately from `reason_counts` because it isn't a review REASON.
    core_pending: int
    #: Senses with an open translation report -- the queue's FIRST bucket
    #: (P4), counted the same way as `core_pending` because "reported" is
    #: not a review reason either.
    reported_pending: int = 0
    rows: list[ReviewRowOut]


class ReviewContextOut(BaseModel):
    material_id: uuid.UUID
    material_title: str
    surface: str
    example: str


class ReviewFixIn(BaseModel):
    """Any subset of the three editable fields; omitted ones are left
    untouched. Sent alongside the approval it always causes -- Studio's
    "Fix" action edits and approves in one request, per the brief."""

    meaning_uz: str | None = Field(default=None, max_length=400)
    definition_en: str | None = Field(default=None, max_length=400)
    cefr: str | None = Field(default=None, max_length=4)


class LicenceSourceOut(BaseModel):
    """One row of the generated "Data sources and licences" page --
    everything but `count` comes from a small hand-written registry
    (`app.services.lexicon_licences.REGISTRY`); `count` is a live query, so
    the page can never claim a source this deploy's database doesn't
    actually contain."""

    key: str
    title: str
    authors: str
    licence_name: str
    licence_url: str
    source_url: str
    count: int
    #: Shown under the licence badge where non-empty -- today only Princeton
    #: WordNet's SemCor counts ("sense ordering only, not stored as
    #: definitions"), which read like a source of definitions if the card
    #: said nothing more (`app.services.lexicon_licences.REGISTRY`).
    usage_note: str = ""


class LicencesOut(BaseModel):
    sources: list[LicenceSourceOut]
