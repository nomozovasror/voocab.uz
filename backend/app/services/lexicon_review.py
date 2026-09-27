"""Studio's admin review tab: the queue query, approve/fix, and the peek at
material sentences a sense's students actually met it in
(`brief-lexicon.md` §6.2).

## The queue is two buckets, not one list

`needs_review` senses come first -- something already flagged a problem, and
of those, a rank-1 sense flagged `pos_mismatch` sorts before every other
reason (the enrichment run's own priority note: 151 lexemes have one).
Behind them sits the CORE bucket: a top-frequency lexeme's rank-1 sense that
was never flagged AND has never been approved -- the brief's "top ~2,000
lexemes by frequency, not yet approved", for a reviewer with limited time
spending it on the words a learner meets constantly. `approved_at IS NULL`
is what makes that bucket shrink as a reviewer works through it;
`needs_review` alone never would have, because most of those senses were
never wrong in the first place.

`frequency_band IN ("core", "common")` stands in for "top ~2,000 by NGSL
rank" -- see `scripts/build_lexicon.py`'s own tiering (rank <= 1000 is
`core`, <= 2000 is `common`) -- because no numeric rank survives onto
`Lexeme` itself; the band is the only trace of it a query can reach.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, case, func, or_
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.lexicon import REVIEW_REASONS, Lexeme, LexemeSense
from app.models.material import Material
from app.models.vocabulary import MaterialVocabulary

#: Independent of any other module's notion of a level -- a sense's `cefr`
#: is a plain checked string, and this is the whole of what "Fix" may set
#: it to.
CEFR_LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")

#: The core bucket's own frequency tiers -- see the module docstring.
_CORE_BANDS = ("core", "common")

#: `reason=` accepts any real review reason, or this synthetic value naming
#: the second bucket, which is not a reason at all.
CORE_REASON = "core"


def _priority_case():
    """0: a rank-1 `pos_mismatch` sense (this run's own priority note). 1:
    any other `needs_review` sense. 2: the core bucket. Lower sorts first."""
    return case(
        (
            and_(
                LexemeSense.needs_review.is_(True),
                LexemeSense.sense_rank == 1,
                LexemeSense.review_reasons.any("pos_mismatch"),
            ),
            0,
        ),
        (LexemeSense.needs_review.is_(True), 1),
        else_=2,
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
    if reason == CORE_REASON:
        return _core_bucket_where()
    if reason is not None:
        return and_(
            LexemeSense.needs_review.is_(True),
            LexemeSense.review_reasons.any(reason),
        )
    return or_(LexemeSense.needs_review.is_(True), _core_bucket_where())


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


async def queue(
    session: AsyncSession,
    *,
    reason: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list[tuple[LexemeSense, Lexeme, int]]]:
    """The queue, paginated. `total` is over the FILTERED set, so a reviewer
    working one reason chip sees how much of THAT is left rather than the
    whole backlog. Each row carries its own `material_example_count` from
    the same query (one extra grouped join, not one query per row)."""
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

    stmt = (
        select(LexemeSense, Lexeme, func.coalesce(example_counts.c.n, 0))
        .join(Lexeme, LexemeSense.lexeme_id == Lexeme.id)
        .outerjoin(
            example_counts, example_counts.c.sense_id == LexemeSense.id
        )
        .where(where)
        .order_by(
            _priority_case(), _band_rank(), Lexeme.lemma, LexemeSense.sense_rank
        )
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.exec(stmt)).all()
    return total, list(rows)


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


async def approve(
    session: AsyncSession, sense: LexemeSense, *, admin_id: uuid.UUID
) -> LexemeSense:
    """Clears `needs_review` -- the reasons stay, as the audit trail of what
    was once flagged -- and stamps who signed off on it, when."""
    sense.needs_review = False
    sense.approved_by = admin_id
    sense.approved_at = datetime.now(timezone.utc)
    session.add(sense)
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
    await session.commit()
    await session.refresh(sense)
    return sense
