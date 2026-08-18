"""What a material must be before anyone but its author can take it.

The rules live here, on the server, because this is the only place they can
actually hold. The editor checks the same things as it goes — that is what
makes the requirements discoverable while authoring, rather than a wall at
the end — but a check that only runs in a browser is a suggestion: one PATCH
with ``{"visibility": "public"}`` published an empty material, or one with no
recording at all, and the learner met the result.

Two callers, and they are deliberately different:

* going public (``visibility`` moving to ``public``) is refused outright when
  anything is missing, with every reason listed at once;
* a write to a material that is already public re-checks afterwards and, if
  the material no longer qualifies, moves it back to draft. Authors edit
  published work — that is normal — and the alternative to demoting is
  leaving something broken in front of learners.
"""

import uuid

from app.core.database import AsyncSession
from app.models.material import Material
from app.models.question import Question
from app.models.question_group import (
    LABELLING_TYPES,
    QuestionGroup,
    QuestionGroupType,
)
from app.services import listening as listening_service
from app.services import materials as materials_service

#: Titles the editors fill in for an author who hasn't named the material
#: yet. They are placeholders standing in for a title, not titles.
PLACEHOLDER_TITLES = {"untitled", "untitled listening", "untitled dictation"}


async def publish_blockers(session: AsyncSession, material: Material) -> list[str]:
    """Everything standing between this material and being taken by someone
    else, phrased for the author. Empty means it's ready.

    All of them, not the first: an author fixing one thing at a time, with a
    round trip each, is the worst version of this.
    """
    blockers: list[str] = []

    title = material.title.strip()
    if not title:
        blockers.append("Give the material a title.")
    elif title.lower() in PLACEHOLDER_TITLES:
        blockers.append("Give the material a real title, not the placeholder.")

    if material.audio_asset_id is None:
        blockers.append("Attach the audio recording.")

    if material.type == "listening":
        blockers.extend(await _listening_blockers(session, material.id))
    else:
        blockers.extend(await _dictation_blockers(session, material.id))

    return blockers


async def _listening_blockers(
    session: AsyncSession, material_id: uuid.UUID
) -> list[str]:
    parts = await listening_service.get_parts(session, material_id)
    if not parts:
        return ["Add at least one part."]

    blockers: list[str] = []
    # Questions are numbered 1..N inside their own group; what the candidate
    # reads runs across the whole material. These messages use the candidate's
    # numbering, because it is the only one the author can see on the page —
    # and a question can take more than one of those numbers, so what is
    # counted here is numbers, not rows.
    numbered_so_far = 0

    for part in parts:
        label = part.title.strip() or f"Part {part.order_index + 1}"
        groups = await listening_service.get_question_groups(session, part.id)
        if not groups:
            # A part with nothing in it is how a four-part test looks while
            # it is being written, so it isn't an error on its own — the
            # "no questions anywhere" check below is what catches an empty
            # material.
            continue

        for group in groups:
            if not group.instructions.strip():
                blockers.append(f"{label}: add the instructions.")

            questions = await listening_service.get_questions(session, group.id)
            if not questions:
                blockers.append(f"{label}: add at least one question.")

            marks = listening_service.question_marks(group)
            if group.type == QuestionGroupType.MULTIPLE_CHOICE:
                blockers.extend(
                    _choice_blockers(label, questions, numbered_so_far, marks)
                )
            elif group.type == QuestionGroupType.MATCHING:
                blockers.extend(
                    _matching_blockers(label, group, questions, numbered_so_far)
                )
            else:
                blockers.extend(
                    _gap_blockers(label, group, questions, numbered_so_far)
                )

            numbered_so_far += len(questions) * marks

    if numbered_so_far == 0:
        blockers.append("Add at least one question.")

    return blockers


def _gap_blockers(
    label: str, group: QuestionGroup, questions: list[Question], offset: int
) -> list[str]:
    """What a completion group still needs. ``offset`` is how many questions
    come before this group in the material, so the numbers quoted are the ones
    printed beside the gaps."""
    boxed = bool(listening_service.group_options(group))
    lettered_picture = listening_service.image_letter_count(group) > 0
    blockers = _box_blockers(label, group, questions, offset)
    blockers.extend(_picture_blockers(label, group, questions, offset))

    unanswered = [
        offset + q.number
        for q in questions
        if not any(a.strip() for a in q.correct_answers)
    ]
    if unanswered:
        # A gap answered by letter wants a letter, not words. Saying "an
        # accepted answer" there would send the author looking for a field to
        # type one into — and which of the two kinds of letter it is decides
        # where they should be looking instead.
        if boxed:
            missing = "without a letter from the box."
        elif lettered_picture:
            missing = "without a letter from the picture."
        else:
            missing = "without an accepted answer."
        blockers.append(f"{label}: {_numbers(unanswered)} {missing}")

    # Where the answer is said is what the learner gets back with their
    # result — the reason to re-listen rather than just be told they were
    # wrong. Required, by the same reasoning as the answer itself.
    unmarked = [offset + q.number for q in questions if q.replay_start_ms is None]
    if unmarked:
        blockers.append(f"{label}: {_numbers(unmarked)} not linked to the audio.")

    return blockers


def _choice_blockers(
    label: str, questions: list[Question], offset: int, wanted: int
) -> list[str]:
    """What a multiple-choice group still needs. ``wanted`` is how many
    letters the group tells the candidate to pick.

    Being linked to the audio IS among them, as it is for a gap. This was
    once left out on the reasoning that a choice question is answered from
    the whole of what was said rather than from one phrase in it — but that
    conflates two things. The option's wording is rarely spoken; the answer
    always is. Some sentence in the recording is what makes b right rather
    than a, even where it does so by implication, and that sentence is what
    a learner who got it wrong needs sending back to.

    What is not required is that the marked seconds contain the option's
    text. For a gap, a mismatch there earns a quiet warning in the editor
    (features/listening/marks.ts); for a choice question it would fire on
    nearly every correctly marked one, so nothing checks it."""
    blockers: list[str] = []

    def numbers(matching) -> list[int]:
        # The FIRST of the numbers this question occupies. A "choose two" is
        # printed as "Questions 23 and 24"; naming 23 is enough to find it,
        # and a message listing both halves of every question reads as twice
        # as much wrong as there is.
        return [
            offset + (q.number - 1) * wanted + 1
            for q in questions
            if matching(q)
        ]

    unwritten = numbers(lambda q: not (q.config or {}).get("prompt", "").strip())
    if unwritten:
        blockers.append(f"{label}: {_numbers(unwritten)} without any question text.")

    # Enough to choose from, and never fewer than the group asks for: "choose
    # two of these two" is not a question.
    too_few = numbers(lambda q: len(q.options or []) < max(2, wanted + 1))
    if too_few:
        blockers.append(
            f"{label}: {_numbers(too_few)} with too few options to choose from."
        )

    blank_option = numbers(
        lambda q: bool(q.options) and any(not o.strip() for o in q.options or [])
    )
    if blank_option:
        blockers.append(f"{label}: {_numbers(blank_option)} with a blank option.")

    # Exactly what the instruction line promises. Short of it, the candidate
    # is told to choose two and then marked against a key of one; over it is
    # refused at write time and can't get here.
    if wanted == 1:
        unmarked = numbers(lambda q: not q.correct_answers)
        if unmarked:
            blockers.append(f"{label}: {_numbers(unmarked)} without a correct answer.")
    else:
        short = numbers(lambda q: len(q.correct_answers) != wanted)
        if short:
            blockers.append(
                f"{label}: {_numbers(short)} without {wanted} answers marked."
            )

    # Every RIGHT option, not the question: a "choose two" is answered in two
    # places, and one range covering the first of them leaves the second
    # unexplained. Options that aren't right are ignored — a distractor has
    # no moment, and a mark left on one from before the key changed is kept
    # rather than demanded.
    unlinked = numbers(
        lambda q: any(
            letter not in q.option_replay for letter in (q.correct_answers or [])
        )
    )
    if unlinked:
        blockers.append(f"{label}: {_numbers(unlinked)} not linked to the audio.")

    return blockers


def _box_blockers(
    label: str,
    group: QuestionGroup,
    questions: list[Question],
    offset: int,
) -> list[str]:
    """What a box of options still needs, for either task that has one:
    matching, where the box is the whole point, and a completion task printed
    with a word list, where it turns every gap into a letter.

    All of it is about the group rather than any one question — the box is
    printed once above the set — except the last, which is the one thing a
    shared box makes possible: two questions claiming the same letter where
    each letter answers only one."""
    blockers: list[str] = []
    options = listening_service.group_options(group)
    allow_reuse = bool((group.config or {}).get("allow_reuse"))
    if not options:
        return blockers

    if len(options) < 2:
        blockers.append(f"{label}: add at least two options to choose from.")
    elif any(not option.strip() for option in options):
        blockers.append(f"{label}: an option to choose from has nothing in it.")
    # Without reuse each option answers at most one question, so a box shorter
    # than the list is a group that cannot be completed however long the author
    # works at it. With reuse allowed it is ordinary — three options and eight
    # questions is a common Part 3 set.
    elif not allow_reuse and len(options) < len(questions):
        blockers.append(
            f"{label}: {len(questions)} questions and only {len(options)} "
            "options to answer them from — add more options, or allow a letter "
            "to be used more than once."
        )

    if not allow_reuse:
        repeated = _repeated_letters(questions, offset)
        if repeated:
            blockers.append(
                f"{label}: {_numbers(repeated)} answered with a letter another "
                "question already uses."
            )

    return blockers


def _repeated_letters(questions: list[Question], offset: int) -> list[int]:
    """Every question after the first to claim a letter another already has.

    The first keeps it: something has to, and the one the author wrote earlier
    is the likelier of the two to be the one they meant.

    Shared by the two things that hand out letters — a box of words and a
    lettered picture — because it is the same mistake either way."""
    taken: set[str] = set()
    repeated: list[int] = []
    for question in sorted(questions, key=lambda q: q.number):
        for letter in question.correct_answers:
            if letter in taken:
                repeated.append(offset + question.number)
            taken.add(letter)
    return repeated


def _picture_blockers(
    label: str,
    group: QuestionGroup,
    questions: list[Question],
    offset: int,
) -> list[str]:
    """What a map or diagram task needs beyond what every completion task
    needs: the picture, and — where the letters are drawn on it — enough of
    them to answer with.

    The picture is required. It is the one thing that makes this task the task:
    "Label the map below" with no map below is not an unfinished question, it is
    an instruction to look at nothing.

    Letters on the picture are optional, and their absence is not a draft. A
    real paper prints both: a map with numbered blanks and "write no more than
    two words", and a map with A–H drawn on it. Zero letters means the first
    one, and there is nothing further to check."""
    if group.type not in LABELLING_TYPES:
        return []

    blockers: list[str] = []
    if listening_service.group_image(group) is None:
        blockers.append(f"{label}: attach the picture the labels go on.")

    letters = listening_service.image_letter_count(group)
    if not letters:
        return blockers

    if letters < 2:
        blockers.append(
            f"{label}: the picture is marked as having one letter — with only "
            "one there is nothing to choose between."
        )
    elif letters < len(questions):
        blockers.append(
            f"{label}: {len(questions)} questions and only {letters} letters on "
            "the picture — draw more letters on it, or say how many there "
            "really are."
        )

    # Always checked, and with no "allow letters to be used again" escape,
    # unlike a word box. A letter on a map marks one place on it, so two
    # questions answered "C" is two questions with the same answer — which is
    # a mistake in the key, not a task that permits reuse.
    repeated = _repeated_letters(questions, offset)
    if repeated:
        blockers.append(
            f"{label}: {_numbers(repeated)} answered with a letter another "
            "question already uses."
        )

    return blockers


def _matching_blockers(
    label: str,
    group: QuestionGroup,
    questions: list[Question],
    offset: int,
) -> list[str]:
    """What a matching group still needs.

    Half of it is about the group rather than any one question, which is what
    makes this different from the other two: the box of options is printed
    once above the set, so "there is nothing to match to" is one complaint
    about the whole group and not one per item.

    Each item is one number and one mark, so the numbers quoted here are
    simply ``offset + q.number`` — the arithmetic a "choose two" forces on
    :func:`_choice_blockers` has nothing to do here."""
    blockers = _box_blockers(label, group, questions, offset)

    def numbers(matching) -> list[int]:
        return [offset + q.number for q in questions if matching(q)]

    unwritten = numbers(lambda q: not (q.config or {}).get("prompt", "").strip())
    if unwritten:
        blockers.append(f"{label}: {_numbers(unwritten)} without any question text.")

    unanswered = numbers(lambda q: not q.correct_answers)
    if unanswered:
        blockers.append(f"{label}: {_numbers(unanswered)} without an answer.")

    unmarked = numbers(lambda q: q.replay_start_ms is None)
    if unmarked:
        blockers.append(f"{label}: {_numbers(unmarked)} not linked to the audio.")

    return blockers


async def _dictation_blockers(
    session: AsyncSession, material_id: uuid.UUID
) -> list[str]:
    segments = await materials_service.get_segments(session, material_id)
    if not segments:
        return ["Add at least one segment."]

    blank = [s.order_index + 1 for s in segments if not s.reference_text.strip()]
    if blank:
        return [f"{_numbers(blank, 'Segment')} without any text."]
    return []


def _numbers(numbers: list[int], noun: str = "Question") -> str:
    if len(numbers) == 1:
        return f"{noun} {numbers[0]} is"
    listed = ", ".join(str(n) for n in numbers)
    return f"{noun}s {listed} are"


async def demote_if_unpublishable(
    session: AsyncSession, material: Material
) -> list[str]:
    """Move a public material back to draft when it stops qualifying, and
    report why. Returns an empty list when nothing changed — either it still
    qualifies, or it was a draft to begin with.

    Called after a write, not before: whether the material still holds up is
    a question about what it has just become.
    """
    if material.visibility != "public":
        return []
    blockers = await publish_blockers(session, material)
    if not blockers:
        return []
    material.visibility = "private"
    session.add(material)
    await session.commit()
    return blockers
