"""Studio dashboard aggregate stats (author-scoped): materials/content/reach
counters plus a recent-activity list.

Pure data layer -- no HTTP. Every number here comes from an aggregate SQL
query (COUNT/SUM/GROUP BY) run against the DB, never from loading full row
sets into Python and counting client-side. The only per-row work is the
``recent`` list (bounded to 8 rows), and even its item counts are two
grouped queries (one for listening, one for dictation), not N+1.
"""

import uuid

from sqlalchemy import func
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.attempt import Attempt, AttemptStatus
from app.models.audio_asset import AudioAsset
from app.models.audio_blob import AudioBlob
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_group import QuestionGroup
from app.models.segment import Segment

# Material types the dashboard always reports a row for, even at zero, so
# the UI can render a real "0" instead of guessing whether a missing entry
# means "none yet" or "still loading".
KNOWN_TYPES = ("listening", "dictation")

RECENT_LIMIT = 8


async def _materials_total(session: AsyncSession, author_id: uuid.UUID) -> int:
    stmt = select(func.count(Material.id)).where(Material.author_id == author_id)
    return (await session.exec(stmt)).one()


async def _content_ms(session: AsyncSession, author_id: uuid.UUID) -> int:
    """Sum of ``duration_ms`` over the caller's OWN audio assets.
    ``AudioAsset`` has a UNIQUE(owner_id, blob_id) constraint, so one owner
    can never have two asset rows over the same blob -- reuse of the same
    clip across materials is already deduped by that constraint, no extra
    DISTINCT needed. NULL durations (still-transcribing blobs) contribute 0
    via SQL SUM's normal NULL handling; COALESCE covers the "no assets at
    all" case (SUM of zero rows is NULL, not 0)."""
    stmt = (
        select(func.coalesce(func.sum(AudioBlob.duration_ms), 0))
        .select_from(AudioAsset)
        .join(AudioBlob, AudioAsset.blob_id == AudioBlob.id)  # type: ignore[arg-type]
        .where(AudioAsset.owner_id == author_id)
    )
    return (await session.exec(stmt)).one()


async def _completions_and_learners(
    session: AsyncSession, author_id: uuid.UUID
) -> tuple[int, int]:
    """``completions`` = submitted attempts on the caller's materials.
    ``learners`` = distinct attempting users, EXCLUDING the author's own
    attempts (self-testing shouldn't inflate reach)."""
    stmt = (
        select(
            func.count(Attempt.id),
            func.count(func.distinct(Attempt.user_id)).filter(
                Attempt.user_id != author_id
            ),
        )
        .select_from(Attempt)
        .join(Material, Attempt.material_id == Material.id)  # type: ignore[arg-type]
        .where(
            Material.author_id == author_id,
            Attempt.status == AttemptStatus.SUBMITTED,
        )
    )
    completions, learners = (await session.exec(stmt)).one()
    return completions or 0, learners or 0


async def _by_type(session: AsyncSession, author_id: uuid.UUID) -> list[dict]:
    stats: dict[str, dict] = {
        t: {"type": t, "total": 0, "public": 0, "private": 0, "completions": 0}
        for t in KNOWN_TYPES
    }

    totals_stmt = (
        select(
            Material.type,
            func.count(Material.id),
            func.count(Material.id).filter(Material.visibility == "public"),
            func.count(Material.id).filter(Material.visibility == "private"),
        )
        .where(Material.author_id == author_id)
        .group_by(Material.type)
    )
    for mtype, total, public, private in (await session.exec(totals_stmt)).all():
        entry = stats.setdefault(
            mtype,
            {"type": mtype, "total": 0, "public": 0, "private": 0, "completions": 0},
        )
        entry["total"] = total
        entry["public"] = public
        entry["private"] = private

    completions_stmt = (
        select(Material.type, func.count(Attempt.id))
        .select_from(Attempt)
        .join(Material, Attempt.material_id == Material.id)  # type: ignore[arg-type]
        .where(
            Material.author_id == author_id,
            Attempt.status == AttemptStatus.SUBMITTED,
        )
        .group_by(Material.type)
    )
    for mtype, completions in (await session.exec(completions_stmt)).all():
        entry = stats.setdefault(
            mtype,
            {"type": mtype, "total": 0, "public": 0, "private": 0, "completions": 0},
        )
        entry["completions"] = completions

    # Stable order: the always-present known types first, then anything else
    # (future material types) alphabetically.
    ordered = [stats[t] for t in KNOWN_TYPES]
    ordered += sorted(
        (v for k, v in stats.items() if k not in KNOWN_TYPES),
        key=lambda e: e["type"],
    )
    return ordered


async def _recent(session: AsyncSession, author_id: uuid.UUID) -> list[dict]:
    stmt = (
        select(Material)
        .where(Material.author_id == author_id)
        .order_by(Material.updated_at.desc())  # type: ignore[attr-defined]
        .limit(RECENT_LIMIT)
    )
    materials = list((await session.exec(stmt)).all())
    if not materials:
        return []

    listening_ids = [m.id for m in materials if m.type == "listening"]
    dictation_ids = [m.id for m in materials if m.type == "dictation"]

    # item_count for the (at most RECENT_LIMIT) recent materials: one grouped
    # query per kind, not one query per material (no N+1).
    question_counts: dict[uuid.UUID, int] = {}
    if listening_ids:
        stmt_q = (
            select(Part.material_id, func.count(Question.id))
            .select_from(Question)
            .join(QuestionGroup, Question.group_id == QuestionGroup.id)  # type: ignore[arg-type]
            .join(Part, QuestionGroup.part_id == Part.id)  # type: ignore[arg-type]
            .where(Part.material_id.in_(listening_ids))  # type: ignore[attr-defined]
            .group_by(Part.material_id)
        )
        question_counts = dict((await session.exec(stmt_q)).all())

    segment_counts: dict[uuid.UUID, int] = {}
    if dictation_ids:
        stmt_s = (
            select(Segment.material_id, func.count(Segment.id))
            .where(Segment.material_id.in_(dictation_ids))  # type: ignore[attr-defined]
            .group_by(Segment.material_id)
        )
        segment_counts = dict((await session.exec(stmt_s)).all())

    recent: list[dict] = []
    for m in materials:
        if m.type == "listening":
            item_count = question_counts.get(m.id, 0)
        elif m.type == "dictation":
            item_count = segment_counts.get(m.id, 0)
        else:
            item_count = 0
        recent.append(
            {
                "id": m.id,
                "title": m.title,
                "type": m.type,
                "visibility": m.visibility,
                "item_count": item_count,
                "created_at": m.created_at,
                "updated_at": m.updated_at,
            }
        )
    return recent


async def get_stats(session: AsyncSession, author_id: uuid.UUID) -> dict:
    materials_total = await _materials_total(session, author_id)
    content_ms = await _content_ms(session, author_id)
    completions, learners = await _completions_and_learners(session, author_id)
    by_type = await _by_type(session, author_id)
    recent = await _recent(session, author_id)
    return {
        "materials_total": materials_total,
        "content_ms": content_ms,
        "learners": learners,
        "completions": completions,
        "by_type": by_type,
        "recent": recent,
    }
