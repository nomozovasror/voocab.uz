"""Grading + attempt persistence for listening form-completion (§7, §3.5).

Normalization is intentionally "dumb" and author-controlled: no fuzzy/
edit-distance matching, no number<->word conversion, no stemming. A given
answer is correct iff its normalized form exactly equals the normalized form
of any element of that question's ``correct_answers``.
"""

import re
import uuid
from datetime import datetime, timezone

from sqlmodel import select

from app.core.database import AsyncSession
from app.models.attempt import Attempt, AttemptStatus
from app.models.question_attempt import QuestionAttempt
from app.schemas.listening import AnswerIn
from app.services import listening as listening_service

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_answer(text: str) -> str:
    """§3.5: trim leading/trailing whitespace, collapse internal whitespace
    runs to a single space, lowercase. Applied identically to the given
    answer and every accepted answer before comparison."""
    return _WHITESPACE_RE.sub(" ", text.strip()).lower()


def grade_answer(given_answer: str, correct_answers: list[str]) -> bool:
    """Exact match (post-normalization) against ANY accepted variant.
    ``correct_answers=["photography"]`` vs given ``"photography course"`` is
    wrong — an extra word is not an exact match, word-limit enforcement
    aside (§3.5/§7)."""
    normalized_given = normalize_answer(given_answer)
    return any(
        normalized_given == normalize_answer(accepted) for accepted in correct_answers
    )


async def _find_in_progress_attempt(
    session: AsyncSession, user_id: uuid.UUID, material_id: uuid.UUID
) -> Attempt | None:
    """The caller's most recent ``in_progress`` attempt on this material, if
    any — §7 says an attempt is "created OR resumed", not always created
    fresh."""
    return (
        await session.exec(
            select(Attempt)
            .where(
                Attempt.user_id == user_id,
                Attempt.material_id == material_id,
                Attempt.status == AttemptStatus.IN_PROGRESS,
            )
            .order_by(Attempt.started_at.desc())  # type: ignore[attr-defined]
        )
    ).first()


async def submit_attempt(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    answers: list[AnswerIn],
) -> tuple[Attempt, list[dict]]:
    """Grade + persist one practice-mode attempt. Every question belonging to
    the material gets exactly one ``QuestionAttempt`` row — even if the
    student left it blank (``given_answer=""``) — and any submitted
    ``question_id`` that doesn't belong to this material is silently
    dropped: never graded, never trusted, never a crash. One transaction:
    the ``Attempt`` and all its ``QuestionAttempt`` rows commit together.

    If the caller already has an ``in_progress`` attempt on this material, it
    is RESUMED (reused, re-graded in place) rather than creating a second
    row — its old ``QuestionAttempt`` rows are deleted first so re-grading
    never leaves duplicates. In the current submit-all-at-once flow this is
    effectively a no-op (attempts go straight to ``submitted``), but it's
    correct if an "start an attempt" endpoint is added later.
    """
    questions = await listening_service.get_material_questions(session, material_id)
    given_by_question_id = {a.question_id: a.given_answer for a in answers}

    attempt = await _find_in_progress_attempt(session, user_id, material_id)
    if attempt is not None:
        existing_qas = (
            await session.exec(
                select(QuestionAttempt).where(
                    QuestionAttempt.attempt_id == attempt.id
                )
            )
        ).all()
        for qa in existing_qas:
            await session.delete(qa)
        # Flush the deletes before inserting the re-graded rows: no ORM
        # relationship teaches the unit-of-work this ordering, so without it
        # the inserts could race the deletes.
        await session.flush()
    else:
        attempt = Attempt(
            user_id=user_id,
            material_id=material_id,
            status=AttemptStatus.IN_PROGRESS,
        )
        session.add(attempt)
        await session.flush()  # assign attempt.id

    results: list[dict] = []
    correct_count = 0
    for question in questions:
        given = given_by_question_id.get(question.id, "")
        correct = grade_answer(given, question.correct_answers)
        if correct:
            correct_count += 1
        session.add(
            QuestionAttempt(
                attempt_id=attempt.id,
                question_id=question.id,
                given_answer=given,
                is_correct=correct,
            )
        )
        results.append(
            {
                "question_id": question.id,
                "is_correct": correct,
                "correct_answers": question.correct_answers,
                "replay_start_ms": question.replay_start_ms,
                "replay_end_ms": question.replay_end_ms,
            }
        )

    attempt.score = float(correct_count)
    attempt.total_questions = len(questions)
    attempt.status = AttemptStatus.SUBMITTED
    attempt.submitted_at = datetime.now(timezone.utc)
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    return attempt, results
