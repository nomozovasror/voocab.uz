"""Studio's admin review tab, and the public "Data sources and licences"
page (`brief-lexicon.md` §6.2, §9).

Every ``/admin/lexicon/*`` route is gated by :data:`app.api.deps.AdminUser`
-- 403 for anybody whose ``is_admin`` is false, checked on the server on
every request regardless of what the client shows or hides. ``/licences``
needs no auth at all: it is the one page this phase makes public.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import AdminUser
from app.core.database import AsyncSession, get_session
from app.models.lexicon import REVIEW_REASONS, Lexeme, LexemeSense
from app.schemas.lexicon import (
    LicencesOut,
    LicenceSourceOut,
    ReviewContextOut,
    ReviewFixIn,
    ReviewQueueOut,
    ReviewRowOut,
)
from app.services import lexicon_licences, lexicon_review

router = APIRouter(prefix="/api", tags=["lexicon"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]

#: `reason=` on the queue accepts a real review reason or the synthetic
#: "core" bucket -- anything else is a 422, not a silently-empty page.
_VALID_REASONS = frozenset({*REVIEW_REASONS, lexicon_review.CORE_REASON})


def _row_out(
    sense: LexemeSense, lexeme: Lexeme, example_count: int
) -> ReviewRowOut:
    return ReviewRowOut(
        sense_id=sense.id,
        lexeme_id=lexeme.id,
        lemma=lexeme.lemma,
        pos=lexeme.pos,
        is_phrase=lexeme.is_phrase,
        cefr=sense.cefr,
        frequency_band=lexeme.frequency_band,
        sense_rank=sense.sense_rank,
        definition_en=sense.definition_en,
        meaning_uz=sense.meaning_uz,
        meaning_uz_alt=sense.meaning_uz_alt,
        meaning_uz_material=sense.meaning_uz_material,
        review_reasons=sense.review_reasons,
        needs_review=sense.needs_review,
        provisional=sense.provisional,
        approved_by=sense.approved_by,
        approved_at=sense.approved_at,
        material_example_count=example_count,
    )


async def _load_sense_and_lexeme(
    session: AsyncSession, sense_id: uuid.UUID
) -> tuple[LexemeSense, Lexeme]:
    sense = await lexicon_review.get_sense(session, sense_id)
    if sense is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sense not found")
    lexeme = await session.get(Lexeme, sense.lexeme_id)
    if lexeme is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sense not found")
    return sense, lexeme


@router.get("/admin/lexicon/review", response_model=ReviewQueueOut)
async def get_review_queue(
    user: AdminUser,
    session: SessionDep,
    reason: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ReviewQueueOut:
    """`needs_review` first (a rank-1 `pos_mismatch` sense ahead of every
    other reason), then the core bucket -- see
    `app.services.lexicon_review`'s own docstring for the two-bucket
    ordering. `reason_counts`/`core_pending` are always over the WHOLE
    backlog, regardless of the current filter, so the chips never blank out
    as a reviewer narrows the list."""
    if reason is not None and reason not in _VALID_REASONS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown reason")

    total, rows = await lexicon_review.queue(
        session, reason=reason, limit=limit, offset=offset
    )
    counts = await lexicon_review.reason_counts(session)
    core_pending = await lexicon_review.core_pending_count(session)
    return ReviewQueueOut(
        total=total,
        reason_counts=counts,
        core_pending=core_pending,
        rows=[_row_out(sense, lexeme, n) for sense, lexeme, n in rows],
    )


@router.get(
    "/admin/lexicon/review/{sense_id}/contexts",
    response_model=list[ReviewContextOut],
)
async def get_review_contexts(
    sense_id: uuid.UUID, user: AdminUser, session: SessionDep
) -> list[ReviewContextOut]:
    """The material sentences behind one sense -- the row's "peek" link.
    Not gated on the sense existing being approved or not; a reviewer may
    also want to double-check an already-approved one."""
    found = await lexicon_review.contexts(session, sense_id)
    return [
        ReviewContextOut(
            material_id=entry.material_id,
            material_title=title,
            surface=entry.surface,
            example=entry.example,
        )
        for entry, title in found
    ]


@router.post(
    "/admin/lexicon/review/{sense_id}/approve", response_model=ReviewRowOut
)
async def approve_review_row(
    sense_id: uuid.UUID, user: AdminUser, session: SessionDep
) -> ReviewRowOut:
    sense, lexeme = await _load_sense_and_lexeme(session, sense_id)
    sense = await lexicon_review.approve(session, sense, admin_id=user.id)
    example_count = len(await lexicon_review.contexts(session, sense_id, limit=10_000))
    return _row_out(sense, lexeme, example_count)


@router.post(
    "/admin/lexicon/review/{sense_id}/fix", response_model=ReviewRowOut
)
async def fix_review_row(
    sense_id: uuid.UUID,
    data: ReviewFixIn,
    user: AdminUser,
    session: SessionDep,
) -> ReviewRowOut:
    if data.cefr is not None and data.cefr not in lexicon_review.CEFR_LEVELS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown CEFR level")

    sense, lexeme = await _load_sense_and_lexeme(session, sense_id)
    sense = await lexicon_review.fix_and_approve(
        session,
        sense,
        admin_id=user.id,
        meaning_uz=data.meaning_uz,
        definition_en=data.definition_en,
        cefr=data.cefr,
    )
    # `fix_and_approve` may have updated the lexeme's own denormalised
    # `cefr` (rank-1 sense) -- reload so the response reflects it.
    lexeme = await session.get(Lexeme, lexeme.id) or lexeme
    example_count = len(await lexicon_review.contexts(session, sense_id, limit=10_000))
    return _row_out(sense, lexeme, example_count)


@router.get("/licences", response_model=LicencesOut)
async def get_licences(session: SessionDep) -> LicencesOut:
    """Public, unauthenticated: the attribution the NGSL family and OEWN's
    licences require, generated from what is actually in the database
    rather than a hand-written page (`brief-lexicon.md` §9)."""
    rows = await lexicon_licences.sources(session)
    return LicencesOut(sources=[LicenceSourceOut(**row) for row in rows])
