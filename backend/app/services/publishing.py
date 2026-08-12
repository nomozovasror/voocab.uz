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
    total_questions = 0

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
            total_questions += len(questions)

            unanswered = [
                q.number
                for q in questions
                if not any(a.strip() for a in q.correct_answers)
            ]
            if unanswered:
                blockers.append(
                    f"{label}: {_numbers(unanswered)} without an accepted answer."
                )

            # Where the answer is said is what the learner gets back with
            # their result — the reason to re-listen rather than just be told
            # they were wrong. Required, by the same reasoning as the answer
            # itself.
            unmarked = [q.number for q in questions if q.replay_start_ms is None]
            if unmarked:
                blockers.append(
                    f"{label}: {_numbers(unmarked)} not linked to the audio."
                )

    if total_questions == 0:
        blockers.append("Add at least one question.")

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
