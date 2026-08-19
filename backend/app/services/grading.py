"""Grading + attempt persistence for listening (§7, §3.5).

Normalization is intentionally "dumb" and author-controlled: no fuzzy/
edit-distance matching, no number<->word conversion, no stemming. For a
gap-fill, a given answer is correct iff its normalized form exactly equals
the normalized form of any element of that question's ``correct_answers``.

A lettered question — multiple choice, matching — is graded differently,
because its ``correct_answers`` means something different: it is the answer
key, not a list of acceptable phrasings. The candidate's selection must equal
it as a SET — all of it, and nothing besides. IELTS gives no partial credit
for a "choose two", and one right letter plus one wrong one is not half an
answer.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.core.database import AsyncSession
from app.models.attempt import Attempt, AttemptStatus
from app.models.audio_blob import AudioBlob
from app.models.material import Material
from app.models.question import Question
from app.models.question_group import QuestionGroup
from app.models.question_attempt import QuestionAttempt
from app.schemas.listening import AttemptSubmit, ListenedSpanIn
from app.services import audio as audio_service
from app.services import listening as listening_service
from app.services import storage

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


def grade_choice(given_answer: str, correct_answers: list[str]) -> bool:
    """Exact SET match for a question answered by letter.

    The selection arrives as the chosen option letters, comma-separated
    ("b", or "a,c"), which is how it is stored on the attempt row too — still
    readable as an answer long after the options have been edited. Order and
    spacing don't matter; membership does, exactly. An empty selection is
    wrong: there is no question here whose answer is "none of them"."""
    chosen = {
        normalize_answer(letter)
        for letter in given_answer.split(",")
        if letter.strip()
    }
    if not chosen:
        return False
    return chosen == {normalize_answer(letter) for letter in correct_answers}


def grade_question(
    question: Question, given_answer: str, group: QuestionGroup
) -> bool:
    """Grade one answer the way its group is meant to be graded.

    Which way that is is the GROUP's, not the question's. It was the
    question's — a question with options is a lettered one — until matching
    put the options on the group and left its items looking, from the row
    alone, exactly like gap-fills. It is not even the group's TYPE: the same
    summary is answered in words or in letters depending on whether it is
    printed with a box. Nothing extra is loaded to ask either way — the walk
    that collects the questions already has their groups in hand."""
    if listening_service.answers_are_letters(group):
        return grade_choice(given_answer, question.correct_answers)
    return grade_answer(given_answer, question.correct_answers)


# --- What the learner listened to (brief §54) --------------------------------
#
# The author has already marked where every answer is said. That marking is the
# only map of the recording anyone has, and it is deliberately kept from the
# client — a candidate who knew that question 17 lives at 4:12 would have been
# told the shape of the answer. So the client reports only what it played, in
# milliseconds, and the crossing of the two happens here, once, after the
# attempt is committed and there is nothing left to give away.


def question_ranges(question: Question) -> list[tuple[int, int]]:
    """Every stretch of audio this question is answered from.

    Usually one. A "choose TWO letters" is answered in two places, and each
    right option carries its own — hearing one of them is not hearing the
    answer, so they are kept apart rather than flattened into the span that
    encloses both (which, for two options a minute apart, would be a minute of
    audio the question has nothing to do with)."""
    ranges: list[tuple[int, int]] = []
    if question.replay_start_ms is not None and question.replay_end_ms is not None:
        ranges.append((question.replay_start_ms, question.replay_end_ms))
    for span in (question.option_replay or {}).values():
        if isinstance(span, (list, tuple)) and len(span) == 2:
            ranges.append((int(span[0]), int(span[1])))
    return ranges


def _covers(span: ListenedSpanIn, moment: tuple[int, int]) -> bool:
    """Did this run of playback amount to hearing that moment?

    Half of it, at least. Not "overlaps at all": a learner who stops the audio
    a quarter-second into the sentence where the answer is said did not hear
    the answer, and counting it would turn every scrub past the moment into a
    listen. Not "all of it" either — playback started mid-word, or stopped on
    the last syllable, is still hearing it."""
    start, end = moment
    if end <= start:  # a marked point rather than a range
        return span.start_ms <= start <= span.end_ms
    overlap = min(span.end_ms, end) - max(span.start_ms, start)
    return overlap * 2 >= end - start


def count_hearings(spans: list[ListenedSpanIn], ranges: list[tuple[int, int]]) -> int:
    """How many separate plays covered the moment this question is answered
    from — any of its moments, for a question with more than one."""
    if not ranges:
        return 0
    return sum(1 for span in spans if any(_covers(span, r) for r in ranges))


def merged_ms(spans: list[ListenedSpanIn]) -> int:
    """Audio time listened to, overlaps counted once. Playing the same minute
    three times is one minute of the recording heard three times, and this is
    the "one minute" — how many times is ``hearings``, per question."""
    total = 0
    reach = -1  # the furthest ms already counted
    for span in sorted(spans, key=lambda s: (s.start_ms, s.end_ms)):
        start = max(span.start_ms, reach)
        if span.end_ms > start:
            total += span.end_ms - start
            reach = span.end_ms
    return total


# --- The transcript across an answer's moment (brief §71) --------------------


async def material_audio(session: AsyncSession, material: Material | None) -> dict:
    """The playable recording behind a material, resolved fresh.

    The URL is derived on every read and never stored: a stored one is a fact
    about which bucket the app was pointed at the day it was written."""
    empty = {"audio_url": None, "duration_ms": None}
    if material is None or material.audio_asset_id is None:
        return empty
    asset = await audio_service.get_asset(session, material.audio_asset_id)
    if asset is None:
        return empty
    blob = await session.get(AudioBlob, asset.blob_id)
    if blob is None:
        return empty
    return {
        "audio_url": await storage.get_storage().url(blob.storage_key),
        "duration_ms": blob.duration_ms,
    }


async def material_transcript(session: AsyncSession, material_id: uuid.UUID) -> list[dict]:
    """The material's transcript as its AUTHOR reads it: the ASR's lines with
    the author's corrections laid over the top.

    The author's, not the machine's. If the author corrected a misheard word,
    the answer key was written against the correction, and a review that
    quoted the raw ASR would show a learner a transcript that disagrees with
    the answer they were just marked against.

    Empty — never an error — when there is no audio, no transcript yet, or the
    asset has gone. Practice doesn't wait for a transcript, so a review with
    nothing to quote is an ordinary state, not a failure."""
    material = await session.get(Material, material_id)
    if material is None or material.audio_asset_id is None:
        return []
    asset = await audio_service.get_asset(session, material.audio_asset_id)
    if asset is None:
        return []
    rows = await audio_service.get_asset_segments(session, asset.blob_id)
    return audio_service.apply_overrides(rows, asset.transcript_overrides or {})


def _touches(line: dict, moment: tuple[int, int]) -> bool:
    start, end = moment
    if end <= start:
        return line["start_ms"] <= start <= line["end_ms"]
    # Strictly overlapping, so a line that merely ENDS where the marked range
    # begins is left out. Authors mark ranges by snapping to segment edges, so
    # touching-counts-as-overlapping would drag in the preceding line every
    # single time.
    return line["start_ms"] < end and line["end_ms"] > start


def transcript_across(lines: list[dict], ranges: list[tuple[int, int]]) -> list[dict]:
    """The lines a question's moments fall in, in playback order, each line
    once however many of the moments it covers."""
    return [
        {"start_ms": line["start_ms"], "end_ms": line["end_ms"], "text": line["text"]}
        for line in lines
        if any(_touches(line, r) for r in ranges)
    ]


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
    data: AttemptSubmit,
) -> Attempt:
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

    Alongside the marks it records how the attempt was WORKED: how long each
    answer took to arrive, how often it changed, and how many times the
    learner played the stretch of audio it comes from. None of that touches
    the grading — a client that reports nothing is graded identically — but it
    has to be collected from the first attempt onwards, because an attempt
    that has already happened can never be measured retroactively.
    """
    questions = await listening_service.get_material_questions(session, material_id)
    given_by_question_id = {a.question_id: a.given_answer for a in data.answers}
    timing_by_question_id = {a.question_id: a.timing for a in data.answers}

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
        # The session began before the row did — attempts are created at
        # submit, so left alone ``started_at`` would say the learner opened
        # and finished the test in the same instant. The client reports how
        # long it has been open and the server subtracts that from its OWN
        # clock, so nothing here depends on the device's idea of the date.
        if data.elapsed_ms is not None:
            attempt.started_at = datetime.now(timezone.utc) - timedelta(
                milliseconds=data.elapsed_ms
            )
        session.add(attempt)
        await session.flush()  # assign attempt.id

    # Marks, not questions answered. A "Choose TWO letters" question is two of
    # the numbers on the paper and two of the marks, so a test of 40 numbers
    # scores out of 40 however many rows it is made of.
    earned = 0
    total_marks = 0
    for question, group in questions:
        marks = listening_service.question_marks(group)
        total_marks += marks
        given = given_by_question_id.get(question.id, "")
        correct = grade_question(question, given, group)
        if correct:
            earned += marks
        timing = timing_by_question_id.get(question.id)
        session.add(
            QuestionAttempt(
                attempt_id=attempt.id,
                question_id=question.id,
                given_answer=given,
                is_correct=correct,
                first_answered_ms=timing.first_answered_ms if timing else None,
                last_changed_ms=timing.last_changed_ms if timing else None,
                changes=timing.changes if timing else None,
                focus_ms=timing.focus_ms if timing else None,
                # Only recorded when the client said what it played. Zero
                # hearings because nothing was reported and zero because the
                # learner never played that stretch are different facts.
                hearings=(
                    count_hearings(data.listened, question_ranges(question))
                    if data.listened
                    else None
                ),
            )
        )

    attempt.score = float(earned)
    attempt.total_questions = total_marks
    attempt.status = AttemptStatus.SUBMITTED
    attempt.submitted_at = datetime.now(timezone.utc)
    if data.elapsed_ms is not None:
        attempt.time_spent_ms = data.elapsed_ms
    if data.listened:
        attempt.listened_ms = merged_ms(data.listened)
    if data.seeks_back is not None:
        attempt.seeks_back = data.seeks_back
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)
    return attempt


async def attempt_result(session: AsyncSession, attempt: Attempt) -> dict:
    """Everything a review screen needs about one attempt, built from what was
    persisted rather than from what grading happened to have in hand.

    Deliberately re-read from the database even directly after a submit that
    already knew all of it. A results page reached by refreshing the URL and
    one reached by pressing submit are the same page, and the cheapest way to
    keep them the same is for there to be one function that answers the
    question. The extra read costs a query on a path that just committed a
    dozen writes.
    """
    material = await session.get(Material, attempt.material_id)
    questions = await listening_service.get_material_questions(
        session, attempt.material_id
    )
    given_rows = {
        row.question_id: row
        for row in (
            await session.exec(
                select(QuestionAttempt).where(
                    QuestionAttempt.attempt_id == attempt.id
                )
            )
        ).all()
    }
    lines = await material_transcript(session, attempt.material_id)

    results = []
    # The number on the paper, accumulated down the same ordered walk the
    # editor and the take page make. It is not ``question.number`` — that is
    # the question's place inside its own group, always 1..N, so printing it
    # would number a four-part test "1, 2, 1, 2, 3".
    printed = 1
    for question, group in questions:
        row = given_rows.get(question.id)
        ranges = question_ranges(question)
        marks = listening_service.question_marks(group)
        results.append(
            {
                "question_id": question.id,
                "number": printed,
                "marks": marks,
                "answered_by": (
                    "letters"
                    if listening_service.answers_are_letters(group)
                    else "words"
                ),
                "given_answer": row.given_answer if row else "",
                "is_correct": bool(row.is_correct) if row else False,
                "correct_answers": question.correct_answers,
                "replay_start_ms": question.replay_start_ms,
                "replay_end_ms": question.replay_end_ms,
                "option_replay": {
                    letter: list(span)
                    for letter, span in (question.option_replay or {}).items()
                },
                "transcript": transcript_across(lines, ranges),
            }
        )
        printed += marks

    return {
        "attempt_id": attempt.id,
        "material_id": attempt.material_id,
        "material_title": material.title if material else "",
        **(await material_audio(session, material)),
        "score": int(attempt.score or 0),
        "total_questions": attempt.total_questions or 0,
        "submitted_at": attempt.submitted_at,
        "results": results,
    }
