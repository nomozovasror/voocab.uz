"""Listening authoring: create/read/update/delete Parts, QuestionGroups and
their Questions.

Pure data layer — no HTTP. The router (``app/api/listening.py``) handles
authorization (owner-only) and translates absence into 404/403, plus the
one-time-use 409 for a duplicate Part ``order_index``.

``QuestionGroup`` + its ``Question`` rows are always written/replaced as one
atomic unit (§3.6/§5): the questions are never embedded in the group's JSON
``config`` — they stay normalized rows so each answer is individually
gradeable and event-sourceable via ``QuestionAttempt`` (Faza 3).
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import case, distinct, func, literal_column
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.attempt import Attempt, AttemptStatus
from app.models.audio_asset import AudioAsset
from app.models.collection import Collection, CollectionItem
from app.models.audio_blob import AudioBlob
from app.models.material import Material
from app.models.material_difficulty import MaterialDifficulty
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import (
    FIXED_CHOICE_OPTIONS,
    FIXED_CHOICE_TYPES,
    LABELLING_TYPES,
    MATCHING_TYPES,
    QuestionGroup,
    QuestionGroupType,
    same_question_kind,
)
from app.models.user import User
from app.schemas.listening import (
    ChoiceQuestionIn,
    FixedChoiceQuestionIn,
    MatchingQuestionIn,
    PartCreate,
    PartUpdate,
    QuestionGroupIn,
)
from app.services import difficulty as difficulty_service
from app.services import images as images_service
from app.services import storage


# --- Part ---------------------------------------------------------------


async def get_parts(session: AsyncSession, material_id: uuid.UUID) -> list[Part]:
    return list(
        (
            await session.exec(
                select(Part)
                .where(Part.material_id == material_id)
                .order_by(Part.order_index)
            )
        ).all()
    )


async def get_part(session: AsyncSession, part_id: uuid.UUID) -> Part | None:
    return await session.get(Part, part_id)


async def create_part(
    session: AsyncSession, material_id: uuid.UUID, data: PartCreate
) -> Part:
    part = Part(
        material_id=material_id,
        order_index=data.order_index,
        title=data.title,
        audio_start_ms=data.audio_start_ms,
        audio_end_ms=data.audio_end_ms,
        passage=data.passage.model_dump() if data.passage else None,
    )
    session.add(part)
    await session.commit()
    await session.refresh(part)
    return part


async def update_part(session: AsyncSession, part: Part, data: PartUpdate) -> Part:
    """Partial update (title / audio range / passage).

    A field is touched only when the key is actually present in the request
    body -- "absent" and "sent as null" are different requests, and telling
    them apart is what lets a range be cleared. Treating null as absent (the
    obvious reading of ``if data.audio_start_ms is not None``) meant a part
    trimmed to a range could never be widened back to the whole recording:
    the editor sent nulls, the server ignored them, and the old range came
    back on the next reload with no error anywhere.

    The title is the exception: it is not nullable on the row, so a null
    there is nothing to apply rather than a request to clear it.

    The end>start check runs against the MERGED result (existing DB value for
    whichever bound wasn't sent), so e.g. sending only a new ``audio_end_ms``
    still gets validated against the part's current ``audio_start_ms``."""
    sent = data.model_fields_set
    if data.title is not None:
        part.title = data.title
    if "audio_start_ms" in sent:
        part.audio_start_ms = data.audio_start_ms
    if "audio_end_ms" in sent:
        part.audio_end_ms = data.audio_end_ms
    if "passage" in sent:
        # Sent as null clears it, the same way the audio bounds above are
        # cleared: a part written as reading and corrected to listening has a
        # passage to get rid of.
        part.passage = data.passage.model_dump() if data.passage else None

    if (
        part.audio_start_ms is not None
        and part.audio_end_ms is not None
        and part.audio_end_ms <= part.audio_start_ms
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "The part's end must come after its start",
        )

    session.add(part)
    await session.commit()
    await session.refresh(part)
    return part


async def _remove_questions(
    session: AsyncSession, questions: list[Question]
) -> None:
    """Delete questions along with the per-question attempt rows pointing at
    them.

    ``question_attempts.question_id`` is a plain FK with no ON DELETE, so a
    question anyone has ever answered cannot simply be dropped — the delete
    raises a ForeignKeyViolation and the whole request 500s. That is not a
    theoretical case: the editor autosaves the whole group, so a single test
    attempt used to make every subsequent save fail.

    Losing a gap costs its per-question detail, but not the attempt itself:
    ``attempts`` carries its own ``score``/``total_questions``, so the record
    that someone sat this material — and how they did — survives. Callers
    reach here only for questions that are genuinely going away; a question
    that merely changed is updated in place (see ``replace_question_group``)
    and keeps everything.
    """
    if not questions:
        return
    ids = [question.id for question in questions]
    attempts = (
        await session.exec(
            select(QuestionAttempt).where(QuestionAttempt.question_id.in_(ids))  # type: ignore[attr-defined]
        )
    ).all()
    # Loaded and deleted one by one rather than in a bulk DELETE: these rows
    # may already be in the session's identity map, and a bulk statement
    # leaves those copies behind as live objects pointing at rows that are
    # gone.
    for attempt in attempts:
        await session.delete(attempt)
    await session.flush()
    for question in questions:
        await session.delete(question)


async def _remove_group_attempts(session: AsyncSession, group_id: uuid.UUID) -> None:
    """Delete the DRILL attempts pointing at a group that is going away.

    ``attempts.group_id`` is a plain FK with no ON DELETE, so once anyone has
    drilled a group the group cannot simply be dropped — exactly the failure
    :func:`_remove_questions` already records one level down ("a single test
    attempt used to make every subsequent save fail"), and reached the same
    way: the editor autosaves the whole group.

    Not ``ON DELETE SET NULL``. A drill attempt whose ``group_id`` was nulled
    would become, by the definition in :class:`AttemptStatus`, a whole sitting
    — a six-mark attempt at a forty-mark paper, feeding every ability figure
    on the platform. Losing the drill is right; silently promoting it is the
    corruption the column exists to prevent.

    Only drills are touched. An attempt at the whole MATERIAL has
    ``group_id IS NULL`` and outlives any one group, the same way it outlives
    the questions :func:`_remove_questions` takes with it.
    """
    attempts = (
        await session.exec(select(Attempt).where(Attempt.group_id == group_id))
    ).all()
    if not attempts:
        return
    ids = [attempt.id for attempt in attempts]
    # The per-question rows first: ``question_attempts.attempt_id`` is a plain
    # FK too. Loaded and deleted one by one for the same reason as above —
    # a bulk DELETE leaves stale copies in the session's identity map.
    for row in (
        await session.exec(
            select(QuestionAttempt).where(QuestionAttempt.attempt_id.in_(ids))  # type: ignore[attr-defined]
        )
    ).all():
        await session.delete(row)
    await session.flush()
    for attempt in attempts:
        await session.delete(attempt)
    await session.flush()


async def _remove_part(session: AsyncSession, part: Part) -> None:
    """A part, its groups and their questions — without committing, so this
    can be one step of a larger transaction (deleting the whole material is
    the other caller).

    Flush the question deletes before the groups, and the groups before the
    part: there's no ORM relationship to teach the unit-of-work the FK order,
    so without this a parent delete can be issued first and trip the FK
    constraint (same pattern as the audio/dictation delete paths)."""
    groups = await get_question_groups(session, part.id)
    for group in groups:
        await _remove_group_attempts(session, group.id)
        await _remove_questions(session, await get_questions(session, group.id))
    await session.flush()
    for group in groups:
        await session.delete(group)
    await session.flush()
    await session.delete(part)


async def delete_part(session: AsyncSession, part: Part) -> None:
    await _remove_part(session, part)
    await session.commit()


async def remove_material_parts(
    session: AsyncSession, material_id: uuid.UUID
) -> None:
    """Every part of a material and everything under it, without committing.

    For the material delete (``app/services/materials.py``), which has more to
    do in the same transaction — nothing pointing at a material may outlive
    it, and ``parts.material_id`` is a plain FK with no ON DELETE."""
    for part in await get_parts(session, material_id):
        await _remove_part(session, part)
    await session.flush()


# --- QuestionGroup + Question ---------------------------------------------


async def get_question_groups(
    session: AsyncSession, part_id: uuid.UUID
) -> list[QuestionGroup]:
    return list(
        (
            await session.exec(
                select(QuestionGroup)
                .where(QuestionGroup.part_id == part_id)
                .order_by(QuestionGroup.order_index)
            )
        ).all()
    )


async def get_question_group(
    session: AsyncSession, group_id: uuid.UUID
) -> QuestionGroup | None:
    return await session.get(QuestionGroup, group_id)


async def get_questions(
    session: AsyncSession, group_id: uuid.UUID
) -> list[Question]:
    return list(
        (
            await session.exec(
                select(Question)
                .where(Question.group_id == group_id)
                .order_by(Question.number)
            )
        ).all()
    )


def _question_config(question) -> dict | None:
    """A question's own presentation, or ``None`` where it has none.

    A form gap's prompt is the template around it, which belongs to the group,
    so it stores NULL. A matching item stores its text and nothing else: what
    it may be matched to is the group's box of options, printed once above the
    set. Multiple choice stores the most, because its options really are one
    question's."""
    if isinstance(question, (MatchingQuestionIn, FixedChoiceQuestionIn)):
        # A statement to be judged stores exactly what a matching item does:
        # its own text. What it may be answered WITH is the group's — the box
        # for one, the type for the other.
        return {"prompt": question.prompt}
    if not isinstance(question, ChoiceQuestionIn):
        return None
    return {
        "prompt": question.prompt,
        "options": list(question.options),
        # Per option, because a "choose two" has two answers said at two
        # different moments — see ChoiceQuestionIn.option_replay. The
        # question's own replay_* columns stay empty for choice questions;
        # they are the form's, where one gap is one answer.
        "option_replay": {
            letter: list(span) for letter, span in question.option_replay.items()
        },
    }


async def _check_image_exists(session: AsyncSession, data: QuestionGroupIn) -> None:
    """A group naming a picture must name one that is actually stored.

    The schema can't check this — it has no session — and nothing else would:
    ``config`` is JSONB, so an id that was never uploaded, or was uploaded to a
    different environment, would be written happily and come back as a broken
    picture above the questions with nothing anywhere saying why.
    """
    image_id = getattr(data.config, "image", None)
    if image_id is None:
        return
    if await images_service.get_blob(session, image_id) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "That picture isn't stored here — upload it again.",
        )


async def create_question_group(
    session: AsyncSession, part_id: uuid.UUID, data: QuestionGroupIn
) -> QuestionGroup:
    """Create a group and its questions atomically. ``order_index`` is
    server-derived (append), mirroring how dictation segment order_index is
    derived from array position rather than trusted from the client.

    Appending means one past the highest, not the count: deleting a group from
    the middle leaves the indices sparse (0, 2), and counting would have put
    the next group at 2 — straight into the unique constraint, for a 409 the
    author did nothing to deserve."""
    await _check_image_exists(session, data)
    existing = await get_question_groups(session, part_id)
    group = QuestionGroup(
        part_id=part_id,
        order_index=max((g.order_index for g in existing), default=-1) + 1,
        type=data.type,
        instructions=data.instructions,
        word_limit=data.word_limit,
        # ``mode="json"`` because this lands in JSONB: the picture's id is a
        # UUID on the model and has to be a string in the column, and psycopg's
        # encoder has no opinion about how to write one.
        config=data.config.model_dump(mode="json"),
    )
    session.add(group)
    await session.flush()  # assign group.id
    for q in data.questions:
        session.add(
            Question(
                group_id=group.id,
                number=q.number,
                correct_answers=q.correct_answers,
                config=_question_config(q),
                replay_start_ms=q.replay_start_ms,
                replay_end_ms=q.replay_end_ms,
            )
        )
    await session.commit()
    await session.refresh(group)
    return group


async def replace_question_group(
    session: AsyncSession, group: QuestionGroup, data: QuestionGroupIn
) -> QuestionGroup:
    """Full atomic replace of the template + question set (PATCH).

    The question set is reconciled BY NUMBER rather than wiped and recreated:
    number 3 that survives the edit stays the same row, with the same id.
    Recreating it looked equivalent — the tree that comes back is identical —
    but a ``Question`` is referenced by ``QuestionAttempt``, so dropping it
    both broke the FK (the editor autosaves, so one attempt was enough to
    make every later save 500) and, had it been allowed to cascade, would
    have thrown away the record of what learners answered every time the
    author touched a comma.

    Only numbers that disappear from the payload are removed, and that path
    goes through ``_remove_questions`` for the attempts they leave behind.

    Changing what KIND of question the group holds is the exception: number 3
    of a form and number 3 of a multiple-choice set are not the same question
    wearing a different hat — the answer key means something else entirely —
    so nothing is kept across that change. Renaming the task is not that: gap
    3 of a form and gap 3 of the notes it becomes are the same question, with
    the same answers, marked at the same moment (see ``same_question_kind``)."""
    await _check_image_exists(session, data)
    retype = not same_question_kind(group.type, data.type)
    group.type = data.type
    group.instructions = data.instructions
    group.word_limit = data.word_limit
    group.config = data.config.model_dump(mode="json")  # see create_question_group
    session.add(group)

    existing = {q.number: q for q in await get_questions(session, group.id)}
    incoming = {q.number for q in data.questions}

    # Removals first, and flushed: a question's attempt rows have to go
    # before the question, and the question before the group's new rows are
    # written, or the unit of work is free to order those statements the
    # other way round and trip the FK it was ordered around.
    await _remove_questions(
        session,
        [q for number, q in existing.items() if retype or number not in incoming],
    )
    await session.flush()
    if retype:
        existing = {}

    for q in data.questions:
        question = existing.get(q.number)
        if question is None:
            question = Question(group_id=group.id, number=q.number, correct_answers=[])
        question.correct_answers = q.correct_answers
        question.config = _question_config(q)
        question.replay_start_ms = q.replay_start_ms
        question.replay_end_ms = q.replay_end_ms
        session.add(question)
    await session.commit()
    await session.refresh(group)
    return group


async def reorder_question_groups(
    session: AsyncSession, part_id: uuid.UUID, group_ids: list[uuid.UUID]
) -> list[QuestionGroup]:
    """Put the part's groups in the given order.

    The whole order is sent, and it has to be the whole order: a list missing
    a group, or naming one from another part, is a request built from a stale
    picture of the part and is refused rather than half-applied.

    Written in two passes because ``(part_id, order_index)`` is unique —
    swapping two groups by assigning their new indices directly collides on
    whichever is written first. The first pass moves everything out of the way
    (indices past the end, which nothing else can be using), the second puts
    them down in order; both are in the one transaction, so nothing outside it
    ever sees the parked indices."""
    groups = await get_question_groups(session, part_id)
    by_id = {group.id: group for group in groups}
    if set(group_ids) != set(by_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "group_ids must name exactly the groups in this part",
        )

    parked = max((g.order_index for g in groups), default=0) + 1
    for offset, group_id in enumerate(group_ids):
        by_id[group_id].order_index = parked + offset
        session.add(by_id[group_id])
    await session.flush()

    for index, group_id in enumerate(group_ids):
        by_id[group_id].order_index = index
        session.add(by_id[group_id])
    await session.commit()
    return await get_question_groups(session, part_id)


async def delete_question_group(session: AsyncSession, group: QuestionGroup) -> None:
    await _remove_group_attempts(session, group.id)
    await _remove_questions(session, await get_questions(session, group.id))
    await session.flush()
    await session.delete(group)
    await session.commit()


async def first_printed_number(
    session: AsyncSession, material_id: uuid.UUID
) -> int:
    """The number the FIRST question of a material carries on its paper.

    Its first part's ``first_number`` where there is one, and 1 otherwise —
    which is what every author-written material means and what every part
    written before the column existed means.
    """
    parts = await get_parts(session, material_id)
    if parts and parts[0].first_number is not None:
        return parts[0].first_number
    return 1


async def get_group_questions(
    session: AsyncSession, group: QuestionGroup
) -> list[tuple[Question, QuestionGroup]]:
    """One group's questions, in the same shape
    :func:`get_material_questions` returns.

    The same shape on purpose: it is what lets a drill and a whole sitting run
    the identical grading arithmetic (``grading._grade_into``) over different
    selections, rather than growing a second loop that has to agree with the
    first about what a mark is.
    """
    return [
        (question, group) for question in await get_questions(session, group.id)
    ]


async def get_material_questions(
    session: AsyncSession, material_id: uuid.UUID
) -> list[tuple[Question, QuestionGroup]]:
    """Every ``Question`` belonging to a material, in the material's display
    order (part ``order_index`` -> group ``order_index`` -> question
    ``number``), each with the group it belongs to.

    ``Question.number`` is only unique within its group, not globally, so
    this traversal order — not a bare ORDER BY number — is what grading
    (Faza 3) uses to order per-question results and to build the
    question_id -> correct_answers map.

    The group comes with it because grading walks questions and two of the
    things it needs are the group's: how many marks the question is worth (a
    "Choose TWO letters" is two of the numbers printed down the side of the
    paper, so a 40-mark test has 40 numbers and not 40 rows), and whether its
    answer key is option letters or accepted phrasings. That second one used
    to be read off the question row, on the reasoning that a question with
    options is a lettered one — which stopped being true when matching
    arrived and put the options on the group."""
    questions: list[tuple[Question, QuestionGroup]] = []
    for part in await get_parts(session, material_id):
        for group in await get_question_groups(session, part.id):
            questions.extend(
                (question, group)
                for question in await get_questions(session, group.id)
            )
    return questions


# --- Consumption read tree (§7, §3.4) ---------------------------------------


#: The types whose ``correct_answers`` is always an answer key of option
#: letters rather than a list of accepted phrasings. What separates them is not
#: whether the question has options — a matching item's are its group's — but
#: what the candidate submits: a letter, matched as a set, against words,
#: matched after normalization.
LETTERED_TYPES = frozenset({QuestionGroupType.MULTIPLE_CHOICE}) | MATCHING_TYPES


def group_options(group: QuestionGroup) -> list[str]:
    """The box of options this group's questions are answered from, in the
    order they are lettered. Empty where there is none.

    One accessor for both the tasks that have a box: matching, where the box is
    the whole point, and a completion task printed with a word list, where it
    turns every gap into a letter. They store it under the same key because it
    is the same thing."""
    options = (group.config or {}).get("options")
    return [str(option) for option in options] if isinstance(options, list) else []


def _parse_image_id(stored: object) -> uuid.UUID | None:
    """A stored image id, or None where there isn't a usable one. JSONB holds
    whatever was written, so this has to cope with something that isn't an id
    at all: that reads as "no picture", which is what the author will see and
    can fix."""
    if not stored:
        return None
    try:
        return uuid.UUID(str(stored))
    except ValueError:
        return None


def group_image(group: QuestionGroup) -> uuid.UUID | None:
    """The picture this group's questions are answered on, where it has one.

    Only for the two types that draw one. A picture left in the config of a
    group that has since been renamed to notes is not drawn, and answering
    "which picture is this task on" with it would be answering about a task
    that no longer has one — which is exactly what publishing must not do, or
    a set of notes would be held to a labelling task's requirements."""
    if group.type not in LABELLING_TYPES:
        return None
    return _parse_image_id((group.config or {}).get("image"))


def image_letter_count(group: QuestionGroup) -> int:
    """How many letters are drawn on this group's picture. Zero where there
    are none — including for every type that isn't a labelling one, for the
    same reason :func:`group_image` refuses to answer for them: a count left
    behind by a rename would otherwise turn a set of notes into letters
    nobody can see."""
    if group.type not in LABELLING_TYPES:
        return 0
    count = (group.config or {}).get("image_letters")
    return count if isinstance(count, int) and count > 0 else 0


def letter_count(group: QuestionGroup) -> int:
    """How many letters this group's questions are answered from, or 0 where
    they are answered in words.

    One question, two places it can be answered from, and they are the same
    statement about the group: a box of words printed above the task, or the
    letters drawn on its picture. Unifying them here is what lets grading,
    publishing and the take page each ask once — the alternative was every
    caller knowing which of the two kinds of box it was looking at, and
    getting it wrong for whichever kind arrived second."""
    # A true/false set is answered in words the exam fixes, never in letters,
    # whatever its config happens to hold. Refused here rather than trusted
    # not to happen: a group that somehow acquired an ``options`` list — a
    # rename from matching, a hand-written row, a seed script — would
    # otherwise be graded by set-matching letters against the word "TRUE",
    # and every answer on it would be wrong.
    if group.type in FIXED_CHOICE_TYPES:
        return 0
    return len(group_options(group)) or image_letter_count(group)


def answers_are_letters(group: QuestionGroup) -> bool:
    """Whether this group's questions are answered by picking a letter.

    The type says so for multiple choice and matching. For a completion task
    the BOX says so: "complete the summary using the list of words, A–H" is
    answered in letters, and the same summary without a list is answered in
    words. A map's letters are the same box drawn onto a picture. So this takes
    the group, not its type — the type alone cannot tell you, and grading that
    assumed it could would compare a letter against the words of an option and
    mark every answer wrong."""
    return group.type in LETTERED_TYPES or letter_count(group) > 0


def answers_are_chosen(group: QuestionGroup) -> bool:
    """Whether this group's answers are PICKED from something printed rather
    than written out.

    A wider question than :func:`answers_are_letters`, and a different one.
    That one decides how to grade; this one decides whether asking *what kind
    of wrong* an answer was means anything. There is no spelling in "b", and
    there is none in TRUE either — a candidate choosing between three buttons
    cannot misspell the one they chose, so classifying their mistake would
    invent a reading problem out of a judgement they got wrong.

    Which is why the two are separate: a true/false set is graded as words
    (its key is the word the book prints) and is nonetheless not written."""
    return answers_are_letters(group) or group.type in FIXED_CHOICE_TYPES


def choice_select_count(group: QuestionGroup) -> int:
    """How many letters this group's questions each ask for.

    Defaults to 1 for anything that doesn't say, which covers every group
    written before the setting existed and every group that isn't multiple
    choice — a form gap's count is not a question you can ask."""
    wanted = (group.config or {}).get("answers_per_question")
    return wanted if isinstance(wanted, int) and wanted >= 1 else 1


def question_marks(group: QuestionGroup) -> int:
    """How many marks — and how many of the numbers printed down the side of
    the paper — each question in this group is worth.

    One per answer asked for. "Choose TWO letters" is labelled *Questions 23
    and 24* in a real paper and carries two marks; treating it as one made a
    40-mark test come out short and quietly halved what a candidate earned
    for the harder question."""
    if group.type != QuestionGroupType.MULTIPLE_CHOICE:
        return 1
    return choice_select_count(group)


async def group_config_out(session: AsyncSession, group: QuestionGroup) -> dict:
    """A group's ``config`` as a client reads it: whatever the author stored,
    plus the picture turned into something that can be drawn.

    The id is what's persisted, and the URL and size are derived on every read
    rather than written beside it. A URL stored in JSONB would be a fact about
    which bucket the app was pointing at on the day it was saved — move from
    local disk to R2, or change the public hostname, and every group written
    before the move would keep asking for a picture that isn't there any more.

    The derived keys are read-only by construction: they are added here and
    dropped on the way back in, since :class:`QuestionGroupConfig` doesn't
    declare them and pydantic ignores what it doesn't know.

    A missing blob leaves them off entirely rather than raising. The group still
    says which picture it wants, so nothing is lost by reloading once the bytes
    are back — and a whole part failing to load because one image row went
    missing is a much worse day than a part that loads with a gap in it.

    Resolved for any group carrying an id, not only the two types that draw
    one — which is why this doesn't go through :func:`group_image`, whose
    question is the narrower "what picture is this task answered on". A map
    task renamed to notes keeps its picture in config, and an editor that
    reloaded it as an id with nothing behind it would have no choice but to
    drop it on the next save. Renaming back is meant to find it still there.
    """
    config = dict(group.config or {})
    # The three words a true/false set is answered in. Derived from the type
    # on the way out rather than stored, so there is exactly one place they
    # are written down and no way for the box the candidate reads to disagree
    # with the answers grading compares against. Same shape as matching's box
    # — the options a group's questions are answered from, printed once above
    # the set — which is what lets one component draw both.
    fixed = FIXED_CHOICE_OPTIONS.get(group.type)
    if fixed is not None:
        config["options"] = list(fixed)
    image_id = _parse_image_id((group.config or {}).get("image"))
    if image_id is None:
        return config
    blob = await images_service.get_blob(session, image_id)
    if blob is None:
        return config
    return config | {
        "image_url": await storage.get_storage().url(blob.storage_key),
        "image_width": blob.width,
        "image_height": blob.height,
    }


def _take_question(question: Question, group: QuestionGroup) -> dict:
    """One question as a candidate may see it.

    ``correct_answers`` is not read here, and there is nowhere it could be
    written: every key is named.

    A gap is only its number — the words around it are the group's template. A
    matching item adds its text, and stops there: the options it is answered
    from are printed once above the whole set, so they travel on the group. A
    choice question adds its own options and how many to pick, which comes
    from the group as well — the same place the instruction line comes from,
    and so can't disagree with it. That count used to be read off the answer
    key's size; that made a paper whose instructions said "choose two" quietly
    ask for three wherever the author had marked three, and it took the key's
    size out towards the candidate on every question."""
    if question.config is None:
        return {"id": question.id, "number": question.number}
    take = {
        "id": question.id,
        "number": question.number,
        "prompt": question.config.get("prompt") or "",
    }
    options = question.options
    if options is None:
        return take
    return take | {"options": options, "select_count": choice_select_count(group)}


async def get_take_tree(session: AsyncSession, material_id: uuid.UUID) -> list[dict]:
    """The student-facing render tree (parts -> question_groups ->
    questions). Deliberately a SEPARATE function from ``get_author_tree``:
    this one never reads ``Question.correct_answers`` for its contents, so
    there is no code path here — no flag, no branch — that could leak it."""
    tree: list[dict] = []
    for part in await get_parts(session, material_id):
        groups: list[dict] = []
        for group in await get_question_groups(session, part.id):
            questions = [
                _take_question(question, group)
                for question in await get_questions(session, group.id)
            ]
            groups.append(
                {
                    "id": group.id,
                    "order_index": group.order_index,
                    "type": group.type,
                    "instructions": group.instructions,
                    "word_limit": group.word_limit,
                    "config": await group_config_out(session, group),
                    "questions": questions,
                }
            )
        tree.append(
            {
                "id": part.id,
                "order_index": part.order_index,
                "title": part.title,
                "audio_start_ms": part.audio_start_ms,
                "audio_end_ms": part.audio_end_ms,
                # What a reading part's questions are answered from. NULL on a
                # listening part, whose questions are answered from the
                # recording — so a client can tell which kind of paper it is
                # holding without being told separately.
                "passage": part.passage,
                # Where this part's numbering starts on its own paper. Built
                # field by field here, so a column added to the model reaches
                # the client only by being named: `first_number` was on the
                # row, on the schema and honoured by both walks in the client,
                # and Part 4 still read "Questions 1-10" because this dict did
                # not mention it.
                "first_number": part.first_number,
                "question_groups": groups,
            }
        )
    return tree


# --- Drills: one question group, worked on its own -------------------------
#
# A drill is one group cut out of its material: the map from Part 2 without the
# four multiple-choice questions printed beside it. It exists because a map
# group is never alone — all 23 in the corpus sit beside another task — so
# "practise only maps" cannot be answered by choosing better materials.

#: The floor on how much recording comes before the group's first answer. The
#: spoken lead-in ("Now look at the plan of the garden centre...") is what tells
#: a learner what they are looking at, and it sits in the gap between the
#: previous group's last answer and this group's first. Measured over the
#: corpus that gap is 0s at its narrowest, so without a floor a drill can open
#: on its own first answer.
DRILL_LEAD_MIN_MS = 8_000
#: And the ceiling on it. The same gap runs to 103s at its widest, most of
#: which is "You now have thirty seconds to check your answers" and dead air
#: rather than lead-in. Because the lead-in sits at the END of the gap, capping
#: from the front takes the last 45 seconds of it — which is the part that is
#: actually lead-in.
DRILL_LEAD_MAX_MS = 45_000
#: One sentence past the last answer, so the clip does not stop on the word.
DRILL_TAIL_MS = 5_000


def _answer_spans(question: Question) -> list[tuple[int, int]]:
    """Every stretch of recording this question is answered in.

    Both sources, because a multiple-choice question keeps its per-option
    spans in ``config["option_replay"]`` rather than in the columns. In this
    corpus the columns happen to bound the options exactly, for all 520 of
    them — but that is a fact about how the seed pipeline writes them, not a
    rule the editor enforces, and a clip computed from the columns alone would
    be silently short the day one of them is edited on its own.
    """
    spans: list[tuple[int, int]] = []
    if question.replay_start_ms is not None and question.replay_end_ms is not None:
        spans.append((question.replay_start_ms, question.replay_end_ms))
    spans.extend(question.option_replay.values())
    return spans


async def _group_spans(
    session: AsyncSession, group: QuestionGroup
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for question in await get_questions(session, group.id):
        spans.extend(_answer_spans(question))
    return spans


async def group_clip(
    session: AsyncSession, group: QuestionGroup, duration_ms: int | None = None
) -> dict | None:
    """The stretch of recording a drill of this group plays, or ``None`` where
    the group is not drillable.

    Derived rather than stored: ``parts.audio_start_ms``/``audio_end_ms`` are
    NULL throughout, and a group has no span column at all. What it is derived
    FROM is the per-question replay marks — which is why this runs on the
    server and only the envelope crosses the wire. Those marks are withheld
    from the take tree on purpose (``app/models/question.py``: "knowing where
    to listen is most of the question"), and that rule is not relaxed here: the
    envelope bounds a couple of minutes the learner is about to hear in full,
    and says nothing about where inside it any one answer falls. It is the same
    thing the printed paper says by heading the task "Questions 15-20".

    The start is the PREVIOUS group's last answer, not this group's first. The
    lead-in lives in between, and a learner who does not hear it is looking at
    a map with no idea what it is of. Clamped at both ends by
    :data:`DRILL_LEAD_MIN_MS` and :data:`DRILL_LEAD_MAX_MS`.

    ``None`` when any question in the group has no mark at all. Not "clip to
    what we have": a clip that stops before question 4 is a drill that cannot
    be answered, and a silent partial is worse than an absence — the learner
    would use it to decide what they missed.
    """
    questions = await get_questions(session, group.id)
    if not questions:
        return None
    spans: list[tuple[int, int]] = []
    for question in questions:
        own = _answer_spans(question)
        if not own:
            return None
        spans.extend(own)

    first = min(start for start, _ in spans)
    last = max(end for _, end in spans)

    # The previous group in the same part, if there is one. A group that opens
    # its part has nothing before it to run into, so ``prev_end`` stays 0 and
    # the MAX cap decides — the clip opens 45s before the first answer rather
    # than at the top of the file. That is deliberate: the head of a Listening
    # recording is exam preamble ("You will hear a man talking about...
    # First you have some time to look at questions 11 to 16"), which is
    # boilerplate a drill does not need. Only 3 of 470 clips reach 0.
    previous = [
        other
        for other in await get_question_groups(session, group.part_id)
        if other.order_index < group.order_index
    ]
    prev_end = 0
    if previous:
        earlier = await _group_spans(session, previous[-1])
        prev_end = max((end for _, end in earlier), default=0)

    start = max(0, min(max(prev_end, first - DRILL_LEAD_MAX_MS), first - DRILL_LEAD_MIN_MS))
    end = last + DRILL_TAIL_MS
    if duration_ms is not None:
        # A stop armed past the end of the file is a stop the clock never
        # reaches, so the clip would run to the end of the recording.
        end = min(end, duration_ms)
    return {"start_ms": start, "end_ms": end}


def part_number(part: Part | None) -> int:
    """Which of the paper's four parts this is.

    From ``first_number`` where there is one, because that is the only field
    that carries the truth for a seeded material: the importer writes one part
    per material at ``order_index`` 0 whatever part it really is, so a Part 2
    and a Part 4 are both index 0. ``first_number`` 11 is Part 2, 31 is Part 4
    — ten numbers per part, which is what the paper does.

    Falls back to the index for an author-written part, where the editor's
    ``Part {order_index + 1}`` titling does make the index carry the number.
    """
    if part is None:
        return 1
    if part.first_number is not None:
        return (part.first_number - 1) // 10 + 1
    return part.order_index + 1


async def group_first_number(
    session: AsyncSession, group: QuestionGroup
) -> int:
    """The number this group's first question carries on the printed paper.

    Its part's starting number plus the marks of every group before it — so
    the map that follows four multiple-choice questions in a Part 2 numbered
    from 11 begins at 15. Marks, not rows: a "Choose TWO letters" before it
    took two of the numbers.

    One definition, because two things need the answer and they must agree —
    the drill tree (so the paper reads 15-20) and the drill card (so the list
    says "Questions 15-20" about the same drill).
    """
    part = await session.get(Part, group.part_id)
    first = part.first_number if part and part.first_number is not None else 1
    for other in await get_question_groups(session, group.part_id):
        if other.order_index >= group.order_index:
            break
        first += len(await get_questions(session, other.id)) * question_marks(other)
    return first


async def get_drill_tree(session: AsyncSession, group: QuestionGroup) -> list[dict]:
    """The student-facing render tree for ONE group.

    A third sibling to :func:`get_take_tree` and :func:`get_author_tree`, and
    separate from both for the reason the first one gives: it never reads
    ``Question.correct_answers``, so there is no code path here — no flag, no
    branch — that could leak it. It reuses ``_take_question`` and
    ``group_config_out``, the two helpers that already never touch the answer
    key and already resolve ``config["image"]`` into a URL, which is what makes
    a map drill draw its own picture with no new code.

    One synthetic part, carrying the number the GROUP starts at on the paper
    rather than the part's. The map in Part 2 is Questions 15-20, and the
    recording says so aloud — the same bug ``parts.first_number`` was added to
    fix, one level down. Working it out here means the client's existing walk
    (``numbering.ts``) prints 15-20 with no change to it at all.

    ``audio_start_ms``/``audio_end_ms`` stay NULL. They mean "this part is a
    stretch of a longer recording", which draws a part strip and a per-part
    play button; a drill's bound on the recording is its clip, which is a
    different thing and travels separately.
    """
    part = await session.get(Part, group.part_id)
    first_number = await group_first_number(session, group)

    questions = [
        _take_question(question, group)
        for question in await get_questions(session, group.id)
    ]
    return [
        {
            "id": part.id if part else group.part_id,
            "order_index": part.order_index if part else 0,
            "title": part.title if part else "",
            "audio_start_ms": None,
            "audio_end_ms": None,
            # The passage, which is the whole of what a READING drill is
            # answered from. A listening drill carries a clip instead, and
            # that travels separately; this is on the part itself, so a drill
            # cut from a reading paper without it is a question paper with no
            # text beside it -- unanswerable, and silently so.
            "passage": part.passage if part else None,
            "first_number": first_number,
            "question_groups": [
                {
                    "id": group.id,
                    "order_index": 0,
                    "type": group.type,
                    "instructions": group.instructions,
                    "word_limit": group.word_limit,
                    "config": await group_config_out(session, group),
                    "questions": questions,
                }
            ],
        }
    ]


# --- Author read tree ------------------------------------------------------


async def get_author_tree(
    session: AsyncSession, material_id: uuid.UUID, *, include_answers: bool
) -> list[dict]:
    """The full authoring tree (parts -> question_groups -> questions) for a
    material, ordered by ``order_index``/``number``. ``correct_answers`` is
    included in each question dict ONLY when ``include_answers`` is true —
    callers (the API layer) must gate this on ``material.author_id ==
    caller.id`` so a non-owner viewing a public material never sees answers
    (§3.4 applies to every read path, not just /take)."""
    tree: list[dict] = []
    for part in await get_parts(session, material_id):
        groups: list[dict] = []
        for group in await get_question_groups(session, part.id):
            questions: list[dict] = []
            for question in await get_questions(session, group.id):
                q: dict = {
                    "id": question.id,
                    "number": question.number,
                    # Where the answer is said. Author-facing only — this tree
                    # is gated on ownership by the caller, and the take tree
                    # (get_take_tree) is a separate function that never sees
                    # these. Left out here, reopening a material lost every
                    # mark, and the next autosave wrote the loss back.
                    "replay_start_ms": question.replay_start_ms,
                    "replay_end_ms": question.replay_end_ms,
                }
                if question.config is not None:
                    # The question's own presentation, flattened out of config
                    # so the editor reads the same field names it sends back.
                    q["prompt"] = question.config.get("prompt") or ""
                    options = question.options
                    if options is not None:
                        # Multiple choice only. A matching item would answer
                        # with an empty list here, which reads as "a question
                        # whose options were deleted" rather than as "a
                        # question whose options are its group's".
                        q["options"] = options
                        q["option_replay"] = (
                            question.config.get("option_replay") or {}
                        )
                if include_answers:
                    q["correct_answers"] = question.correct_answers
                questions.append(q)
            groups.append(
                {
                    "id": group.id,
                    "order_index": group.order_index,
                    "type": group.type,
                    "instructions": group.instructions,
                    "word_limit": group.word_limit,
                    "config": await group_config_out(session, group),
                    "questions": questions,
                }
            )
        tree.append(
            {
                "id": part.id,
                "order_index": part.order_index,
                "title": part.title,
                "audio_start_ms": part.audio_start_ms,
                "audio_end_ms": part.audio_end_ms,
                # What a reading part's questions are answered from. NULL on a
                # listening part, whose questions are answered from the
                # recording — so a client can tell which kind of paper it is
                # holding without being told separately.
                "passage": part.passage,
                # The author's tree needs it for the same reason the
                # student's does: the studio prints the numbers beside the
                # questions, and two trees that disagree about question 27
                # are worse than either being wrong on its own.
                "first_number": part.first_number,
                "question_groups": groups,
            }
        )
    return tree


# --- The learner's catalogue (brief §33) ------------------------------------


#: How many rows one page of the catalogue holds, and the most a caller may
#: ask for. Thirty is about three screens of list — enough that the first
#: fetch fills the page and the second is prefetched before anybody reaches
#: the bottom, small enough that a filter change is not a fresh half-megabyte.
CATALOGUE_PAGE = 30
CATALOGUE_MAX_PAGE = 100

#: Where each band sits when the list is ordered by difficulty. ``new`` is
#: last in BOTH directions, and that is the point of two tables rather than
#: one reversed: a material nobody has answered enough of has no place on the
#: scale, so it can be neither the easiest nor the hardest thing on the page.
#: The frontend has the same two tables for the same reason; they are two
#: implementations of one rule, and the tests pin the SQL one.
_EASIEST_FIRST = {"easy": 0, "medium": 1, "hard": 2, "new": 3}
_HARDEST_FIRST = {"hard": 0, "medium": 1, "easy": 2, "new": 3}

#: How many parts make a whole paper; anything less is an excerpt from one.
#: The same constant the frontend calls FULL_TEST_PARTS.
#:
#: Four for listening and three for reading, because that is what the two
#: papers are: forty questions over four recordings, or forty over three
#: passages. One number for both would have called every complete reading
#: paper an excerpt, which is the one thing the "full test" filter exists to
#: tell apart.
FULL_TEST_PARTS = 4
_FULL_PARTS = {"listening": 4, "reading": 3}


def full_test_parts(skill: str) -> int:
    """How many parts a whole paper of this skill has."""
    return _FULL_PARTS.get(skill, FULL_TEST_PARTS)


def _band_of():
    """A material's band as SQL sees it.

    ``COALESCE`` and not a plain column read: a material created since the
    last refresh has no projection row, and a LEFT JOIN gives NULL where the
    honest answer is ``new``. Without this, filtering by New would silently
    drop exactly the materials that most deserve to be in it.

    The default is a literal rather than a bound parameter because this
    expression is both selected and grouped by, and Postgres matches a GROUP
    BY to a SELECT expression by comparing them — two placeholders holding
    the same string are not the same expression to it, and the query is
    rejected.
    """
    return func.coalesce(MaterialDifficulty.band, literal_column("'new'"))


def _catalogue_where(
    user_id: uuid.UUID,
    *,
    skill: str,
    query: str,
    scope: str,
    types: list[str],
    bands: list[str],
    done: bool,
) -> list:
    """Everything the controls above the list mean, as SQL.

    This used to be a function in the browser over the whole catalogue, which
    worked precisely because the whole catalogue was in the browser. It is
    here now because the list is paginated, and a filter applied to the page
    rather than to the query filters thirty rows out of a thousand.

    Each clause is an EXISTS rather than a join, deliberately: a material with
    two parts and three groups would otherwise come back twice and be counted
    twice, and every one of these asks "is there one" rather than "which".
    """
    where = [
        Material.type == skill,
        Material.visibility == "public",
    ]

    if scope == "full":
        where.append(
            select(func.count(Part.id))
            .where(Part.material_id == Material.id)
            .scalar_subquery()
            >= full_test_parts(skill)
        )
    elif scope.isdigit():
        # A part chip matches a material that HOLDS that part, whole paper
        # included: somebody practising their weakest section wants material
        # with that part in it, not material that is only that part. The
        # editor titles a part `Part {order_index + 1}`, so the index carries
        # the number.
        where.append(
            select(Part.id)
            .where(
                Part.material_id == Material.id,
                Part.order_index == int(scope) - 1,
            )
            .exists()
        )

    if types:
        where.append(
            select(QuestionGroup.id)
            .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
            .where(
                Part.material_id == Material.id,
                QuestionGroup.type.in_(types),  # type: ignore[attr-defined]
            )
            .exists()
        )

    if bands:
        where.append(_band_of().in_(bands))

    if not done:
        # Materials the caller has already sat are put away by default: the
        # list answers "what shall I practise next", and a paper they have
        # finished is the least likely answer on it. Started-and-abandoned
        # does not count — only a submitted attempt is having done something.
        where.append(
            ~select(Attempt.id)
            .where(
                Attempt.material_id == Material.id,
                Attempt.user_id == user_id,
                Attempt.status == AttemptStatus.SUBMITTED,
            )
            .exists()
        )

    # Title, author, and the name of a collection the material is in. The
    # client-side version also matched question-type labels and "Part 3",
    # which were free when every row was already in hand; in SQL they would
    # be a subquery per term to search for something the chips above the
    # field select exactly. Every term must hit (AND, not OR), so "nodira
    # park" narrows rather than widens.
    #
    # The collection is in because the book's name is ONLY there. A seeded
    # material is titled "Why we need silence -- C21 T1 P2": the code says
    # which test, and the thirty characters of "Cambridge IELTS 21" live once
    # on the course rather than sixteen times on its materials
    # (`scripts/import_section.py` says so where it builds the title). The
    # cost of that was a search for "Cambridge 21" finding nothing at all,
    # which is the first thing somebody types.
    for term in query.split():
        where.append(
            _hit(Material.title, term)
            | select(User.id)
            .where(
                User.id == Material.author_id,
                _hit(User.display_name, term),
            )
            .exists()
            | select(CollectionItem.material_id)
            .where(
                CollectionItem.material_id == Material.id,
                CollectionItem.collection_id == Collection.id,
                Collection.visibility == "public",
                _hit(Collection.title, term),
            )
            .exists()
        )

    return where


def _hit(column, term: str):
    """One search term against one piece of text -- as a WORD if it is a number.

    Everything else is a substring match, which is what this search should
    be: "silence" finds "Why we need silence" and "sail" finds the Cutty
    Sark. But a bare number is a substring of every code on the shelf, and
    the codes are made of numbers. "C21 T1 Part 2" came back with all FOUR of
    that test's parts, because the "2" the reader typed to mean part two also
    sits inside "C21" -- so the one search a learner actually performs, the
    one that names the paper they want, could not narrow to it.

    A word boundary fixes exactly that and nothing else: `2` matches "Part 2"
    and not "C21", while `C21`, `T1` and `P2` stay substrings, which is what
    makes them typeable without the separators the title prints.

    Every field it is matched against, not only the title. The collection's
    name was added here to make "Cambridge 21" find something, and with a
    plain LIKE it quietly handed the number back its old behaviour: "2" hit
    "Cambridge IELTS 21" and all four parts came back again, through a
    different door.
    """
    if term.isdigit():
        return column.op("~*")(rf"\m{term}\M")
    return func.lower(column).like(f"%{term.lower()}%")


def _catalogue_order(sort: str) -> list:
    """The chosen order, with a tiebreaker that makes paging honest.

    Every order ends in ``created_at DESC, id``: two materials with the same
    band sort in a defined order, so row thirty of page one is not also row
    one of page two. Without the final ``id`` two rows written in the same
    transaction could swap places between two requests, which is a row the
    reader sees twice and one they never see.
    """
    tail = [Material.created_at.desc(), Material.id]  # type: ignore[attr-defined]
    if sort == "easiest":
        return [_band_case(_EASIEST_FIRST), *tail]
    if sort == "hardest":
        return [_band_case(_HARDEST_FIRST), *tail]
    if sort == "shortest":
        # NULLS LAST: a material with no recording has no length, so it sorts
        # last rather than first — an unknown duration is not a duration of
        # zero.
        return [AudioBlob.duration_ms.asc().nulls_last(), *tail]  # type: ignore[attr-defined]
    return tail


def _band_case(ranks: dict[str, int]):
    band = _band_of()
    return case(*[(band == name, rank) for name, rank in ranks.items()], else_=99)


async def _catalogue_facets(session: AsyncSession, *, skill: str) -> dict:
    """What there is to filter BY, counted over the WHOLE catalogue.

    Not over what is currently showing, and not over the current page. An
    option that appears and vanishes as you filter is an option you cannot
    aim at, and a count that only described the thirty rows in hand would be
    a number nobody could act on. Two grouped queries for the whole library,
    which is why they are cheap enough to run on every request.
    """
    public = [Material.type == skill, Material.visibility == "public"]

    types = [
        {"value": group_type, "count": int(count)}
        for group_type, count in (
            await session.exec(
                select(QuestionGroup.type, func.count(distinct(Part.material_id)))
                .select_from(QuestionGroup)
                .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
                .join(Material, Material.id == Part.material_id)  # type: ignore[arg-type]
                .where(*public)
                .group_by(QuestionGroup.type)  # type: ignore[arg-type]
            )
        ).all()
    ]

    bands = [
        {"value": band, "count": int(count)}
        for band, count in (
            await session.exec(
                select(_band_of(), func.count(Material.id))
                .select_from(Material)
                .outerjoin(
                    MaterialDifficulty,
                    MaterialDifficulty.material_id == Material.id,  # type: ignore[arg-type]
                )
                .where(*public)
                .group_by(_band_of())  # type: ignore[arg-type]
            )
        ).all()
    ]

    return {"types": types, "bands": bands}


async def practice_catalogue(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    skill: str,
    query: str = "",
    scope: str = "all",
    types: list[str] | None = None,
    bands: list[str] | None = None,
    done: bool = False,
    sort: str = "newest",
    limit: int = CATALOGUE_PAGE,
    offset: int = 0,
) -> dict:
    """One page of what a learner can sit, and what they have done with it.

    Public ones only. An author's unfinished drafts are reachable from the
    Studio, which is where unfinished work belongs; listing them here put
    "untitled listening — private" in front of the person who came to
    practise, next to a button that opens a paper with no questions on it.

    **Filtered, ordered and paged in the database.** It used to return the
    whole catalogue and let the browser do all three, which was right while
    the whole catalogue was fifteen rows and stops being right somewhere
    around a hundred: at a thousand it is half a megabyte of JSON, a thousand
    rows of DOM, and a difficulty aggregate over every answer on the platform,
    to show somebody thirty titles.

    What comes back is a page plus the two things a page cannot say about
    itself — how many there are in total, and what there is to filter by (see
    :func:`_catalogue_facets`) — plus ``done_hidden``, because a list quietly
    shorter than the reader knows the library to be is a list that looks
    broken.

    Ordered newest-first by ``created_at`` and not by ``updated_at``, which is
    what the list header claims and what a learner means. ``updated_at`` moves
    every time the author fixes a typo, so a year-old paper could sit at the
    top of "Newest first" for having been touched this morning.
    """
    limit = max(1, min(limit, CATALOGUE_MAX_PAGE))
    offset = max(0, offset)
    where = _catalogue_where(
        user_id,
        skill=skill,
        query=query,
        scope=scope,
        types=types or [],
        bands=bands or [],
        done=done,
    )

    # One base shape for the count and the page, so the two can never come to
    # disagree about what the filters mean. The joins are all one-to-(zero or
    # one) — the difficulty projection, the recording — so nothing here
    # multiplies rows and the count needs no DISTINCT.
    def base(statement):
        return statement.select_from(Material).outerjoin(
            MaterialDifficulty,
            MaterialDifficulty.material_id == Material.id,  # type: ignore[arg-type]
        )

    total = int(
        (await session.exec(base(select(func.count(Material.id))).where(*where))).one()
    )

    page = base(select(Material))
    if sort == "shortest":
        # Only where it is being ordered by: two more joins on every request
        # to sort by a column three of the four orders never look at.
        page = page.outerjoin(
            AudioAsset,
            AudioAsset.id == Material.audio_asset_id,  # type: ignore[arg-type]
        ).outerjoin(AudioBlob, AudioBlob.id == AudioAsset.blob_id)  # type: ignore[arg-type]

    materials = list(
        (
            await session.exec(
                page.where(*where)
                .order_by(*_catalogue_order(sort))
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )

    # How many the default is holding back, over and above whatever the chips
    # are doing: the same filters with that one switch flipped the other way.
    # Zero the moment the reader asks to see them, which is what makes the
    # line above the list disappear rather than say "0 done".
    done_hidden = 0
    if not done:
        done_where = _catalogue_where(
            user_id,
            skill=skill,
            query=query,
            scope=scope,
            types=types or [],
            bands=bands or [],
            done=True,
        )
        done_where.append(
            select(Attempt.id)
            .where(
                Attempt.material_id == Material.id,
                Attempt.user_id == user_id,
                Attempt.status == AttemptStatus.SUBMITTED,
            )
            .exists()
        )
        done_hidden = int(
            (
                await session.exec(
                    base(select(func.count(Material.id))).where(*done_where)
                )
            ).one()
        )

    return {
        "items": await _catalogue_rows(session, user_id, materials, skill=skill),
        "total": total,
        "done_hidden": done_hidden,
        **await _catalogue_facets(session, skill=skill),
    }


async def recommended(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    skill: str,
    part: int | None,
    ranks: dict[str, int],
    size: int,
    skip: set[uuid.UUID] | None = None,
    prefer_full: bool = False,
) -> list[dict]:
    """A handful of materials to put in front of one learner.

    The same rows as the catalogue, chosen by a different question. Two
    filters and an order, and nothing else is worth the machinery: it must be
    something they have NOT sat — recommending a paper somebody finished last
    week is the page not paying attention — optionally from one part, and
    ordered so the level that suits them comes first (``ranks``, from
    :mod:`app.services.recommend`, which is where every judgement about WHO
    this is for lives).

    ``skip`` is what the collections add to this: materials waiting their turn
    inside a course the learner has started. Offering lesson five to somebody
    on lesson three denies the one thing a collection claims — that its order
    is somebody's judgement about what to do when.

    ``prefer_full`` puts whole papers first. It is for the one reader the
    ladder has nothing else to offer — level across all four parts, so there
    is no weak one to send them to — and a whole paper is the next thing after
    excerpts however good you are at the excerpts.

    Ties inside a band break newest-first, so the block changes as the library
    grows rather than recommending the same three things forever.
    """
    where = [
        Material.type == skill,
        Material.visibility == "public",
        ~select(Attempt.id)
        .where(
            Attempt.material_id == Material.id,
            Attempt.user_id == user_id,
            Attempt.status == AttemptStatus.SUBMITTED,
        )
        .exists(),
        # Nothing empty. A material with no questions is not practice, and it
        # is the one thing a recommendation must not be: the page choosing,
        # on the learner's behalf, to waste their evening.
        select(Question.id)
        .join(QuestionGroup, QuestionGroup.id == Question.group_id)  # type: ignore[arg-type]
        .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
        .where(Part.material_id == Material.id)
        .exists(),
    ]
    if part is not None:
        where.append(
            select(Part.id)
            .where(Part.material_id == Material.id, Part.order_index == part - 1)
            .exists()
        )
    if skip:
        where.append(Material.id.not_in(skip))  # type: ignore[attr-defined]

    materials = list(
        (
            await session.exec(
                select(Material)
                .select_from(Material)
                .outerjoin(
                    MaterialDifficulty,
                    MaterialDifficulty.material_id == Material.id,  # type: ignore[arg-type]
                )
                .where(*where)
                .order_by(
                    *(
                        [
                            case(
                                (
                                    select(func.count(Part.id))
                                    .where(Part.material_id == Material.id)
                                    .scalar_subquery()
                                    >= full_test_parts(skill),
                                    0,
                                ),
                                else_=1,
                            )
                        ]
                        if prefer_full
                        else []
                    ),
                    _band_case(ranks),
                    Material.created_at.desc(),  # type: ignore[attr-defined]
                    Material.id,
                )
                .limit(size)
            )
        ).all()
    )
    return await _catalogue_rows(session, user_id, materials, skill=skill)


async def materials_in_order(
    session: AsyncSession, ids: list[uuid.UUID]
) -> list[Material]:
    """The named materials, in the order they were named.

    SQL has no opinion about the order of an ``IN`` list, and here the order
    IS the content — a collection is a sequence somebody laid out on purpose.
    Sorted in Python against the ids rather than with a CASE expression
    because the list is a course, not a catalogue: ten rows, not ten thousand.
    """
    if not ids:
        return []
    found = {
        m.id: m
        for m in (
            await session.exec(
                select(Material).where(Material.id.in_(ids))  # type: ignore[attr-defined]
            )
        ).all()
    }
    return [found[i] for i in ids if i in found]


async def _catalogue_rows(
    session: AsyncSession,
    user_id: uuid.UUID,
    materials: list[Material],
    *,
    skill: str,
) -> list[dict]:
    """Everything a row prints, for one page of materials.

    Flat queries rather than a walk per material — the same rule as before,
    and it matters less than it did now that the page is thirty rows rather
    than the library. What it costs is a fixed handful of queries whatever the
    catalogue grows to, which is the whole point of paginating.
    """
    if not materials:
        return []

    ids = [m.id for m in materials]

    # Which parts, not how many. "Part 2" is the single most useful thing on
    # a row — it is what a candidate practising their weakest section filters
    # by — and a count can't say it: a material with one part is Part 1 or
    # Part 4 depending on the index it was seeded at (the editor titles a part
    # ``Part {order_index + 1}``, so the index carries the number even when
    # there is only one).
    part_numbers: dict[uuid.UUID, list[int]] = {}
    for material_id, order_index in (
        await session.exec(
            select(Part.material_id, Part.order_index)
            .where(Part.material_id.in_(ids))  # type: ignore[attr-defined]
            .order_by(Part.material_id, Part.order_index)  # type: ignore[arg-type]
        )
    ).all():
        part_numbers.setdefault(material_id, []).append(int(order_index) + 1)

    # The kinds of question each material asks, in the order they are asked
    # and without repeating one. A row names its type where there is one to
    # name; a material that mixes them says so instead of being labelled
    # after whichever came first.
    types_by_material: dict[uuid.UUID, list[str]] = {}
    for material_id, group_type in (
        await session.exec(
            select(Part.material_id, QuestionGroup.type)
            .select_from(QuestionGroup)
            .join(Part, Part.id == QuestionGroup.part_id)  # type: ignore[arg-type]
            .where(Part.material_id.in_(ids))  # type: ignore[attr-defined]
            .order_by(Part.material_id, Part.order_index, QuestionGroup.order_index)  # type: ignore[arg-type]
        )
    ).all():
        seen = types_by_material.setdefault(material_id, [])
        if group_type not in seen:
            seen.append(group_type)

    # Who wrote it. Public material is somebody's work with their name on it,
    # and the name is also how a learner comes to follow an author whose
    # papers suit them. One query for every author at once.
    author_ids = {m.author_id for m in materials}
    authors = {
        user.id: user
        for user in (
            await session.exec(
                select(User).where(User.id.in_(author_ids))  # type: ignore[attr-defined]
            )
        ).all()
    }

    # What else each of them has written, and how much of it the caller has
    # sat. Over the whole library rather than over this page — the byline
    # opens into these two numbers on hover, and "4 materials" counted from
    # the thirty rows in hand would be wrong every time it wasn't one.
    written_by: dict[uuid.UUID, int] = {
        author_id: int(count)
        for author_id, count in (
            await session.exec(
                select(Material.author_id, func.count(Material.id))
                .where(
                    Material.author_id.in_(author_ids),  # type: ignore[attr-defined]
                    Material.type == skill,
                    Material.visibility == "public",
                )
                .group_by(Material.author_id)  # type: ignore[arg-type]
            )
        ).all()
    }
    sat_by_author: dict[uuid.UUID, int] = {
        author_id: int(count)
        for author_id, count in (
            await session.exec(
                select(Material.author_id, func.count(distinct(Material.id)))
                .select_from(Material)
                .join(Attempt, Attempt.material_id == Material.id)  # type: ignore[arg-type]
                .where(
                    Material.author_id.in_(author_ids),  # type: ignore[attr-defined]
                    Material.type == skill,
                    Material.visibility == "public",
                    Attempt.user_id == user_id,
                    Attempt.status == AttemptStatus.SUBMITTED,
                )
                .group_by(Material.author_id)  # type: ignore[arg-type]
            )
        ).all()
    }

    # Marks, not rows — the number a score is out of. A "choose TWO letters"
    # is one row and two of the numbers printed down the side, and a
    # catalogue that advertised "39 questions" for a test marked out of 40
    # would be wrong in the one figure anybody reads.
    marks_by_material: dict[uuid.UUID, int] = {}
    for material_id, group, count in (
        await session.exec(
            select(Part.material_id, QuestionGroup, func.count(Question.id))
            .join(QuestionGroup, QuestionGroup.part_id == Part.id)  # type: ignore[arg-type]
            .outerjoin(Question, Question.group_id == QuestionGroup.id)  # type: ignore[arg-type]
            .where(Part.material_id.in_(ids))  # type: ignore[attr-defined]
            .group_by(Part.material_id, QuestionGroup.id)  # type: ignore[arg-type]
        )
    ).all():
        marks_by_material[material_id] = marks_by_material.get(
            material_id, 0
        ) + count * question_marks(group)

    # The caller's own history, and nobody else's. Ordered so the last one
    # read wins, which is how each material ends up holding its most recent
    # attempt without a window function.
    history: dict[uuid.UUID, dict] = {}
    for attempt in (
        await session.exec(
            select(Attempt)
            .where(
                Attempt.user_id == user_id,
                Attempt.material_id.in_(ids),  # type: ignore[attr-defined]
                Attempt.status == AttemptStatus.SUBMITTED,
            )
            .order_by(Attempt.submitted_at)  # type: ignore[arg-type]
        )
    ).all():
        row = history.setdefault(
            attempt.material_id,
            {"attempts": 0, "best_score": None, "first_score": None},
        )
        row["attempts"] += 1
        score = int(attempt.score or 0)
        row["best_score"] = (
            score if row["best_score"] is None else max(row["best_score"], score)
        )
        # The first one, kept alongside the best. The row prints the best —
        # it is somebody's record and the record is their best — but anything
        # that MEASURES them reads the first, and the collection page's result
        # map is one of those. Attempts arrive oldest-first, so the first is
        # simply whichever got here before this one.
        if row["first_score"] is None:
            row["first_score"] = score
        row["last_attempt_id"] = attempt.id
        row["last_attempt_at"] = attempt.submitted_at

    audio_by_material = await _catalogue_audio(session, materials)

    # How hard each one turned out to be, over everybody's answers. Read from
    # the projection the worker refills — see app/services/difficulty.py for
    # why that is a cache and not a column.
    difficulty_by_material = await difficulty_service.material_difficulty(session, ids)

    rows = []
    for m in materials:
        author = authors.get(m.author_id)
        parts = part_numbers.get(m.id, [])
        rows.append(
            {
                "id": m.id,
                "title": m.title,
                "part_count": len(parts),
                "part_numbers": parts,
                "question_types": types_by_material.get(m.id, []),
                "question_count": marks_by_material.get(m.id, 0),
                "duration_ms": audio_by_material.get(m.id),
                "created_at": m.created_at,
                "author": (
                    {
                        "id": author.id,
                        "display_name": author.display_name,
                        "avatar_url": author.avatar_url,
                        "materials": written_by.get(author.id, 0),
                        "done": sat_by_author.get(author.id, 0),
                    }
                    if author is not None
                    else None
                ),
                "difficulty": difficulty_by_material.get(
                    m.id, difficulty_service.unknown()
                ),
                "attempts": 0,
                "best_score": None,
                "first_score": None,
                "last_attempt_id": None,
                "last_attempt_at": None,
                **history.get(m.id, {}),
            }
        )
    return rows


async def _catalogue_audio(
    session: AsyncSession, materials: list[Material]
) -> dict[uuid.UUID, int | None]:
    """How long each material's recording runs, by material id.

    The duration only — no URL. A catalogue that resolved a playable link per
    row would be handing out signed URLs for recordings nobody has opened
    yet, and the number is the only part a learner reads before deciding.
    """
    asset_ids = [m.audio_asset_id for m in materials if m.audio_asset_id]
    if not asset_ids:
        return {}
    durations = {
        asset_id: duration
        for asset_id, duration in (
            await session.exec(
                select(AudioAsset.id, AudioBlob.duration_ms)
                .join(AudioBlob, AudioBlob.id == AudioAsset.blob_id)  # type: ignore[arg-type]
                .where(AudioAsset.id.in_(asset_ids))  # type: ignore[attr-defined]
            )
        ).all()
    }
    return {
        m.id: durations.get(m.audio_asset_id)
        for m in materials
        if m.audio_asset_id
    }
