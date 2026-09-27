"""Studio's admin review tab: the queue query, approve/fix, and the peek at
material sentences a sense's students actually met it in
(`brief-lexicon.md` §6.2).

## The queue is three buckets, not one list (P4 adds the first)

A sense with an OPEN `translation_reports` row sorts first, ahead of even a
`pos_mismatch` `needs_review` row -- a learner who took the trouble to say
"this is wrong" has already done the finding a reviewer would otherwise have
to do themselves, so their report is the cheapest, highest-confidence signal
this queue has and it is wasted sitting behind a backlog nobody asked about.
`report_count`/`report_notes` ride on the row itself (one extra grouped
join, the same shape as `material_example_count` below) so a reviewer reads
the complaint without a second request.

Behind reports, `needs_review` senses come next -- something already
flagged a problem, and of those, a rank-1 sense flagged `pos_mismatch` sorts
before every other reason (the enrichment run's own priority note: 151
lexemes have one). Behind them sits the CORE bucket: a top-frequency
lexeme's rank-1 sense that was never flagged AND has never been approved --
the brief's "top ~2,000 lexemes by frequency, not yet approved", for a
reviewer with limited time spending it on the words a learner meets
constantly. `approved_at IS NULL` is what makes that bucket shrink as a
reviewer works through it; `needs_review` alone never would have, because
most of those senses were never wrong in the first place.

`frequency_band IN ("core", "common")` stands in for "top ~2,000 by NGSL
rank" -- see `scripts/build_lexicon.py`'s own tiering (rank <= 1000 is
`core`, <= 2000 is `common`) -- because no numeric rank survives onto
`Lexeme` itself; the band is the only trace of it a query can reach.

Approving or fixing a sense closes every OPEN report against it in the same
transaction -- a reviewer who has just looked at the sense and signed off on
it has answered the report, whatever they changed.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, case, exists, func, or_
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.lexicon import REVIEW_REASONS, Lexeme, LexemeSense, TranslationReport
from app.models.material import Material
from app.models.vocabulary import MaterialVocabulary

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
    """0: an open translation report -- a learner already did the finding
    (P4). 1: a rank-1 `pos_mismatch` sense (this run's own priority note).
    2: any other `needs_review` sense. 3: the core bucket. Lower sorts
    first."""
    return case(
        (_has_open_report(), 0),
        (
            and_(
                LexemeSense.needs_review.is_(True),
                LexemeSense.sense_rank == 1,
                LexemeSense.review_reasons.any("pos_mismatch"),
            ),
            1,
        ),
        (LexemeSense.needs_review.is_(True), 2),
        else_=3,
    )


def _band_rank():
    return case(
        (Lexeme.frequency_band == "core", 0),
        (Lexeme.frequency_band == "common", 1),
        else_=2,
    )


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


async def queue(
    session: AsyncSession,
    *,
    reason: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list[tuple[LexemeSense, Lexeme, int, int, list[str]]]]:
    """The queue, paginated. `total` is over the FILTERED set, so a reviewer
    working one reason chip sees how much of THAT is left rather than the
    whole backlog. Each row carries its own `material_example_count`,
    `report_count` and `report_notes` from the same query (extra grouped
    joins, not one query per row)."""
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

    stmt = (
        select(
            LexemeSense,
            Lexeme,
            func.coalesce(example_counts.c.n, 0),
            func.coalesce(report_counts.c.n, 0),
            report_counts.c.notes,
        )
        .join(Lexeme, LexemeSense.lexeme_id == Lexeme.id)
        .outerjoin(
            example_counts, example_counts.c.sense_id == LexemeSense.id
        )
        .outerjoin(report_counts, report_counts.c.sense_id == LexemeSense.id)
        .where(where)
        .order_by(
            _priority_case(), _band_rank(), Lexeme.lemma, LexemeSense.sense_rank
        )
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.exec(stmt)).all()
    return total, [
        (sense, lexeme, examples, reports, notes or [])
        for sense, lexeme, examples, reports, notes in rows
    ]


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


async def approve(
    session: AsyncSession, sense: LexemeSense, *, admin_id: uuid.UUID
) -> LexemeSense:
    """Clears `needs_review` -- the reasons stay, as the audit trail of what
    was once flagged -- and stamps who signed off on it, when."""
    sense.needs_review = False
    sense.approved_by = admin_id
    sense.approved_at = datetime.now(timezone.utc)
    session.add(sense)
    await _close_open_reports(session, sense.id)
    await session.commit()
    await session.refresh(sense)
    return sense


async def fix_and_approve(
    session: AsyncSession,
    sense: LexemeSense,
    *,
    admin_id: uuid.UUID,
    meaning_uz: str | None,
    definition_en: str | None,
    cefr: str | None,
) -> LexemeSense:
    """Edits whichever of the three fields were sent, then approves in the
    same transaction -- Studio's "Fix" is one action, not an edit followed
    by a second click.

    A rank-1 sense's `cefr` is kept in step with `Lexeme.cefr`
    (`app.models.lexicon.Lexeme.cefr` is a denormalisation of exactly this
    column, recomputed, never hand-set elsewhere) -- fixing the grade a
    reviewer actually sees and leaving the catalogue's own copy stale would
    make the fix invisible everywhere a listing filters or sorts by level.
    """
    if meaning_uz is not None:
        sense.meaning_uz = meaning_uz
    if definition_en is not None:
        sense.definition_en = definition_en
    if cefr is not None:
        sense.cefr = cefr
        if sense.sense_rank == 1:
            lexeme = await session.get(Lexeme, sense.lexeme_id)
            if lexeme is not None:
                lexeme.cefr = cefr
                session.add(lexeme)

    sense.needs_review = False
    sense.approved_by = admin_id
    sense.approved_at = datetime.now(timezone.utc)
    session.add(sense)
    await _close_open_reports(session, sense.id)
    await session.commit()
    await session.refresh(sense)
    return sense
