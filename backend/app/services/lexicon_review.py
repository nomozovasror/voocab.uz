"""Studio's admin review tab: the queue query, approve/fix, and the peek at
material sentences a sense's students actually met it in
(`brief-lexicon.md` §6.2).

## The queue is Reported first, then exposure, not flag type (A1)

2,476 `needs_review` senses is twenty hours of one person's work -- a queue
that never empties. What changes that is ordering the backlog by how many
learners have actually MET the sense rather than by which flag it carries:
a wrong meaning nobody has read yet costs nothing, and one one thousand
students have already seen is the whole reason this tab exists.

A sense with an OPEN `translation_reports` row still sorts first, ahead of
everything -- a learner who took the trouble to say "this is wrong" has
already done the finding a reviewer would otherwise have to do themselves,
which is a stronger signal than any exposure count. `report_count`/
`report_notes` ride on the row itself (one extra grouped join, the same
shape as `material_example_count` below) so a reviewer reads the complaint
without a second request.

Everything else -- `needs_review` senses AND the unapproved CORE bucket --
is now ONE list, ordered by :func:`exposure` descending. `needs_review`
sorts ahead of an unflagged core sense on an EQUAL exposure (a demonstrated
problem outranks "nobody has checked yet" when nothing else distinguishes
them), and `material_count` is the last tie-break, for the same reason it
was already exposure's own fallback: a great many senses currently carry
zero exposure of any kind (no attempts, no lookups, no saves have reached
this deploy yet), and material count is the only signal left to rank them
by until real usage exists. `reason=` still narrows the WHERE clause exactly
as before; it changes what is in the list, never how the list still sorts.

The core bucket itself is unchanged: a top-frequency lexeme's rank-1 sense
that was never flagged AND has never been approved -- the brief's "top
~2,000 lexemes by frequency, not yet approved". `frequency_band IN ("core",
"common")` stands in for "top ~2,000 by NGSL rank" -- see
`scripts/build_lexicon.py`'s own tiering (rank <= 1000 is `core`, <= 2000 is
`common`) -- because no numeric rank survives onto `Lexeme` itself; the
band is the only trace of it a query can reach.

## Exposure: how many learners have actually met this sense (A1)

A plain, unweighted sum of three counts, per sense:

* **attempters** -- distinct users who SUBMITTED an attempt on a material
  that glosses this sense (a join from `material_vocabulary.sense_id`
  through `material_id` into `attempts`, `status = 'submitted'`).
* **lookups** -- how many `lookup_events` resolved to this sense, mapped
  the same way the event itself was resolved: `(material_id, lemma)` into
  the material's own `material_vocabulary` row, then that row's
  `sense_id`. A plain count, not distinct users -- a word looked up three
  times by the same reader said something three times over, and the
  budget that makes repeats meaningful lives in the browser, not here.
* **saves** -- how many `saved_words` rows point at this sense. Already
  one per learner (`uq_saved_user_lexeme_sense`), so a plain count IS a
  count of distinct learners without a second `DISTINCT`.

No weights: the brief is explicit that this is a plain sum, not a scored
blend where one signal quietly outvotes the other two. `material_count`
(distinct materials glossing the sense) is a fourth, SEPARATE column --
never summed into exposure -- because "how many materials" and "how many
people" are different questions and the second is what this ordering is
actually for; the first is only the tie-break of last resort.

Computed as a handful of grouped subqueries, joined once per page
(`queue`) or once per sense (`exposure_for`, used by `approve`/`fix`'s own
response) -- never once per row in a loop. `ix_attempts_material_id_status`
(the migration alongside `needs_letter_hint`) is what keeps the attempters
subquery's join+filter an index lookup rather than a sequential scan of
every attempt on the platform.

Approving or fixing a sense closes every OPEN report against it in the same
transaction -- a reviewer who has just looked at the sense and signed off on
it has answered the report, whatever they changed.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, case, exists, func, or_
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.attempt import Attempt, AttemptStatus
from app.models.lexicon import REVIEW_REASONS, Lexeme, LexemeSense, TranslationReport
from app.models.material import Material
from app.models.user import User
from app.models.vocabulary import LookupEvent, MaterialVocabulary, SavedWord
from app.services import lexicon as lexicon_service

#: Independent of any other module's notion of a level -- a sense's `cefr`
#: is a plain checked string, and this is the whole of what "Fix" may set
#: it to.
CEFR_LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")

#: The core bucket's own frequency tiers -- see the module docstring.
_CORE_BANDS = ("core", "common")

#: `reason=` accepts any real review reason, or one of these two synthetic
#: values naming the second and third (P4) buckets, neither of which is a
#: review reason at all.
CORE_REASON = "core"
REPORTED_REASON = "reported"


def _has_open_report():
    """EXISTS rather than a join for the WHERE-clause use -- the row-level
    `report_count`/`report_notes` in :func:`queue` need the grouped
    subquery's own numbers, but a filter or a priority check only needs to
    know whether one exists at all."""
    return exists(
        select(TranslationReport.id).where(
            TranslationReport.lexeme_sense_id == LexemeSense.id,
            TranslationReport.status == "open",
        )
    )


def _priority_case():
    """0: an open translation report -- a learner already did the finding,
    and outranks everything else regardless of exposure (P4/A1). 1:
    everything else -- `needs_review` senses and the unapproved core bucket,
    now ONE group sorted by :func:`exposure` (see :func:`queue`'s own
    ORDER BY, and the module docstring's "A1" section for why flag type no
    longer decides the order within it). Lower sorts first."""
    return case((_has_open_report(), 0), else_=1)


def _core_bucket_where():
    return and_(
        LexemeSense.needs_review.is_(False),
        LexemeSense.sense_rank == 1,
        LexemeSense.approved_at.is_(None),
        Lexeme.frequency_band.in_(_CORE_BANDS),
    )


def _queue_where(reason: str | None):
    if reason == REPORTED_REASON:
        return _has_open_report()
    if reason == CORE_REASON:
        return _core_bucket_where()
    if reason is not None:
        return and_(
            LexemeSense.needs_review.is_(True),
            LexemeSense.review_reasons.any(reason),
        )
    return or_(
        _has_open_report(), LexemeSense.needs_review.is_(True), _core_bucket_where()
    )


async def reason_counts(session: AsyncSession) -> dict[str, int]:
    """One count per `REVIEW_REASONS` value, over every `needs_review`
    sense -- not the page, so a reviewer sees the whole backlog behind each
    filter chip rather than only what fits on screen (the catalogue's own
    rule: facets are counted over the whole set, never the page)."""
    counts: dict[str, int] = {}
    for reason in REVIEW_REASONS:
        stmt = select(func.count(LexemeSense.id)).where(
            LexemeSense.needs_review.is_(True),
            LexemeSense.review_reasons.any(reason),
        )
        counts[reason] = (await session.exec(stmt)).one()
    return counts


async def core_pending_count(session: AsyncSession) -> int:
    stmt = (
        select(func.count(LexemeSense.id))
        .join(Lexeme, LexemeSense.lexeme_id == Lexeme.id)
        .where(_core_bucket_where())
    )
    return (await session.exec(stmt)).one()


async def reported_count(session: AsyncSession) -> int:
    """How many senses currently carry an open report -- the third bucket's
    own count, alongside `core_pending`, over the whole backlog rather than
    the page."""
    stmt = select(func.count(func.distinct(TranslationReport.lexeme_sense_id))).where(
        TranslationReport.status == "open"
    )
    return (await session.exec(stmt)).one()


def _attempter_counts_subquery():
    """Per sense: distinct users who SUBMITTED an attempt on a material
    that glosses it -- see the module docstring's exposure section."""
    return (
        select(
            MaterialVocabulary.sense_id.label("sense_id"),
            func.count(func.distinct(Attempt.user_id)).label("n"),
        )
        .join(Attempt, Attempt.material_id == MaterialVocabulary.material_id)
        .where(
            MaterialVocabulary.sense_id.is_not(None),
            Attempt.status == AttemptStatus.SUBMITTED,
        )
        .group_by(MaterialVocabulary.sense_id)
        .subquery()
    )


def _lookup_counts_subquery():
    """Per sense: how many `lookup_events` resolved to it, mapped the same
    way the event itself was -- `(material_id, lemma)` into that material's
    own row, then the row's `sense_id`."""
    return (
        select(
            MaterialVocabulary.sense_id.label("sense_id"),
            func.count(LookupEvent.id).label("n"),
        )
        .join(
            LookupEvent,
            and_(
                LookupEvent.material_id == MaterialVocabulary.material_id,
                LookupEvent.lemma == MaterialVocabulary.lemma,
            ),
        )
        .where(MaterialVocabulary.sense_id.is_not(None), LookupEvent.lemma != "")
        .group_by(MaterialVocabulary.sense_id)
        .subquery()
    )


def _save_counts_subquery():
    """Per sense: how many `saved_words` rows point at it -- already one
    per learner (`uq_saved_user_lexeme_sense`), so this IS the count of
    distinct learners."""
    return (
        select(
            SavedWord.lexeme_sense_id.label("sense_id"),
            func.count(SavedWord.id).label("n"),
        )
        .group_by(SavedWord.lexeme_sense_id)
        .subquery()
    )


def _material_counts_subquery():
    """Per sense: how many DISTINCT materials gloss it -- the ordering's
    last-resort tie-break, and a separate figure from `material_example_
    count` above (a plain row count, which can exceed the material count
    when two lemmas in one material share a sense)."""
    return (
        select(
            MaterialVocabulary.sense_id.label("sense_id"),
            func.count(func.distinct(MaterialVocabulary.material_id)).label("n"),
        )
        .where(MaterialVocabulary.sense_id.is_not(None))
        .group_by(MaterialVocabulary.sense_id)
        .subquery()
    )


async def queue(
    session: AsyncSession,
    *,
    reason: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list[tuple[LexemeSense, Lexeme, int, int, list[str], int, int, int, int]]]:
    """The queue, paginated. `total` is over the FILTERED set, so a reviewer
    working one reason chip sees how much of THAT is left rather than the
    whole backlog. Each row carries its own `material_example_count`,
    `report_count`, `report_notes`, exposure's three parts (attempters,
    lookups, saves) and `material_count` from the same query -- extra
    grouped joins, not one query per row, and not one per part either."""
    where = _queue_where(reason)

    total_stmt = (
        select(func.count(LexemeSense.id))
        .join(Lexeme, LexemeSense.lexeme_id == Lexeme.id)
        .where(where)
    )
    total = (await session.exec(total_stmt)).one()

    example_counts = (
        select(
            MaterialVocabulary.sense_id.label("sense_id"),
            func.count(MaterialVocabulary.id).label("n"),
        )
        .group_by(MaterialVocabulary.sense_id)
        .subquery()
    )

    report_counts = (
        select(
            TranslationReport.lexeme_sense_id.label("sense_id"),
            func.count(TranslationReport.id).label("n"),
            func.array_agg(TranslationReport.note)
            .filter(TranslationReport.note != "")
            .label("notes"),
        )
        .where(TranslationReport.status == "open")
        .group_by(TranslationReport.lexeme_sense_id)
        .subquery()
    )

    attempter_counts = _attempter_counts_subquery()
    lookup_counts = _lookup_counts_subquery()
    save_counts = _save_counts_subquery()
    material_counts = _material_counts_subquery()

    attempters_n = func.coalesce(attempter_counts.c.n, 0)
    lookups_n = func.coalesce(lookup_counts.c.n, 0)
    saves_n = func.coalesce(save_counts.c.n, 0)
    material_count_n = func.coalesce(material_counts.c.n, 0)
    exposure_expr = attempters_n + lookups_n + saves_n

    stmt = (
        select(
            LexemeSense,
            Lexeme,
            func.coalesce(example_counts.c.n, 0),
            func.coalesce(report_counts.c.n, 0),
            report_counts.c.notes,
            attempters_n,
            lookups_n,
            saves_n,
            material_count_n,
        )
        .join(Lexeme, LexemeSense.lexeme_id == Lexeme.id)
        .outerjoin(
            example_counts, example_counts.c.sense_id == LexemeSense.id
        )
        .outerjoin(report_counts, report_counts.c.sense_id == LexemeSense.id)
        .outerjoin(attempter_counts, attempter_counts.c.sense_id == LexemeSense.id)
        .outerjoin(lookup_counts, lookup_counts.c.sense_id == LexemeSense.id)
        .outerjoin(save_counts, save_counts.c.sense_id == LexemeSense.id)
        .outerjoin(material_counts, material_counts.c.sense_id == LexemeSense.id)
        .where(where)
        .order_by(
            _priority_case(),
            exposure_expr.desc(),
            LexemeSense.needs_review.desc(),
            material_count_n.desc(),
            Lexeme.lemma,
            LexemeSense.sense_rank,
        )
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.exec(stmt)).all()
    return total, [
        (sense, lexeme, examples, reports, notes or [], attempters, lookups, saves, material_count)
        for sense, lexeme, examples, reports, notes, attempters, lookups, saves, material_count
        in rows
    ]


async def exposure_for(session: AsyncSession, sense_id: uuid.UUID) -> tuple[int, int, int, int]:
    """One sense's exposure, computed the identical way :func:`queue` does
    for a whole page -- used by `approve`/`fix`'s own response, which has
    exactly one row to answer for and would rather not rebuild the whole
    queue's four subqueries for it. Returns
    ``(attempters, lookups, saves, material_count)``.
    """
    attempters = (
        await session.exec(
            select(func.count(func.distinct(Attempt.user_id)))
            .select_from(MaterialVocabulary)
            .join(Attempt, Attempt.material_id == MaterialVocabulary.material_id)
            .where(
                MaterialVocabulary.sense_id == sense_id,
                Attempt.status == AttemptStatus.SUBMITTED,
            )
        )
    ).one()
    lookups = (
        await session.exec(
            select(func.count(LookupEvent.id))
            .select_from(MaterialVocabulary)
            .join(
                LookupEvent,
                and_(
                    LookupEvent.material_id == MaterialVocabulary.material_id,
                    LookupEvent.lemma == MaterialVocabulary.lemma,
                ),
            )
            .where(MaterialVocabulary.sense_id == sense_id, LookupEvent.lemma != "")
        )
    ).one()
    saves = (
        await session.exec(
            select(func.count(SavedWord.id)).where(
                SavedWord.lexeme_sense_id == sense_id
            )
        )
    ).one()
    material_count = (
        await session.exec(
            select(func.count(func.distinct(MaterialVocabulary.material_id))).where(
                MaterialVocabulary.sense_id == sense_id
            )
        )
    ).one()
    return attempters, lookups, saves, material_count


async def contexts(
    session: AsyncSession, sense_id: uuid.UUID, *, limit: int = 5
) -> list[tuple[MaterialVocabulary, str]]:
    """Up to `limit` materials whose vocabulary uses this sense -- the
    review row's "peek at material sentences" link. One join, not N+1."""
    stmt = (
        select(MaterialVocabulary, Material.title)
        .join(Material, MaterialVocabulary.material_id == Material.id)
        .where(MaterialVocabulary.sense_id == sense_id)
        .order_by(MaterialVocabulary.id.desc())
        .limit(limit)
    )
    return list((await session.exec(stmt)).all())


async def get_sense(
    session: AsyncSession, sense_id: uuid.UUID
) -> LexemeSense | None:
    return await session.get(LexemeSense, sense_id)


async def _close_open_reports(session: AsyncSession, sense_id: uuid.UUID) -> None:
    """A reviewer who has just approved or fixed a sense has answered every
    open report against it, whatever they changed -- there is no separate
    "dismiss" action, because Studio's review IS the answer a report was
    asking for."""
    rows = (
        await session.exec(
            select(TranslationReport).where(
                TranslationReport.lexeme_sense_id == sense_id,
                TranslationReport.status == "open",
            )
        )
    ).all()
    now = datetime.now(timezone.utc)
    for report in rows:
        report.status = "resolved"
        report.resolved_at = now
        session.add(report)


async def _finish(session: AsyncSession, sense: LexemeSense, commit: bool) -> LexemeSense:
    """Commit and refresh, or -- for a caller that owns the transaction
    (`lexicon_ai_review.apply`: one transaction per run) -- only flush."""
    if commit:
        await session.commit()
        await session.refresh(sense)
    else:
        await session.flush()
    return sense


async def approve(
    session: AsyncSession, sense: LexemeSense, *, admin_id: uuid.UUID,
    commit: bool = True,
) -> LexemeSense:
    """Clears `needs_review` -- the reasons stay, as the audit trail of what
    was once flagged -- and stamps who signed off on it, when. ``commit=False``
    leaves the commit to a caller that owns the transaction."""
    sense.needs_review = False
    sense.approved_by = admin_id
    sense.approved_at = datetime.now(timezone.utc)
    session.add(sense)
    await _close_open_reports(session, sense.id)
    return await _finish(session, sense, commit)


async def fix_and_approve(
    session: AsyncSession,
    sense: LexemeSense,
    *,
    admin_id: uuid.UUID,
    meaning_uz: str | None,
    definition_en: str | None,
    cefr: str | None,
    meaning_uz_alt: str | None = None,
    commit: bool = True,
) -> LexemeSense:
    """Edits whichever of the fields were sent, then approves in the
    same transaction -- Studio's "Fix" is one action, not an edit followed
    by a second click.

    A rank-1 sense's `cefr` is kept in step with `Lexeme.cefr`
    (`app.models.lexicon.Lexeme.cefr` is a denormalisation of exactly this
    column, recomputed, never hand-set elsewhere) -- fixing the grade a
    reviewer actually sees and leaving the catalogue's own copy stale would
    make the fix invisible everywhere a listing filters or sorts by level.

    A reviewer's decision LOCKS the sense (``approved_at``): the CALD apply
    and restore skip it from then on (`lexicon_cald.apply_plans`,
    `restore_senses`), so a re-run never overwrites what was fixed here. Two
    provenance marks keep that honest. A ``cald`` sense whose DEFINITION was
    rewritten becomes ``definition_source = 'human'`` (``cald_ref`` and the
    licence stay: it began as dictionary text); one whose definition was
    merely approved, or whose Uzbek alone was fixed, stays ``cald``. A
    ``cald``-graded level the reviewer changed becomes ``cefr_source =
    'ours'`` (``cald_cefr`` still says what the dictionary has), so nothing
    later mistakes the reviewer's grade for the dictionary's.

    ``meaning_uz_alt`` (the other translator's candidate) is not on Studio's
    form; the AI-assisted review (`lexicon_ai_review`) replaces the pair as a
    pair and passes it, with ``commit=False`` so a whole run is one
    transaction. ``None`` leaves a field alone; ``""`` empties it.
    """
    rerank = False
    if meaning_uz is not None:
        sense.meaning_uz = meaning_uz
    if meaning_uz_alt is not None:
        sense.meaning_uz_alt = meaning_uz_alt
    if definition_en is not None:
        if (sense.definition_source == "cald"
                and definition_en.strip() != sense.definition_en.strip()):
            sense.definition_source = "human"
        sense.definition_en = definition_en
    if cefr is not None:
        if sense.cefr_source == "cald" and cefr != sense.cefr:
            sense.cefr_source = "ours"
        sense.cefr = cefr
        rerank = True

    sense.needs_review = False
    sense.approved_by = admin_id
    sense.approved_at = datetime.now(timezone.utc)
    session.add(sense)
    if rerank:
        # A level changed: re-order the lexeme's senses easiest first (the
        # fixed sense may no longer be rank 1), `Lexeme.cefr` and the rank-1
        # `ngsl_conflict` flag with it. After the approval stamp: the fixed
        # sense keeps its reasons as history.
        await session.flush()
        await lexicon_service.rerank_lexemes(session, [sense.lexeme_id])
    await _close_open_reports(session, sense.id)
    return await _finish(session, sense, commit)


async def approver_names(
    session: AsyncSession, user_ids: list[uuid.UUID | None]
) -> dict[uuid.UUID, str]:
    """Display names of whoever approved the given senses, one query -- so a
    row can say "Claude review" rather than an id."""
    wanted = {user_id for user_id in user_ids if user_id is not None}
    if not wanted:
        return {}
    rows = (await session.exec(
        select(User.id, User.display_name).where(User.id.in_(wanted))
    )).all()
    return {user_id: name for user_id, name in rows}
