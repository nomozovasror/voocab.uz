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
from app.services import answers as answers_service
from app.services import audio as audio_service
from app.services import collections as collections_service
from app.services import drills as drills_service
from app.services import difficulty as difficulty_service
from app.services import listening as listening_service
from app.services import mistakes as mistakes_service
from app.services import storage
from app.services.learner_stats import score_pct

#: The comparison rule, which now lives in app/services/answers.py — see the
#: note there. Re-exported because it reads as grading's own: "what counts as
#: the same answer" is a grading question, and the module split is about who
#: is allowed to import whom.
normalize_answer = answers_service.normalize_answer


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


async def last_submitted_attempt(
    session: AsyncSession,
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    group_id: uuid.UUID | None = None,
) -> Attempt | None:
    """The caller's most recent finished sitting of this paper, if any.

    With ``group_id``, the most recent finished DRILL of that group instead.
    The two never mix: a drill is ``AttemptStatus.DRILLED`` and a sitting is
    ``SUBMITTED``, so "you have sat this" on the take page cannot be answered
    by a drill, and "you have drilled this" cannot be answered by a sitting.

    What lets somebody go back and READ a paper they have already done
    instead of sitting it again to find out how it went. Without it the only
    route to a review was through a fresh attempt, which is the one thing a
    learner coming back to analyse their mistakes does not want: it would
    write a second attempt, and every ability figure on the platform counts
    first attempts (see app/services/learner_stats.py). Analysing a paper
    would have quietly cost them the measurement.

    Most recent rather than best or first: the question a page asks when
    somebody opens a material they have done is "what happened last time",
    and every other reading of "your result" is a different question with a
    different page behind it.
    """
    return (
        await session.exec(
            select(Attempt)
            .where(
                Attempt.user_id == user_id,
                Attempt.material_id == material_id,
                Attempt.group_id == group_id
                if group_id is not None
                else Attempt.group_id.is_(None),  # type: ignore[attr-defined]
                Attempt.status
                == (
                    AttemptStatus.DRILLED
                    if group_id is not None
                    else AttemptStatus.SUBMITTED
                ),
                Attempt.submitted_at.is_not(None),  # type: ignore[attr-defined]
            )
            .order_by(Attempt.submitted_at.desc())  # type: ignore[attr-defined]
        )
    ).first()


async def _find_in_progress_attempt(
    session: AsyncSession,
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    group_id: uuid.UUID | None = None,
) -> Attempt | None:
    """The caller's most recent ``in_progress`` attempt at this exact scope,
    if any — §7 says an attempt is "created OR resumed", not always created
    fresh.

    ``group_id`` is matched EXACTLY, never loosely: a drill resumes a drill of
    the same group, and a sitting resumes a sitting (``group_id IS NULL``).
    Matching "this material, either scope" would let a sitting pick up a
    drill's half-finished row and re-grade six answers as a forty-mark paper —
    and it would do it silently, because the re-grade overwrites the score
    rather than failing.
    """
    return (
        await session.exec(
            select(Attempt)
            .where(
                Attempt.user_id == user_id,
                Attempt.material_id == material_id,
                Attempt.group_id == group_id
                if group_id is not None
                else Attempt.group_id.is_(None),  # type: ignore[attr-defined]
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

    await _grade_into(session, attempt, questions, data)
    attempt.status = AttemptStatus.SUBMITTED
    await _settle(session, attempt, data)
    return attempt


async def submit_drill(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    group: QuestionGroup,
    material_id: uuid.UUID,
    data: AttemptSubmit,
) -> Attempt:
    """Grade + persist one DRILL: a single question group worked on its own.

    A separate function from :func:`submit_attempt` rather than a scope
    parameter on it, and the reason is not symmetry with the take trees —
    there the point is that a leak should be unrepresentable. Here the failure
    is different and worse. A scope argument that defaults wrong, or a caller
    that forgets it, writes a six-mark attempt with ``group_id = NULL``: by the
    definition in :class:`app.models.attempt.AttemptStatus` that IS a whole
    sitting, so it would mark the paper done, withdraw it from recommendation,
    and become the first attempt every ability figure on the platform is
    measured from. Silently, because nothing about it is malformed. Two
    functions make the wrong row unrepresentable instead of guarded.

    What it shares with a sitting is the arithmetic — :func:`_grade_into`
    writes a row per question and totals the marks for both — and what it does
    not share is the score's meaning: ``total_questions`` is the GROUP's marks,
    six rather than forty, which is why the attempt must never be read as a
    sitting of the paper.
    """
    questions = await listening_service.get_group_questions(session, group)

    attempt = await _find_in_progress_attempt(
        session, user_id, material_id, group_id=group.id
    )
    if attempt is not None:
        for qa in (
            await session.exec(
                select(QuestionAttempt).where(
                    QuestionAttempt.attempt_id == attempt.id
                )
            )
        ).all():
            await session.delete(qa)
        # Flush the deletes before inserting the re-graded rows, for the same
        # reason the sitting does: no ORM relationship teaches the
        # unit-of-work this ordering.
        await session.flush()
    else:
        attempt = Attempt(
            user_id=user_id,
            material_id=material_id,
            group_id=group.id,
            status=AttemptStatus.IN_PROGRESS,
        )
        if data.elapsed_ms is not None:
            attempt.started_at = datetime.now(timezone.utc) - timedelta(
                milliseconds=data.elapsed_ms
            )
        session.add(attempt)
        await session.flush()  # assign attempt.id

    await _grade_into(session, attempt, questions, data)
    attempt.status = AttemptStatus.DRILLED
    await _settle(session, attempt, data)
    return attempt


async def _grade_into(
    session: AsyncSession,
    attempt: Attempt,
    questions: list[tuple[Question, QuestionGroup]],
    data: AttemptSubmit,
) -> None:
    """Write one ``QuestionAttempt`` per question and total the marks.

    The arithmetic both :func:`submit_attempt` and :func:`submit_drill` run,
    in one place. What differs between them is only WHICH questions they hand
    in — the whole material, or one group — and that is the whole of the
    difference. A second copy of this loop would be the "three walks are three
    chances to contradict each other" failure the take page's rules name, with
    the marks arithmetic as the thing they would come to disagree about.

    Marks, not questions answered. A "Choose TWO letters" question is two of
    the numbers on the paper and two of the marks, so a test of 40 numbers
    scores out of 40 however many rows it is made of.

    A skipped question is still an answer: every question handed in gets a
    row, blank ones included, which is what makes "missed entirely"
    classifiable at all.
    """
    given_by_question_id = {a.question_id: a.given_answer for a in data.answers}
    timing_by_question_id = {a.question_id: a.timing for a in data.answers}

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


async def _settle(
    session: AsyncSession, attempt: Attempt, data: AttemptSubmit
) -> None:
    """Stamp the finished attempt with how it was worked, and commit.

    The caller has already set the status, because that is the one thing a
    sitting and a drill genuinely disagree about.
    """
    attempt.submitted_at = datetime.now(timezone.utc)
    if data.elapsed_ms is not None:
        attempt.time_spent_ms = data.elapsed_ms
    if data.active_ms is not None:
        # Never above the wall clock. The client works this out from a timer
        # a throttled tab can fire late, and a "time spent" larger than the
        # time the page was open is a number nobody can explain.
        attempt.active_ms = min(
            data.active_ms,
            data.elapsed_ms if data.elapsed_ms is not None else data.active_ms,
        )
    if data.listened:
        attempt.listened_ms = merged_ms(data.listened)
    if data.seeks_back is not None:
        attempt.seeks_back = data.seeks_back
    if data.looked_up:
        # Lower-cased and deduplicated here rather than trusted as sent: the
        # budget counts unique lemmas, so a client that reported
        # ``["Phenomena", "phenomenon"]`` is reporting one word twice and the
        # review must not show it twice.
        seen: list[str] = []
        for lemma in data.looked_up:
            tidy = " ".join(lemma.split()).lower()[:80]
            if tidy and tidy not in seen:
                seen.append(tidy)
        attempt.looked_up = seen
    session.add(attempt)
    await session.commit()
    await session.refresh(attempt)


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
    #
    # And it starts where the PART says its numbering starts, not at 1. A
    # seeded material is one part of a real paper: Part 4 is Questions 31-40
    # and the recording says so aloud. The take page was taught this when
    # ``parts.first_number`` arrived; this walk was not, so a review of a Part
    # 4 numbered its rows 1-10 while the paper beside it read 31-40.
    printed = await listening_service.first_printed_number(
        session, attempt.material_id
    )
    # A drill reviews ONE group, and reviews it at the numbers the paper gives
    # it: the map cut out of Part 2 is Questions 15-20 on the page and in the
    # recording, which says them aloud. So the walk is still the whole
    # material's — rows outside the group are skipped while ``printed`` keeps
    # counting — rather than a second walk starting at the group. A separate
    # walk would have to arrive at 15 by agreeing with this one, and two walks
    # that must agree are two walks that eventually don't.
    scope = attempt.group_id
    for question, group in questions:
        marks = listening_service.question_marks(group)
        if scope is not None and group.id != scope:
            printed += marks
            continue
        row = given_rows.get(question.id)
        ranges = question_ranges(question)
        by_letter = listening_service.answers_are_letters(group)
        # Whether the answer was PICKED rather than written — wider than
        # by_letter, and a different question. See answers_are_chosen.
        chosen = listening_service.answers_are_chosen(group)
        correct = bool(row.is_correct) if row else False
        results.append(
            {
                "question_id": question.id,
                "number": printed,
                "marks": marks,
                "answered_by": "letters" if by_letter else "words",
                "given_answer": row.given_answer if row else "",
                "is_correct": correct,
                "correct_answers": question.correct_answers,
                # What KIND of wrong this was, classified here rather than in
                # the browser so the review screen and the practice page's
                # "Where you lose marks" cannot disagree about what counts as
                # a spelling slip — the same call, over the same rules, in
                # app/services/mistakes.py.
                #
                # ``None`` twice over: a right answer has no kind, and
                # neither has a CHOSEN one, because there is no spelling in
                # "b" — nor in TRUE — and which distractor pulled somebody is
                # a different analysis.
                "mistake": (
                    None
                    if correct or chosen
                    else mistakes_service.classify(
                        row.given_answer if row else "",
                        question.correct_answers,
                        group.word_limit,
                    )
                ),
                "replay_start_ms": question.replay_start_ms,
                "replay_end_ms": question.replay_end_ms,
                "option_replay": {
                    letter: list(span)
                    for letter, span in (question.option_replay or {}).items()
                },
                # Where in the passage the answer was — reading's counterpart
                # to the replay range above, and released on the same terms.
                #
                # The PART is stamped on here rather than stored on the row.
                # A span is written by the seed extraction, which knows a
                # passage and a paragraph and nothing about parts; the review
                # needs the part because a paper holds three passages, each
                # lettering its paragraphs from A. The question's group knows
                # it, so this is the one place that has both.
                "evidence": [
                    {
                        "part_id": group.part_id,
                        "paragraph_index": span["index"],
                        "start": span["start"],
                        "end": span["end"],
                    }
                    for span in (question.evidence or [])
                    if isinstance(span, dict)
                    and {"index", "start", "end"} <= span.keys()
                ],
                "transcript": transcript_across(lines, ranges),
            }
        )
        printed += marks

    return {
        "attempt_id": attempt.id,
        "material_id": attempt.material_id,
        "material_title": material.title if material else "",
        "material_reference": material.reference if material else None,
        **(await material_audio(session, material)),
        "score": int(attempt.score or 0),
        "total_questions": attempt.total_questions or 0,
        "submitted_at": attempt.submitted_at,
        "time_spent_ms": attempt.time_spent_ms,
        "looked_up": list(attempt.looked_up or []),
        **(await _standing(session, attempt, skill=material.type if material else "")),
        "results": results,
    }


async def _standing(session: AsyncSession, attempt: Attempt, *, skill: str) -> dict:
    """The three things that turn a score into a sentence.

    ``43%`` on its own says nothing anybody can act on. "Your 2nd try — the
    first was 14%" is somebody getting better at a paper; "the average here
    is 61%" is somebody finding out where they stand on it. The number is the
    same in all three; only one of them is worth reading.

    Each is withheld rather than faked when it cannot be had. There is no
    first-try figure on a first try — the same number under a second name is
    a panel padding itself out — and no platform average until the paper has
    been answered enough times for one to mean anything, which is
    :data:`app.services.difficulty.MIN_ANSWERS`' judgement and not a second
    threshold invented here.

    A DRILL's run is its own. "Your 3rd try" counted over the learner's full
    sittings would be a sentence about a different piece of work — they may
    have sat the paper twice and never drilled this group — so the run is
    scoped to the same group, and a sitting's run stays scoped to sittings.
    ``material_avg_pct`` and ``course`` are withheld outright for a drill:
    "everybody averages 61% here" is about a forty-mark paper and this score
    is out of six, and a drill is not a lesson in anybody's course.
    """
    drill = attempt.group_id is not None
    run = list(
        (
            await session.exec(
                select(Attempt)
                .where(
                    Attempt.user_id == attempt.user_id,
                    Attempt.material_id == attempt.material_id,
                    Attempt.group_id == attempt.group_id
                    if drill
                    else Attempt.group_id.is_(None),  # type: ignore[attr-defined]
                    Attempt.status
                    == (
                        AttemptStatus.DRILLED if drill else AttemptStatus.SUBMITTED
                    ),
                    Attempt.submitted_at.is_not(None),  # type: ignore[attr-defined]
                )
                .order_by(Attempt.submitted_at)  # type: ignore[arg-type]
            )
        ).all()
    )
    ids = [a.id for a in run]
    # 1 rather than 0 for an attempt not in the run: this is only reachable
    # from an unsubmitted one, and "your 0th try" is worse than a guess.
    attempt_no = ids.index(attempt.id) + 1 if attempt.id in ids else 1

    # Everybody's answers on this paper, from the projection the catalogue
    # already reads — a primary-key lookup, not a scan, and ``None`` below the
    # threshold, which is the guard doing its job rather than a missing value.
    band = (
        difficulty_service.unknown()
        if drill
        else (
            await difficulty_service.material_difficulty(
                session, [attempt.material_id]
            )
        ).get(attempt.material_id)
        or difficulty_service.unknown()
    )

    return {
        "attempt_no": attempt_no,
        "first_try_pct": score_pct(run[0]) if attempt_no > 1 and run else None,
        "material_avg_pct": band["correct_pct"],
        "course": (
            None
            if drill
            else await collections_service.next_after(
                session, attempt.user_id, attempt.material_id, skill=skill
            )
        ),
        "drill": (
            await _drill_standing(session, attempt, skill=skill) if drill else None
        ),
    }


async def _drill_standing(
    session: AsyncSession, attempt: Attempt, *, skill: str
) -> dict | None:
    """What the review of a finished drill needs to offer another one."""
    group = await session.get(QuestionGroup, attempt.group_id)
    if group is None:
        return None
    return {
        "group_id": group.id,
        "type": group.type,
        "next_group_id": await drills_service.next_after(
            session, attempt.user_id, group, skill=skill
        ),
    }
