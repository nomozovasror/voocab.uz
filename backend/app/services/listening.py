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
from app.models.audio_blob import AudioBlob
from app.models.material import Material
from app.models.material_difficulty import MaterialDifficulty
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import (
    LABELLING_TYPES,
    QuestionGroup,
    QuestionGroupType,
    same_question_kind,
)
from app.models.user import User
from app.schemas.listening import (
    ChoiceQuestionIn,
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
    )
    session.add(part)
    await session.commit()
    await session.refresh(part)
    return part


async def update_part(session: AsyncSession, part: Part, data: PartUpdate) -> Part:
    """Partial update (title / audio range).

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
    if isinstance(question, MatchingQuestionIn):
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
    await _remove_questions(session, await get_questions(session, group.id))
    await session.flush()
    await session.delete(group)
    await session.commit()


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
LETTERED_TYPES = frozenset(
    {QuestionGroupType.MULTIPLE_CHOICE, QuestionGroupType.MATCHING}
)


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
                "question_groups": groups,
            }
        )
    return tree


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

#: Four parts is a whole paper; anything less is an excerpt from one. The same
#: constant the frontend calls FULL_TEST_PARTS.
FULL_TEST_PARTS = 4


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
        Material.type == "listening",
        Material.visibility == "public",
    ]

    if scope == "full":
        where.append(
            select(func.count(Part.id))
            .where(Part.material_id == Material.id)
            .scalar_subquery()
            >= FULL_TEST_PARTS
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

    # Title and author, and nothing else. The client-side version also matched
    # question-type labels and "Part 3", which were free when every row was
    # already in hand; in SQL they would be a subquery per term to search for
    # something the chips above the field select exactly. Every term must hit
    # (AND, not OR), so "nodira park" narrows rather than widens.
    for term in query.split():
        pattern = f"%{term}%"
        where.append(
            func.lower(Material.title).like(pattern.lower())
            | select(User.id)
            .where(
                User.id == Material.author_id,
                func.lower(User.display_name).like(pattern.lower()),
            )
            .exists()
        )

    return where


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


async def _catalogue_facets(session: AsyncSession) -> dict:
    """What there is to filter BY, counted over the WHOLE catalogue.

    Not over what is currently showing, and not over the current page. An
    option that appears and vanishes as you filter is an option you cannot
    aim at, and a count that only described the thirty rows in hand would be
    a number nobody could act on. Two grouped queries for the whole library,
    which is why they are cheap enough to run on every request.
    """
    public = [Material.type == "listening", Material.visibility == "public"]

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
        "items": await _catalogue_rows(session, user_id, materials),
        "total": total,
        "done_hidden": done_hidden,
        **await _catalogue_facets(session),
    }


async def recommended(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    part: int | None,
    ranks: dict[str, int],
    size: int,
) -> list[dict]:
    """A handful of materials to put in front of one learner.

    The same rows as the catalogue, chosen by a different question. Two
    filters and an order, and nothing else is worth the machinery: it must be
    something they have NOT sat — recommending a paper somebody finished last
    week is the page not paying attention — optionally from one part, and
    ordered so the level that suits them comes first (``ranks``, from
    :mod:`app.services.recommend`, which is where every judgement about WHO
    this is for lives).

    Ties inside a band break newest-first, so the block changes as the library
    grows rather than recommending the same three things forever.
    """
    where = [
        Material.type == "listening",
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
                    _band_case(ranks),
                    Material.created_at.desc(),  # type: ignore[attr-defined]
                    Material.id,
                )
                .limit(size)
            )
        ).all()
    )
    return await _catalogue_rows(session, user_id, materials)


async def _catalogue_rows(
    session: AsyncSession, user_id: uuid.UUID, materials: list[Material]
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
                    Material.type == "listening",
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
                    Material.type == "listening",
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
            attempt.material_id, {"attempts": 0, "best_score": None}
        )
        row["attempts"] += 1
        score = int(attempt.score or 0)
        row["best_score"] = (
            score if row["best_score"] is None else max(row["best_score"], score)
        )
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
