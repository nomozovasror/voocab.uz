"""A passage's words: finding one, listing them, and saving them to study.

The expensive half of this feature is not here. `seed/read_vocabulary.py`
glosses every passage once, at seed time, and what this module does is answer
questions about rows that already exist.

## Finding the word somebody tapped, without a lemmatiser

A reader double-clicks ``undertaken`` and the row says ``undertake``. The
obvious fix is a lemmatiser on the server, which means the NGSL form map, a
second copy of `seed/vocabulary.py`'s rules, and two implementations of
lemmatisation that have to agree forever.

None of that is needed, because the search space is not English. It is the
eighty-odd lemmas of ONE material, and against a set that small the question
can be asked four cheap ways in order:

1. **By where they tapped.** The client sends the paragraph and the two
   offsets of the selection, and an entry whose span CONTAINS that point is
   the answer -- exactly, with no string matching at all. This is also what
   makes phrases work: ``give rise to`` is stored as one entry over three
   words, so tapping ``rise`` inside it lands in the phrase's span.
2. **By the surface form**, which is the word as it stands in the passage
   and therefore what the reader most often taps.
3. **By the lemma**, for the reader who taps the dictionary form.
4. **By reducing the tapped word until it matches one of this material's
   lemmas.** A handful of suffix rules, tried against eighty candidates. A
   rule that produces a string none of the eighty matches has simply failed,
   which is the same acceptance test the seed side uses and is what makes
   rules this crude safe.

## What the take screen may ask for, and what it may not

``look_up`` answers about ONE word. ``entries`` -- the whole list -- is
refused to anybody who has not finished the paper (see
:func:`may_see_all`). The budget of three lookups is enforced in the
browser, which is the right place for a rule whose purpose is to make a
learner choose; but a list endpoint that handed out all eighty-six glosses
would make the browser's rule a formality, and the network tab is not a
difficult place to look.

The review page, which is where the list belongs, is reached by submitting.

## Saving is deduplicated; glossing is not

A material's entries are per material, because ``spring`` means different
things in different passages. A learner's saved words are per lemma, because
somebody studying ``spring`` is studying one word. The join between the two
is :class:`app.models.vocabulary.SavedWordContext`, which copies the gloss
rather than pointing at it: a material can be re-glossed, and a saved word
changing its meaning underneath somebody is worse than one that has aged.

## Every row this module writes is find-or-create

`replace_extracted` (the seed import path) and `_generate` (a live lookup)
are the two writers of `material_vocabulary` this project has, and both call
`app.services.lexicon.link_row` on every row they create, before it is
committed -- see that module's own docstring (`lexicon-spec.md` D6). A row
never sits without a `lexeme_id`/`sense_id`, not even for the length of one
request, and neither writer's ``meaning_core_en``/``meaning_core_uz`` is set
any more: that field's job -- the word's USUAL meaning, independent of this
passage -- now belongs to `LexemeSense.definition_en`/`meaning_uz`, which
`link_row` fills from the very same wording. The column stays on
`MaterialVocabulary` (existing readers still read it; migrating them is a
later phase) but nothing here writes it going forward.
"""

import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.attempt import Attempt, AttemptStatus
from app.models.lexicon import LexemeSense
from app.models.material import Material
from app.models.part import Part
from app.models.vocabulary import (
    LookupEvent,
    MACHINE_MADE,
    MaterialVocabulary,
    SavedWord,
    SavedWordContext,
    VocabularyReviewLog,
)
from app.services import dictionary as dictionary_service
from app.services import practice as practice_service
from app.services.lexicon import is_excluded_word, link_row

logger = logging.getLogger("app.services.vocabulary")

#: The levels a learner sees, in the order they are shown. An ordering the
#: database cannot give -- ``cefr_level`` is a string column and ``B1`` sorts
#: after ``C1`` alphabetically -- so it is named once here and every reader
#: uses it.
LEVELS: tuple[str, ...] = ("B1", "B2", "C1")

#: Suffix reductions for step 4 of the search, tried in order against this
#: material's own lemmas. Short on purpose: the seed side has the frequency
#: lists to check an answer against and can afford fourteen rules; here the
#: check is "does it match one of eighty lemmas", which is a narrower test,
#: so the rules that survive it are the ones that are nearly always right.
REDUCTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ies", ("y",)),
    ("ied", ("y",)),
    ("ing", ("", "e")),
    ("ed", ("", "e")),
    ("es", ("", "e")),
    ("er", ("", "e")),
    ("ly", ("",)),
    ("s", ("",)),
)

#: Everything around a word that is not the word. A reader double-clicking
#: ``languages,`` has looked up ``languages``, and one who drags across
#: ``"vogue"`` has looked up ``vogue``.
EDGES = re.compile(r"^[^\w]+|[^\w]+$", re.UNICODE)


def normalise(word: str) -> str:
    """One tapped word, as a thing to search by."""
    return EDGES.sub("", " ".join((word or "").split())).lower()


def reductions(word: str) -> list[str]:
    """Every shorter form worth trying for this word, longest first."""
    found = []
    for ending, replacements in REDUCTIONS:
        if word.endswith(ending) and len(word) - len(ending) >= 2:
            stem = word[: -len(ending)]
            found += [stem + replacement for replacement in replacements]
    # A doubled final consonant before -ed or -ing: `stopped`, `running`.
    doubled = re.sub(r"([bcdfghjklmnpqrstvwxz])\1(ed|ing)$", r"\1\2", word)
    if doubled != word:
        found += [doubled[:-2], doubled[:-3], doubled[:-2] + "e"]
    return found


async def entries(
    session: AsyncSession, material_id: uuid.UUID, *, hidden: bool = False
) -> list[MaterialVocabulary]:
    """Every word of one material, in passage order.

    Passage order rather than alphabetical, because the review shows them
    beside the passage they came from and a walk through the text is how
    somebody re-reads it. Alphabetical is a dictionary, and this is not one.
    """
    query = select(MaterialVocabulary).where(
        MaterialVocabulary.material_id == material_id
    )
    if not hidden:
        query = query.where(MaterialVocabulary.hidden.is_(False))
    rows = await session.exec(
        query.order_by(
            MaterialVocabulary.paragraph_index,
            MaterialVocabulary.offset_start,
        )
    )
    return list(rows.all())


async def summary(session: AsyncSession, material_id: uuid.UUID) -> dict:
    """How much there is to learn here, for the card that has to say so.

    Counted in SQL rather than by loading the rows, because the one caller
    that wants it is a material page that wants a number and not eighty-six
    glosses -- and because the same shape will be wanted per row in a
    catalogue query one day.
    """
    rows = await session.exec(
        select(
            MaterialVocabulary.cefr_level,
            MaterialVocabulary.unusual,
            func.count(),
        )
        .where(
            MaterialVocabulary.material_id == material_id,
            MaterialVocabulary.hidden.is_(False),
        )
        .group_by(MaterialVocabulary.cefr_level, MaterialVocabulary.unusual)
    )
    levels = {level: 0 for level in LEVELS}
    total = unusual = 0
    for level, is_unusual, count in rows.all():
        total += count
        if is_unusual:
            unusual += count
        if level in levels:
            levels[level] += count
    return {"total": total, "levels": levels, "unusual": unusual}


def stale(material: Material, entry: MaterialVocabulary) -> bool:
    """Whether the passage has been edited since this entry was made.

    The offsets are the reason to care: text that has moved leaves a gloss
    pointing at the wrong words. Derived rather than flagged, so no authoring
    path has to remember to set anything -- the one that forgot would be the
    one nobody noticed.
    """
    return material.updated_at > entry.generated_at


async def may_see_all(
    session: AsyncSession, material: Material, user_id: uuid.UUID
) -> bool:
    """Whether this caller may have the whole list.

    The author may, because it is theirs. Anybody who has SUBMITTED the paper
    may, because the list is what the review is for and they can no longer
    use it to answer anything. Nobody else, which is what keeps the three
    lookups meaningful while the paper is open.
    """
    if material.author_id == user_id:
        return True
    sat = await session.exec(
        select(Attempt.id)
        .where(
            Attempt.user_id == user_id,
            Attempt.material_id == material.id,
            Attempt.status == AttemptStatus.SUBMITTED,
        )
        .limit(1)
    )
    return sat.first() is not None


# --- Looking one word up ----------------------------------------------------


async def look_up(
    session: AsyncSession,
    material: Material,
    *,
    user_id: uuid.UUID,
    word: str,
    paragraph_index: int | None = None,
    offset: int | None = None,
    context: str = "take",
) -> dict:
    """What to show for the word a reader just tapped.

    Returns ``{"word": entry | None, "phrase": entry | None}``. Both can be
    filled, and when they are the phrase is shown FIRST: somebody who tapped
    ``rise`` inside ``give rise to`` is reading the phrase, whatever their
    finger landed on, and the word's own meaning underneath is there for the
    case where the phrase is not what confused them.

    Every call writes a :class:`LookupEvent`, including the ones that find
    nothing. The failures are the interesting half: a live answer is saved
    and becomes indistinguishable from an extracted one, so whether this
    lookup was served from the extraction is a fact that erases itself
    within milliseconds unless it is written down here.

    ``context`` says which screen asked -- ``take`` mid-paper, ``review``
    afterwards -- and this function treats the two identically on purpose.
    The budget that makes them different is the browser's, and it always
    was (see ``app/api/vocabulary.py``); what changes here is only what
    gets WRITTEN DOWN, on the event and on any entry generated to answer.
    """
    started = time.monotonic()
    # `hidden=True`: this search must still find a row hidden for being a
    # proper noun (`app.services.lexicon.link_row`), or every later tap on
    # the SAME name would fail to match it here, fall through to `_generate`,
    # find nothing there either (`known` would exclude it the same way), and
    # collide on the row that already exists -- turning "someone looked this
    # up" into "nobody can look this up again". The whole-list REVIEW page
    # (`entries()`'s other caller, `material_vocabulary`) is what actually
    # keeps a hidden row out of what a learner is shown; this is a private
    # search for "does an answer already exist", not a list being served.
    found = await entries(session, material.id, hidden=True)
    asked = normalise(word)

    phrase = None
    if paragraph_index is not None and offset is not None:
        phrase = _covering(found, paragraph_index, offset, phrases=True)
        exact = _covering(found, paragraph_index, offset, phrases=False)
        if exact is not None:
            return await _answered(
                session, material, user_id, asked, started, "cache",
                {"word": exact, "phrase": phrase}, paragraph_index, offset,
                context)

    matched = _by_string(found, asked)
    if matched is not None:
        return await _answered(
            session, material, user_id, asked, started, "cache",
            {"word": matched, "phrase": phrase}, paragraph_index, offset,
            context)

    # Nothing extracted for this one. It is a word the frequency filter did
    # not think was hard, and this reader does -- which is worth an answer
    # and worth keeping, so the next reader who taps it gets it for free.
    made = await _generate(session, material, asked, known=found,
                           paragraph_index=paragraph_index, context=context)
    return await _answered(
        session, material, user_id, asked, started,
        # `cache` where the phrase answered and the word did not: nothing was
        # generated, and calling it live would inflate the one number this
        # table exists to report.
        "live" if made is not None or phrase is None else "cache",
        {"word": made, "phrase": phrase}, paragraph_index, offset, context)


async def _answered(
    session: AsyncSession,
    material: Material,
    user_id: uuid.UUID,
    asked: str,
    started: float,
    source: str,
    answer: dict,
    paragraph_index: int | None,
    offset: int | None,
    context: str,
) -> dict:
    """Write down what just happened, and hand the answer back unchanged.

    Guarded, and the guard is the point: a log that can fail a lookup is a
    log that has made the feature less reliable in order to measure it. A
    row nobody can write is a row nobody will miss.
    """
    entry = answer["word"] or answer["phrase"]
    try:
        session.add(
            LookupEvent(
                user_id=user_id,
                material_id=material.id,
                asked=asked[:120],
                lemma=(entry.lemma if entry else "")[:80],
                source=source,
                latency_ms=int((time.monotonic() - started) * 1000),
                found=entry is not None,
                context=context,
                paragraph_index=paragraph_index,
                offset=offset,
            )
        )
        await session.commit()
    except Exception:  # noqa: BLE001 - telemetry never costs an answer
        logger.exception("could not log the lookup of %r", asked)
        await session.rollback()
    return answer


async def claim_lookups(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    attempt_id: uuid.UUID,
) -> int:
    """Attach this reader's unclaimed lookups on this material to the sitting
    that has just ended. Returns how many.

    Done here rather than at the moment of the lookup because there is no
    attempt to point at then: the row is created by the submit. What is left
    unclaimed afterwards is therefore a passage somebody looked words up in
    and never finished, which is a fact worth being able to count rather
    than a gap to apologise for.
    """
    rows = await session.exec(
        select(LookupEvent).where(
            LookupEvent.user_id == user_id,
            LookupEvent.material_id == material_id,
            LookupEvent.attempt_id.is_(None),  # type: ignore[union-attr]
        )
    )
    claimed = list(rows.all())
    for event in claimed:
        event.attempt_id = attempt_id
        session.add(event)
    if claimed:
        await session.commit()
    return len(claimed)


def _covering(
    found: list[MaterialVocabulary],
    index: int,
    offset: int,
    *,
    phrases: bool | None = None,
) -> MaterialVocabulary | None:
    """The entry whose span contains this point, if one does.

    Exact, and the only step of the search that needs no string comparison
    at all. It is also the whole of how a phrase is recognised: the brief's
    rule -- does the tapped offset fall inside some ``is_phrase`` entry's
    span -- is this function with ``phrases=True``.

    ``None`` asks about both kinds, which is what "is this span spoken for
    at all" means. The lookup itself always asks about one or the other,
    because it is building an answer with two slots and needs to know which
    slot an entry goes in.
    """
    for entry in found:
        if phrases is not None and entry.is_phrase != phrases:
            continue
        if (entry.paragraph_index == index
                and entry.offset_start <= offset < entry.offset_end):
            return entry
        # And everywhere else the same word stands. Without this, a tap on
        # the SECOND `give rise to` in a passage misses the phrase entirely
        # -- the span test is the only thing that recognises a phrase, and
        # it was only ever looking at the first occurrence. The word inside
        # it would be answered on its own, which is the one answer the
        # phrase exists to prevent.
        if any(where == index and left <= offset < right
               for where, left, right in entry.also_at):
            return entry
    return None


def _by_string(
    found: list[MaterialVocabulary], asked: str
) -> MaterialVocabulary | None:
    """The entry for this word, by surface, by lemma, then by reduction."""
    if not asked:
        return None
    by_surface = {entry.surface.lower(): entry for entry in found}
    by_lemma = {entry.lemma.lower(): entry for entry in found}
    if asked in by_surface:
        return by_surface[asked]
    if asked in by_lemma:
        return by_lemma[asked]
    for shorter in reductions(asked):
        if shorter in by_lemma:
            return by_lemma[shorter]
        if shorter in by_surface:
            return by_surface[shorter]
    return None


async def _generate(
    session: AsyncSession,
    material: Material,
    word: str,
    *,
    known: list[MaterialVocabulary],
    paragraph_index: int | None,
    context: str = "take",
) -> MaterialVocabulary | None:
    """Gloss a word the extraction missed, and keep what comes back.

    Kept, because it is the same process run later for a word the frequency
    filter did not flag. The list therefore grows towards what readers
    actually find hard, which is a better list than any frequency table can
    describe -- and it grows at a few words a passage, so the cost stays
    where it was put. The next reader of this passage meets the word already
    glossed and already marked in its CEFR colour, for free.

    Filed under the CONTEXT that caused it. Both are machine-made and both
    may be replaced by a later seed run, so the distinction costs nothing to
    keep and answers a question nothing else can: a ``review_lookup`` row is
    a word the extraction declined to offer and a learner went looking for
    anyway, which is the evidence for where the filter's cut is wrong. See
    ``SOURCES`` in ``app/models/vocabulary.py``.

    Everything here is guarded, and the guard is the last of several. Each
    provider in the chain is tried in turn (``dictionary.look_up``); this
    catch is for the case where every one of them failed, which the reader
    is told about in the panel's own voice rather than as a fact about a
    list they cannot see.
    """
    # A function word or a single letter is refused before any of this
    # runs -- not marked and hidden like a proper noun (`link_row` does
    # that), REFUSED: there is no meaning of "the" worth a model call, a
    # row, or an entry in the passage's word list, for anybody. See
    # `app.services.lexicon.is_excluded_word`.
    if is_excluded_word(word):
        return None

    # `prose` rather than `context`, which is what this held until the
    # lookup grew a context of its own. Two meanings on one name in one
    # function is how `source=` silently became "the paragraph text is not
    # the string 'review'", which is always true.
    part, index, start, end, prose = await _place(session, material, word,
                                                  paragraph_index)
    if part is None or not prose:
        return None
    # The form as the PASSAGE writes it, not as the query arrived. The search
    # is case-insensitive, so a reader who tapped `Vertical` at the start of
    # a sentence would otherwise have stored a surface that does not match
    # the text its own offsets point at -- and the surface is the one field
    # that makes those offsets checkable.
    surface = prose[start:end]
    try:
        gloss = await dictionary_service.look_up(word, prose)
    except Exception:  # noqa: BLE001 - one word is not worth a 500
        logger.exception("dictionary lookup of %r failed", word)
        return None
    if gloss is None:
        return None
    # The dictionary answers about the WORD, which is not always the exact
    # string tapped -- a plural, a possessive, an inflected form -- so the
    # same refusal is checked again on what it actually came back with.
    if is_excluded_word(gloss.lemma):
        return None

    # A word that turned out to be part of a term is stored as the TERM.
    # See `dictionary.Gloss.term`: the answer is about something wider than
    # what was tapped, and an entry over the word's own span would file a
    # term's meaning under a word that does not have it -- which is the
    # failure this whole pair of fields exists to stop.
    #
    # Widened only where the term is actually found AROUND the tap. A model
    # that names a term the paragraph does not contain, or one somewhere
    # else in it, has not answered about the word in front of the reader,
    # and an entry placed on a guess is a highlight over the wrong words.
    span = _term_span(prose, gloss.term, start, end)
    if span is not None:
        # And where the material already HAS that term, there is nothing to
        # add. This is not a rare case, it is the commonest one: a reader
        # taps `rise` inside `give rise to`, the extraction found the phrase
        # long ago, and the caller is already showing it. Writing a second
        # row for the same expression would break the one-lemma-per-material
        # rule on the way in, and showing it as "the word on its own" under
        # the phrase would print the same gloss twice.
        if _covering(known, index, span[0]) is not None:
            return None
        start, end = span
        surface = prose[start:end]

    # The lemma that came back may be one this material already has, and
    # that is not a rare collision -- it is what happens every time a model
    # answers about a WORD with the term it belongs to. A reader taps
    # `machine-learning`; the answer's lemma is `machine learning`, which
    # the extraction wrote hours ago.
    #
    # Checked here rather than left to the unique constraint. The constraint
    # does catch it, and the catch below is kept for the genuine race of two
    # readers tapping the same unusual word at once -- but a failed INSERT
    # leaves the session's connection in a state the next query on it cannot
    # survive, and what the reader saw was "we couldn't find a meaning for
    # that one" about a word the model had glossed perfectly well.
    already = _by_string(known, gloss.lemma)
    if already is not None:
        return already

    entry = MaterialVocabulary(
        material_id=material.id,
        part_id=part.id,
        lemma=gloss.lemma,
        surface=surface,
        pos=gloss.pos,
        meaning_en=gloss.meaning_en,
        meaning_uz=gloss.meaning_uz,
        sense_differs=gloss.sense_differs,
        example=_sentence_at(prose, start, end),
        paragraph_index=index,
        offset_start=start,
        offset_end=end,
        cefr_level=gloss.cefr_level,
        # No frequency list on this side of the fence, and guessing one would
        # put a made-up figure into the column the difficulty arithmetic
        # reads. Empty says "not measured", which is true.
        frequency_band="",
        is_phrase=" " in surface,
        source="review_lookup" if context == "review" else "extracted",
    )
    # Find-or-create, before this row is ever visible to anybody else: see
    # `app.services.lexicon.link_row` (`lexicon-spec.md` D6). No model call
    # here -- the gloss the reader is waiting on already answered that.
    #
    # `meaning_core_en`/`meaning_core_uz` are no longer WRITTEN to this row
    # (`lexicon-spec.md` P3) -- that job now belongs to the row's
    # `LexemeSense`. They are set here only to give `link_row` the model's
    # own usual-sense answer to build the provisional sense from (its own
    # fallback would otherwise reach for the CONTEXTUAL gloss, which is
    # right for an old row that predates this field but wrong when the
    # usual sense is sitting right here), then cleared before this row is
    # ever added to the session, so what lands in the database is exactly
    # what every future row will have: nothing.
    entry.meaning_core_en = gloss.meaning_core_en
    entry.meaning_core_uz = gloss.meaning_core_uz
    await link_row(session, entry)
    entry.meaning_core_en = entry.meaning_core_uz = ""
    session.add(entry)
    try:
        await session.commit()
    except IntegrityError:
        # Two readers tapped the same unusual word at the same moment. The
        # other one won, and their row is the answer -- but it is not in
        # `known`, which was read before either of them asked, so there is
        # nothing to hand back here.
        #
        # Answered from MEMORY rather than by reading the table again. A
        # failed INSERT leaves this session's connection unable to serve the
        # next query on it, and the re-read used to raise over the top of
        # the exception it was handling: the reader was told there was no
        # meaning, having waited for one that had just been written.
        #
        # So this tap finds nothing and the next tap on the same word finds
        # it in the cache. Losing one answer in a race is the small half of
        # the trade; the ordinary collision -- a term the material already
        # has -- never reaches here at all, because it is checked above.
        await session.rollback()
        return _by_string(known, gloss.lemma)
    await session.refresh(entry)
    return entry


async def _place(
    session: AsyncSession,
    material: Material,
    word: str,
    paragraph_index: int | None,
) -> tuple[Part | None, int, int, int, str]:
    """Where this word stands in the material, and the paragraph around it.

    The paragraph is what the model is given -- a whole passage would cost
    four times the tokens to answer a question about one sentence -- and the
    offsets are found here rather than taken from the client, because the
    client's are a claim and the passage is the fact.
    """
    parts = await session.exec(
        select(Part).where(Part.material_id == material.id).order_by(Part.order_index)
    )
    for part in parts.all():
        paragraphs = ((part.passage or {}).get("paragraphs")) or []
        order = ([paragraph_index] if paragraph_index is not None else []) + [
            index for index in range(len(paragraphs)) if index != paragraph_index
        ]
        for index in order:
            if not 0 <= index < len(paragraphs):
                continue
            text = paragraphs[index].get("text") or ""
            at = text.lower().find(word)
            if at >= 0:
                return part, index, at, at + len(word), text
    return None, 0, 0, 0, ""


def _term_span(
    prose: str, term: str, start: int, end: int
) -> tuple[int, int] | None:
    """Where a multi-word term stands, when it is the one around this tap.

    Located in the paragraph by exact search and then case-insensitively --
    the same two tries, in the same order, that `seed/read_vocabulary.py`
    uses for a phrase, and nothing cleverer for the same reason: a fuzzy
    match places a highlight over words nobody meant.

    Accepted only where the term CONTAINS the tapped word. The model is
    being asked a leading question -- "is this inside a term?" -- and a
    model asked a leading question finds one; requiring the answer to cover
    the span the reader actually pointed at is the check that costs nothing
    and refuses every term the paragraph has somewhere else.

    Returns nothing where the term is empty, unfindable, or elsewhere, and
    the caller then stores the word on its own, which is the ordinary case.
    """
    needle = (term or "").strip()
    if not needle or " " not in needle:
        return None
    for matcher in (str.find, lambda hay, pin: hay.lower().find(pin.lower())):
        at = 0
        while True:
            found = matcher(prose[at:], needle)
            if found < 0:
                break
            left = at + found
            right = left + len(needle)
            if left <= start and end <= right:
                return left, right
            at = left + 1
    return None


#: Where one sentence ends and the next begins. The same rough rule the seed
#: stage uses, and wrong about `Dr.` in the same way: a fragment for an
#: example is occasionally ugly, a whole paragraph is always useless.
SENTENCE = re.compile(r"(?<=[.!?][\"'’”)\]])\s+|(?<=[.!?])\s+")


def _sentence_at(text: str, start: int, end: int) -> str:
    edges = [0] + [split.end() for split in SENTENCE.finditer(text)] + [len(text)]
    for left, right in zip(edges, edges[1:]):
        if left <= start < right:
            return text[left : max(right, end)].strip()
    return text[start:end]


# --- The learner's own list -------------------------------------------------


async def _get_or_create_saved_word(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    sense_id: uuid.UUID,
    lemma: str,
    pos: str,
) -> tuple[SavedWord, bool]:
    """One saved word for `(user_id, sense_id)`, created if `save`'s own
    existence check (below) found none -- guarded the same way
    `lexicon.report_translation` guards its own partial unique index:
    attempted inside a SAVEPOINT (`session.begin_nested()`), so a second
    request racing to save the SAME sense for the SAME learner between that
    check and this INSERT collides on `uq_saved_user_lexeme_sense`.

    A failed flush leaves the SESSION needing `Session.rollback()` before it
    will run another statement at all -- and that call rolls back the
    session's WHOLE transaction, not just this SAVEPOINT (verified against
    this project's own asyncpg driver: the savepoint's own auto-rollback on
    exception is not enough to make the session usable again). ``save``
    therefore commits after every lemma it fully processes, specifically so
    that by the time a LATER lemma in the same call reaches this function,
    nothing from an earlier one is still sitting uncommitted for this
    rollback to destroy -- unlike `report_translation`, which never has more
    than the one row in flight and can afford a plain rollback.

    The winner -- already committed by whichever request got there first --
    is read back after the rollback and returned instead of raising.
    Returns `(word, created)`.
    """
    candidate = SavedWord(user_id=user_id, lemma=lemma, pos=pos, lexeme_sense_id=sense_id)
    session.add(candidate)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        await session.rollback()
        winner = (
            await session.exec(
                select(SavedWord).where(
                    SavedWord.user_id == user_id,
                    SavedWord.lexeme_sense_id == sense_id,
                )
            )
        ).first()
        assert winner is not None
        return winner, False
    return candidate, True


async def save(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    lemmas: list[str],
) -> int:
    """Put these words on the learner's list, THE SENSE THIS MATERIAL ROW
    HAS. Returns how many are new to it.

    Idempotent in both directions: saving a word twice is one word, and
    saving it from a second material is one word with two contexts -- AS
    LONG AS both materials gloss the same sense (P4): `bank` the financial
    institution met twice is one card with two example sentences, which
    teaches more than either alone; `bank` the river met from a different
    passage is a DIFFERENT saved word, because it is a different thing to
    learn. The key is `entry.sense_id`, not `entry.lemma`.
    """
    wanted = {normalise(lemma) for lemma in lemmas} - {""}
    if not wanted:
        return 0

    rows = await session.exec(
        select(MaterialVocabulary).where(
            MaterialVocabulary.material_id == material_id,
            MaterialVocabulary.lemma.in_(wanted),
        )
    )
    found = list(rows.all())
    if not found:
        return 0

    # Every row this project writes has been find-or-create linked since P3
    # (`link_row`, called from both writers) -- but a row can still reach
    # here unlinked: a fixture, or an import that predates that rule. This
    # is the last chance to fix that before a saved word is created with
    # nothing to point at, so it is repaired here rather than skipped.
    relinked = False
    for entry in found:
        if entry.sense_id is None:
            await link_row(session, entry)
            session.add(entry)
            relinked = True
    if relinked:
        # Committed, not merely flushed: `_get_or_create_saved_word` below
        # may call `session.rollback()` on a later lemma in this same call,
        # which -- see its own docstring -- rolls back this session's WHOLE
        # transaction, not just its own SAVEPOINT. A row this project must
        # never leave unlinked (`CLAUDE.md`, "every writer... is
        # find-or-create") needs its link durable before that can happen.
        await session.commit()

    existing = await session.exec(
        select(SavedWord).where(
            SavedWord.user_id == user_id,
            SavedWord.lexeme_sense_id.in_(
                [entry.sense_id for entry in found if entry.sense_id is not None]
            ),
        )
    )
    words = {word.lexeme_sense_id: word for word in existing.all()}
    # The context's own `meaning_core_en`/`meaning_core_uz` snapshot no
    # longer depends on `entry.meaning_core_en` (dead on a row written since
    # P3) -- it is filled from the entry's SENSE instead, batched once over
    # everything this call might save.
    senses = await senses_by_id(
        session, {entry.sense_id for entry in found if entry.sense_id is not None}
    )

    added = 0
    for entry in found:
        if entry.sense_id is None:
            continue  # link_row above failed silently -- nothing sane to key on
        word = words.get(entry.sense_id)
        if word is None:
            # `lemma`/`pos` are the display copy only (P4) -- the word's
            # usual meaning/definition/CEFR are read LIVE from
            # `lexeme_sense_id`'s `LexemeSense` from now on
            # (`app.services.vocabulary`'s readers), which is what lets an
            # admin's fix in Studio reach everybody already studying the
            # word. Nothing here writes `meaning_core_en`/`meaning_core_uz`
            # any more. Guarded against a second request racing to save the
            # same sense between the SELECT above and this INSERT -- see
            # `_get_or_create_saved_word`.
            word, created = await _get_or_create_saved_word(
                session,
                user_id=user_id,
                sense_id=entry.sense_id,
                lemma=entry.lemma,
                pos=entry.pos,
            )
            words[entry.sense_id] = word
            if created:
                added += 1
        already = await session.exec(
            select(SavedWordContext.id).where(
                SavedWordContext.saved_word_id == word.id,
                SavedWordContext.material_id == material_id,
            )
        )
        if already.first() is not None:
            continue
        sense = senses.get(entry.sense_id)
        session.add(
            SavedWordContext(
                saved_word_id=word.id,
                material_id=material_id,
                vocabulary_id=entry.id,
                surface=entry.surface,
                pos=entry.pos,
                meaning_core_en=(
                    entry.meaning_core_en
                    or (sense.definition_en if sense is not None else "")
                ),
                meaning_core_uz=(
                    entry.meaning_core_uz
                    or (sense.meaning_uz if sense is not None else "")
                ),
                meaning_en=entry.meaning_en,
                meaning_uz=entry.meaning_uz,
                sense_differs=entry.sense_differs,
                example=entry.example,
                cefr_level=entry.cefr_level,
                is_phrase=entry.is_phrase,
            )
        )
        # Committed per lemma, not once at the end of the whole call -- for
        # the same reason as the relink step above: a race on a LATER lemma
        # rolls back everything still uncommitted in this session, and this
        # lemma's word and context must already be durable before that can
        # ever run.
        await session.commit()
    return added


async def saved_state_for(
    session: AsyncSession, user_id: uuid.UUID, entries: list[MaterialVocabulary]
) -> dict[uuid.UUID, dict]:
    """For each entry (keyed by its own `MaterialVocabulary.id`): whether
    THIS SENSE is already saved, the saved word id if so, and whether some
    OTHER sense of the same lexeme is saved instead (P4 -- a lemma is no
    longer the unit a "saved" button asks about).

    Asked for the entries on one page rather than for the whole list,
    because the list grows without limit and the page is eighty-six rows.
    One query over every lexeme those entries belong to, not one per row.
    """
    lexeme_ids = {entry.lexeme_id for entry in entries if entry.lexeme_id is not None}
    if not lexeme_ids:
        return {}
    rows = await session.exec(
        select(SavedWord.id, SavedWord.lexeme_sense_id, LexemeSense.lexeme_id)
        .join(LexemeSense, LexemeSense.id == SavedWord.lexeme_sense_id)
        .where(SavedWord.user_id == user_id, LexemeSense.lexeme_id.in_(lexeme_ids))
    )
    by_sense: dict[uuid.UUID, uuid.UUID] = {}
    by_lexeme: dict[uuid.UUID, set[uuid.UUID]] = {}
    for word_id, sense_id, lexeme_id in rows.all():
        by_sense[sense_id] = word_id
        by_lexeme.setdefault(lexeme_id, set()).add(sense_id)

    state: dict[uuid.UUID, dict] = {}
    for entry in entries:
        if entry.sense_id is None:
            state[entry.id] = {
                "saved": False, "saved_word_id": None, "other_sense_saved": False,
            }
            continue
        saved_word_id = by_sense.get(entry.sense_id)
        other = bool(by_lexeme.get(entry.lexeme_id, set()) - {entry.sense_id})
        state[entry.id] = {
            "saved": saved_word_id is not None,
            "saved_word_id": saved_word_id,
            "other_sense_saved": other,
        }
    return state


async def senses_by_id(
    session: AsyncSession, sense_ids: set[uuid.UUID]
) -> dict[uuid.UUID, LexemeSense]:
    """A batch of `LexemeSense` rows, keyed by id -- one query for however
    many a caller needs (a page of material entries, a page of saved
    words), never one per row."""
    sense_ids = {sense_id for sense_id in sense_ids if sense_id is not None}
    if not sense_ids:
        return {}
    rows = await session.exec(select(LexemeSense).where(LexemeSense.id.in_(sense_ids)))
    return {sense.id: sense for sense in rows.all()}


async def usual_meanings_for(
    session: AsyncSession, entries: list[MaterialVocabulary]
) -> dict[uuid.UUID, LexemeSense]:
    """Every `LexemeSense` these entries point at, batched -- the shim for a
    row written since P3, which no longer carries its own
    `meaning_core_en`/`meaning_core_uz` copy (see `link_row`'s docstring):
    where a row's own copy is empty, the caller reads the usual meaning LIVE
    from here instead, keyed by `entry.sense_id`.
    """
    return await senses_by_id(
        session, {entry.sense_id for entry in entries if entry.sense_id is not None}
    )


async def saved_list_for(
    session: AsyncSession, word_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[SavedWordContext]]:
    """Every context for a known set of words, grouped by word -- the half
    of :func:`saved_list` that is reusable for a single word (the word
    page, a leech resolution's response) without re-running the "which
    words does this learner have" query for one row."""
    if not word_ids:
        return {}
    contexts = await session.exec(
        select(SavedWordContext)
        .where(SavedWordContext.saved_word_id.in_(word_ids))
        .order_by(SavedWordContext.created_at)
    )
    by_word: dict[uuid.UUID, list[SavedWordContext]] = {}
    for context in contexts.all():
        by_word.setdefault(context.saved_word_id, []).append(context)
    return by_word


async def saved_list(
    session: AsyncSession, user_id: uuid.UUID
) -> list[tuple[SavedWord, list[SavedWordContext]]]:
    """Everything the learner has saved, newest first, with its contexts."""
    words = await session.exec(
        select(SavedWord)
        .where(SavedWord.user_id == user_id)
        .order_by(SavedWord.created_at.desc())
    )
    found = list(words.all())
    if not found:
        return []
    by_word = await saved_list_for(session, [word.id for word in found])
    return [(word, by_word.get(word.id, [])) for word in found]


#: The word page's review history is capped here, not just sliced in the
#: API layer, so the query never pulls more rows than the brief asks it to
#: show -- a card answered thousands of times should not cost a thousand
#: rows fetched to throw most of them away.
MAX_HISTORY = 100


async def saved_word_with_history(
    session: AsyncSession, user_id: uuid.UUID, word_id: uuid.UUID
) -> tuple[SavedWord, list[SavedWordContext], list[VocabularyReviewLog]] | None:
    """The word page's whole answer: the word, its contexts, and its
    review history (newest first, capped at :data:`MAX_HISTORY`). ``None``
    for a word id this learner does not have -- including one that belongs
    to somebody else, which the caller turns into a 404 that says nothing
    about whether the word exists at all.

    Addressed by id (P4), not lemma -- a lemma is no longer unique to one
    saved word, so it cannot name one on its own any more.
    """
    word = await session.get(SavedWord, word_id)
    if word is None or word.user_id != user_id:
        return None
    contexts = (await saved_list_for(session, [word.id])).get(word.id, [])
    history_rows = await session.exec(
        select(VocabularyReviewLog)
        .where(VocabularyReviewLog.saved_word_id == word.id)
        .order_by(VocabularyReviewLog.reviewed_at.desc())
        .limit(MAX_HISTORY)
    )
    return word, contexts, list(history_rows.all())


async def bulk_action(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    word_ids: list[uuid.UUID],
    action: str,
) -> int:
    """``known``/``suspend``/``restore``/``forget`` over a batch of the
    caller's OWN words, by id (P4) -- the ``in_`` clause below is scoped to
    ``user_id``, so an id somebody else owns is silently not theirs to
    change rather than an error that would confirm it exists.

    ``forget`` is delegated to :func:`forget`, one id at a time, because
    it has its own contexts-then-word delete order to preserve; the other
    three are a plain column write over whichever of the requested ids
    this learner actually has.
    """
    if not word_ids:
        return 0

    # The lazy 30-day return, same as every other read/write path that
    # touches `status` -- a bulk `restore`/`known`/`suspend` should never
    # act over a status the 30 days have already made stale.
    await practice_service._reap_suspensions(session, user_id)

    if action == "forget":
        changed = 0
        for word_id in word_ids:
            if await forget(session, user_id, word_id):
                changed += 1
        return changed

    rows = await session.exec(
        select(SavedWord).where(
            SavedWord.user_id == user_id, SavedWord.id.in_(word_ids)
        )
    )
    words = list(rows.all())
    now = datetime.now(timezone.utc)
    for word in words:
        if action == "known":
            word.status = "known"
        elif action == "suspend":
            word.status = "suspended"
            word.suspended_until = now + timedelta(days=practice_service.SUSPEND_DAYS)
        elif action == "restore":
            word.status = practice_service.recompute_status(word)
            word.suspended_until = None
            word.leech_reset_at = now
        session.add(word)
    if words:
        await session.commit()
    return len(words)


async def mark_browsed(
    session: AsyncSession, user_id: uuid.UUID, word_id: uuid.UUID
) -> bool:
    """Record that a Browse card for this word was just shown. Returns
    whether there was one to mark (owner-only, same 404-shaped "not theirs"
    as every other by-id route in this module).

    THE ONLY thing this writes is ``browsed_at``. Browse
    (`brief-vocabulary-tuzatish-browse.md` §C) is explicitly not practice:
    no ``VocabularyReviewLog`` row, no FSRS card touched, no ``due`` moved,
    nothing counted in daily minutes -- writing any of those here would be
    exactly the "self-graded flashcard" the stage-1 brief already refused
    (see `app/services/CLAUDE.md`'s "the rating is computed, never asked").
    Debounced/idempotent by the caller (repeated flips of the same card
    within a sitting keep posting this); this function does not itself
    check for a recent call, because setting the same timestamp again a
    second later is indistinguishable from setting it once.
    """
    word = await session.get(SavedWord, word_id)
    if word is None or word.user_id != user_id:
        return False
    word.browsed_at = datetime.now(timezone.utc)
    session.add(word)
    await session.commit()
    return True


async def forget(
    session: AsyncSession, user_id: uuid.UUID, word_id: uuid.UUID
) -> bool:
    """Take a word off the list, with everywhere it was met, by id (P4).
    Returns whether there was one."""
    word = await session.get(SavedWord, word_id)
    if word is None or word.user_id != user_id:
        return False
    contexts = await session.exec(
        select(SavedWordContext).where(SavedWordContext.saved_word_id == word.id)
    )
    for context in contexts.all():
        await session.delete(context)
    # Flushed before the word goes, rather than left to one flush to order:
    # the contexts point AT the word, and a single flush emitted them the
    # wrong way round.
    await session.flush()
    await session.delete(word)
    await session.commit()
    return True


# --- Writing the pipeline's output in ---------------------------------------


async def replace_extracted(
    session: AsyncSession,
    *,
    material_id: uuid.UUID,
    part_id: uuid.UUID,
    rows: list[dict],
) -> tuple[int, int]:
    """Put a fresh extraction in, keeping whatever an author has touched.

    Returns ``(written, kept)``. What is kept is what a PERSON touched: a
    correction outlives the process that produced the thing it corrected,
    and the alternative -- a re-run that silently reverts an edit -- is the
    failure the ``source`` column exists to prevent.

    What is replaced is everything machine-made, which is ``extracted`` and
    ``review_lookup`` both. The second of those is a word a learner tapped
    on the review page and a model glossed on the spot, and it has to go for
    two reasons: a fresh extraction knows more about it (a frequency band, a
    sentence cut properly), and its offsets were measured against the text
    as it stood THEN. A re-import is a passage re-read, and a kept row from
    the previous reading points at the wrong words -- which is the whole
    reason this function replaces rather than merges.

    Flushes; the CALLER commits. The one caller is the passage importer,
    which is part-way through writing a material when it gets here, and a
    commit of its own would leave a half-imported paper behind on any later
    failure.
    """
    existing = await session.exec(
        select(MaterialVocabulary).where(
            MaterialVocabulary.material_id == material_id
        )
    )
    kept: dict[str, MaterialVocabulary] = {}
    for entry in existing.all():
        if entry.source in MACHINE_MADE:
            await session.delete(entry)
        else:
            kept[entry.lemma] = entry
    await session.flush()

    now = datetime.now(timezone.utc)
    written = 0
    # Deduplicated here, against what is kept AND against what this batch has
    # already written. One passage can offer the same lemma twice: the
    # candidate filter sends `descending` and `descent` as two words, and the
    # model correctly answers `descend` for both. The first occurrence wins,
    # which is passage order -- where the reader meets the word.
    #
    # Enforced here rather than left to the unique constraint, because the
    # constraint's answer is an IntegrityError that fails the whole import of
    # a passage over one repeated word. Ninety of two hundred and three
    # imports died this way.
    seen = set(kept)
    for row in rows:
        lemma = normalise(row.get("lemma") or "")
        # The candidate filter (`seed/vocabulary.py`'s `ASK_RANK`/`SHORTEST`)
        # already keeps almost every one of these out; refused again here so
        # nothing upstream of this function -- a hand-edited extraction file,
        # a future loosened filter -- can put a function word or a single
        # letter into a material's word list. See
        # `app.services.lexicon.is_excluded_word`.
        if not lemma or lemma in seen or is_excluded_word(lemma):
            continue
        seen.add(lemma)
        entry = MaterialVocabulary(
            material_id=material_id,
            part_id=part_id,
            lemma=lemma,
            surface=row.get("surface") or lemma,
            pos=row.get("pos") or "",
            meaning_en=row.get("meaning_en") or "",
            meaning_uz=row.get("meaning_uz") or "",
            sense_differs=bool(row.get("sense_differs")),
            example=row.get("example") or "",
            paragraph_index=int(row.get("index") or 0),
            offset_start=int(row.get("start") or 0),
            offset_end=int(row.get("end") or 0),
            # Trusted as far as its shape and no further: three
            # integers or the place is dropped. It is drawn as a mark
            # over the passage, and a malformed triple is a highlight
            # somewhere nobody meant.
            also_at=[
                [int(place[0]), int(place[1]), int(place[2])]
                for place in (row.get("again") or [])
                if isinstance(place, (list, tuple)) and len(place) == 3
            ],
            cefr_level=row.get("cefr_level") or "",
            frequency_band=row.get("frequency_band") or "",
            is_phrase=bool(row.get("is_phrase")),
            unusual=bool(row.get("unusual")),
            source="extracted",
            generated_at=now,
        )
        # Find-or-create before this row is ever visible to anybody else
        # (`app.services.lexicon.link_row`, `lexicon-spec.md` D6) -- no
        # model call in this loop, only a lookup against what P1/P2 and
        # earlier imports have already built.
        #
        # `meaning_core_en`/`meaning_core_uz` are no longer WRITTEN to this
        # row (P3): that job now belongs to the row's `LexemeSense`. Set here
        # only so `link_row` builds the provisional sense from the
        # extraction's own usual-sense answer rather than falling back to
        # the CONTEXTUAL gloss, then cleared before the row is added.
        entry.meaning_core_en = row.get("meaning_core_en") or ""
        entry.meaning_core_uz = row.get("meaning_core_uz") or ""
        await link_row(session, entry)
        entry.meaning_core_en = entry.meaning_core_uz = ""
        session.add(entry)
        written += 1
    await session.flush()
    return written, len(kept)


async def enrich_saved_contexts(
    session: AsyncSession, *, material_id: uuid.UUID
) -> int:
    """Give the words people have already saved the field they were saved
    without. Returns how many contexts gained one.

    ## Why this exists at all, when the copy rule says leave them alone

    A saved context COPIES its gloss and is never refreshed from the entry
    it came from -- see :class:`SavedWordContext`, which argues the case at
    length: a material can be re-glossed, and a learner's word quietly
    changing meaning underneath them is worse than one that has aged. That
    rule is not being relaxed.

    What is being fixed is different in kind. The usual meaning is not a
    correction to what they saved; it is a field that did not exist when
    they saved it, and a card with only "here" on it is exactly the failure
    ``meaning_core_en`` was added to stop. Somebody who saved ``learn`` from
    a passage about artificial intelligence has "a computer process of
    finding patterns in data" and nothing else, for ever, unless something
    goes back and fills the gap.

    So: filled where empty, never written over. Every meaning, example,
    level and part of speech they saved stays exactly as it was, and a
    context that already has a usual meaning is left entirely alone --
    including one enriched by an earlier run, so running this twice is the
    same as running it once.

    ``vocabulary_id`` is re-pointed at the same time, and that is the same
    kind of repair. A re-extraction deletes the machine-made row a context
    was taken from, and the foreign key sets the pointer to null (see the
    model); finding the new row for the same lemma puts the provenance back
    where it can be followed. The pointer is not what the card shows, so
    nothing a learner sees moves with it.

    The fill source is the entry's own `LexemeSense` now (P4), not
    `entry.meaning_core_en` -- a row written since P3 never carries that
    copy at all (`link_row`'s docstring names this exact gap as the reason
    a later phase would need to move here), so reading only the dead column
    would mean this function stopped closing the gap it exists for the
    moment the pipeline it runs beside stopped writing that column.

    Flushes; the CALLER commits, like :func:`replace_extracted` beside it
    and for the same reason -- the one caller is the passage importer,
    part-way through writing a material.
    """
    rows = await session.exec(
        select(SavedWordContext, SavedWord.lemma)
        .join(SavedWord, SavedWord.id == SavedWordContext.saved_word_id)
        .where(SavedWordContext.material_id == material_id)
    )
    contexts = list(rows.all())
    if not contexts:
        return 0

    fresh = await session.exec(
        select(MaterialVocabulary).where(
            MaterialVocabulary.material_id == material_id,
            MaterialVocabulary.lemma.in_([lemma for _, lemma in contexts]),
        )
    )
    by_lemma = {entry.lemma: entry for entry in fresh.all()}
    senses = await senses_by_id(
        session, {entry.sense_id for entry in by_lemma.values() if entry.sense_id}
    )

    filled = 0
    for context, lemma in contexts:
        entry = by_lemma.get(lemma)
        if entry is None:
            continue
        if context.vocabulary_id is None:
            context.vocabulary_id = entry.id
        sense = senses.get(entry.sense_id) if entry.sense_id else None
        usual_en = entry.meaning_core_en or (sense.definition_en if sense else "")
        usual_uz = entry.meaning_core_uz or (sense.meaning_uz if sense else "")
        if context.meaning_core_en or not usual_en:
            continue
        context.meaning_core_en = usual_en
        context.meaning_core_uz = usual_uz
        # Only meaningful beside a usual meaning, so it travels with one and
        # never on its own: a context marked "not the usual sense" with no
        # usual sense to show is a promise the card cannot keep.
        context.sense_differs = entry.sense_differs
        session.add(context)
        filled += 1
    await session.flush()
    return filled
