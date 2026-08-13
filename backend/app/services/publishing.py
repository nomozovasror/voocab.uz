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
from app.models.question_group import QuestionGroupType
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
    # numbering, because it is the only one the author can see on the page.
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

            if group.type == QuestionGroupType.MULTIPLE_CHOICE:
                blockers.extend(_choice_blockers(label, questions, numbered_so_far))
            else:
                blockers.extend(_gap_blockers(label, questions, numbered_so_far))

            numbered_so_far += len(questions)

    if numbered_so_far == 0:
        blockers.append("Add at least one question.")

    return blockers


def _gap_blockers(label: str, questions: list[Question], offset: int) -> list[str]:
    """What a form-completion group still needs. ``offset`` is how many
    questions come before this group in the material, so the numbers quoted
    are the ones printed beside the gaps."""
    blockers: list[str] = []

    unanswered = [
        offset + q.number
        for q in questions
        if not any(a.strip() for a in q.correct_answers)
    ]
    if unanswered:
        blockers.append(f"{label}: {_numbers(unanswered)} without an accepted answer.")

    # Where the answer is said is what the learner gets back with their
    # result — the reason to re-listen rather than just be told they were
    # wrong. Required, by the same reasoning as the answer itself.
    unmarked = [offset + q.number for q in questions if q.replay_start_ms is None]
    if unmarked:
        blockers.append(f"{label}: {_numbers(unmarked)} not linked to the audio.")

    return blockers


def _choice_blockers(label: str, questions: list[Question], offset: int) -> list[str]:
    """What a multiple-choice group still needs.

    Being linked to the audio isn't among them, unlike a gap: a choice
    question is answered from the whole of what was said rather than from one
    phrase in it, so there is often no single moment to point a reviewer at,
    and requiring one would be asking the author to invent it."""
    blockers: list[str] = []

    def numbers(matching) -> list[int]:
        return [offset + q.number for q in questions if matching(q)]

    unwritten = numbers(lambda q: not (q.config or {}).get("prompt", "").strip())
    if unwritten:
        blockers.append(f"{label}: {_numbers(unwritten)} without any question text.")

    too_few = numbers(lambda q: len(q.options or []) < 2)
    if too_few:
        blockers.append(f"{label}: {_numbers(too_few)} with fewer than two options.")

    blank_option = numbers(
        lambda q: bool(q.options) and any(not o.strip() for o in q.options or [])
    )
    if blank_option:
        blockers.append(f"{label}: {_numbers(blank_option)} with a blank option.")

    unmarked = numbers(lambda q: not q.correct_answers)
    if unmarked:
        blockers.append(f"{label}: {_numbers(unmarked)} without a correct answer.")

    # Set to several answers but given one: the candidate would be told to
    # choose two and then marked against a key of one.
    short_key = numbers(
        lambda q: (q.config or {}).get("mode") == "multiple"
        and 0 < len(q.correct_answers) < 2
    )
    if short_key:
        blockers.append(
            f"{label}: {_numbers(short_key)} set to several answers "
            "with only one marked."
        )

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
