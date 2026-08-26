"""The difficulty projection (app/services/difficulty.py + material_difficulty).

What changed, and what these pin down: difficulty is no longer aggregated
when somebody opens the catalogue. It is computed by :func:`recompute` on the
worker's timer and read back by primary key, because the aggregate is a scan
of every answer on the platform and a thousand materials makes that a page
that takes seconds to draw.

The measurement itself is unchanged and is tested where it always was
(tests/test_listening_stats.py). These are about the seam: that the numbers
survive the round trip through the table, that a material nobody has answered
is a row rather than an absence, that a second pass changes nothing, and —
the one genuinely new fact about the system — that a band is only as fresh as
the last refresh.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.attempt import Attempt, AttemptStatus
from app.models.material import Material
from app.models.material_difficulty import MaterialDifficulty
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import QuestionGroup
from app.models.user import User
from app.services import difficulty as difficulty_service
from app.services.difficulty import MIN_ANSWERS


async def _material(title: str) -> tuple[uuid.UUID, list[uuid.UUID], uuid.UUID]:
    """A public listening material with one part, one group and four
    questions. Built directly rather than through the API: what is under test
    is the aggregate, and the authoring endpoints are covered elsewhere."""
    async with async_session_factory() as session:
        user = (
            await session.exec(
                select(User).where(User.email == "difficulty-projection@example.com")
            )
        ).first()
        if user is None:
            user = User(
                email="difficulty-projection@example.com", display_name="Projection"
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        material = Material(
            author_id=user.id, type="listening", title=title, visibility="public"
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)

        part = Part(material_id=material.id, order_index=0, title="Part 1")
        session.add(part)
        await session.commit()
        await session.refresh(part)

        group = QuestionGroup(
            part_id=part.id,
            type="form_completion",
            order_index=0,
            instructions="Complete the notes.",
            config={"template": "Name: ____"},
        )
        session.add(group)
        await session.commit()
        await session.refresh(group)

        question_ids = []
        for number in range(1, 5):
            question = Question(
                group_id=group.id, number=number, correct_answers=["x"]
            )
            session.add(question)
            await session.commit()
            await session.refresh(question)
            question_ids.append(question.id)

        return material.id, question_ids, user.id


async def _answer(
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    question_ids: list[uuid.UUID],
    *,
    answers: int,
    correct: int,
) -> None:
    async with async_session_factory() as session:
        attempt = Attempt(
            user_id=user_id,
            material_id=material_id,
            status=AttemptStatus.SUBMITTED,
            score=correct,
            total_questions=answers,
            submitted_at=datetime.now(timezone.utc),
        )
        session.add(attempt)
        await session.commit()
        await session.refresh(attempt)

        for i in range(answers):
            session.add(
                QuestionAttempt(
                    attempt_id=attempt.id,
                    question_id=question_ids[i % len(question_ids)],
                    given_answer="whatever",
                    is_correct=i < correct,
                )
            )
        await session.commit()


async def _cleanup(material_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        material = await session.get(Material, material_id)
        if material is None:
            return
        for attempt in (
            await session.exec(
                select(Attempt).where(Attempt.material_id == material_id)
            )
        ).all():
            for qa in (
                await session.exec(
                    select(QuestionAttempt).where(
                        QuestionAttempt.attempt_id == attempt.id
                    )
                )
            ).all():
                await session.delete(qa)
            await session.flush()
            await session.delete(attempt)
        await session.flush()

        for part in (
            await session.exec(select(Part).where(Part.material_id == material_id))
        ).all():
            for group in (
                await session.exec(
                    select(QuestionGroup).where(QuestionGroup.part_id == part.id)
                )
            ).all():
                for question in (
                    await session.exec(
                        select(Question).where(Question.group_id == group.id)
                    )
                ).all():
                    await session.delete(question)
                await session.flush()
                await session.delete(group)
            await session.flush()
            await session.delete(part)
        await session.flush()
        await session.delete(material)
        await session.commit()


@pytest.mark.asyncio
async def test_the_tally_survives_the_round_trip() -> None:
    """What the aggregate found is what the read path reports."""
    material_id, questions, user_id = await _material(f"Round trip {uuid.uuid4()}")
    try:
        await _answer(user_id, material_id, questions, answers=40, correct=30)

        async with async_session_factory() as session:
            await difficulty_service.recompute(session, [material_id])
            row = await difficulty_service.material_difficulty(session, [material_id])

        assert row[material_id] == {
            "band": "easy",
            "correct_pct": 75,
            "answered": 40,
        }
    finally:
        await _cleanup(material_id)


@pytest.mark.asyncio
async def test_a_material_nobody_has_answered_gets_a_row_not_an_absence() -> None:
    """A zero tally is a fact, and it is written down.

    The alternative — leaving the row out — makes "nobody has answered this"
    and "the refresher has never run" the same observation, and those need
    telling apart the day something goes wrong.
    """
    material_id, _questions, _user_id = await _material(f"Untouched {uuid.uuid4()}")
    try:
        async with async_session_factory() as session:
            await difficulty_service.recompute(session, [material_id])
            stored = await session.get(MaterialDifficulty, material_id)

        assert stored is not None
        assert (stored.answered, stored.correct, stored.band) == (0, 0, "new")
    finally:
        await _cleanup(material_id)


@pytest.mark.asyncio
async def test_a_material_with_no_row_reads_as_new() -> None:
    """Created since the last refresh, and the page still draws.

    This is the state every material is in for its first fifteen minutes, so
    it had better not be an error — `New` is exactly what a material nobody
    has answered is anyway.
    """
    material_id, _questions, _user_id = await _material(f"Unrefreshed {uuid.uuid4()}")
    try:
        async with async_session_factory() as session:
            row = await difficulty_service.material_difficulty(session, [material_id])

        assert row[material_id] == {"band": "new", "correct_pct": None, "answered": 0}
    finally:
        await _cleanup(material_id)


@pytest.mark.asyncio
async def test_a_band_is_only_as_fresh_as_the_last_refresh() -> None:
    """The price of the projection, written down so nobody is surprised by it.

    Answers land, and the band does not move until the refresher runs. That
    is the trade: a page that loads in milliseconds against a number that can
    be one interval out of date — on a measurement averaged over dozens of
    answers, which does not meaningfully move in that time.
    """
    material_id, questions, user_id = await _material(f"Staleness {uuid.uuid4()}")
    try:
        await _answer(user_id, material_id, questions, answers=40, correct=4)
        async with async_session_factory() as session:
            await difficulty_service.recompute(session, [material_id])
            before = await difficulty_service.material_difficulty(
                session, [material_id]
            )
        assert before[material_id]["band"] == "hard"

        # Forty perfect answers arrive. Nothing recomputes.
        await _answer(user_id, material_id, questions, answers=40, correct=40)
        async with async_session_factory() as session:
            during = await difficulty_service.material_difficulty(
                session, [material_id]
            )
        assert during[material_id]["band"] == "hard"
        assert during[material_id]["answered"] == 40

        # The timer fires.
        async with async_session_factory() as session:
            await difficulty_service.recompute(session, [material_id])
            after = await difficulty_service.material_difficulty(session, [material_id])
        assert after[material_id]["band"] == "medium"
        assert after[material_id]["answered"] == 80
        assert after[material_id]["correct_pct"] == 55
    finally:
        await _cleanup(material_id)


@pytest.mark.asyncio
async def test_recomputing_twice_changes_nothing_but_the_timestamp() -> None:
    """An upsert, not an insert. The job runs every quarter of an hour
    forever, so the second run has to be as harmless as the first."""
    material_id, questions, user_id = await _material(f"Idempotent {uuid.uuid4()}")
    try:
        await _answer(user_id, material_id, questions, answers=24, correct=12)

        async with async_session_factory() as session:
            await difficulty_service.recompute(session, [material_id])
            first = await session.get(MaterialDifficulty, material_id)
            assert first is not None
            tally = (first.answered, first.correct, first.band)
            stamped = first.computed_at

        async with async_session_factory() as session:
            await difficulty_service.recompute(session, [material_id])
            second = await session.get(MaterialDifficulty, material_id)
            assert second is not None
            assert (second.answered, second.correct, second.band) == tally
            assert second.computed_at >= stamped

        # And exactly one row for the material, not two.
        async with async_session_factory() as session:
            rows = (
                await session.exec(
                    select(MaterialDifficulty).where(
                        MaterialDifficulty.material_id == material_id
                    )
                )
            ).all()
        assert len(rows) == 1
    finally:
        await _cleanup(material_id)


@pytest.mark.asyncio
async def test_the_default_pass_covers_every_listening_material() -> None:
    """Called with no ids — the way the worker calls it — nothing is missed."""
    first, questions, user_id = await _material(f"Sweep A {uuid.uuid4()}")
    second, _q2, _u2 = await _material(f"Sweep B {uuid.uuid4()}")
    try:
        await _answer(user_id, first, questions, answers=MIN_ANSWERS, correct=0)

        async with async_session_factory() as session:
            written = await difficulty_service.recompute(session)
            rows = await difficulty_service.material_difficulty(
                session, [first, second]
            )

        assert written >= 2
        assert rows[first]["band"] == "hard"
        assert rows[second]["band"] == "new"
    finally:
        await _cleanup(first)
        await _cleanup(second)


@pytest.mark.asyncio
async def test_deleting_a_material_takes_its_tally_with_it() -> None:
    """A projection row about something that no longer exists is not a fact
    about anything. The FK's ON DELETE CASCADE is what guarantees it, so it
    is worth one test — the alternative is a table that only grows."""
    material_id, questions, user_id = await _material(f"Cascade {uuid.uuid4()}")
    await _answer(user_id, material_id, questions, answers=20, correct=10)
    async with async_session_factory() as session:
        await difficulty_service.recompute(session, [material_id])
        assert await session.get(MaterialDifficulty, material_id) is not None

    await _cleanup(material_id)

    async with async_session_factory() as session:
        assert await session.get(MaterialDifficulty, material_id) is None


# --- The one refresh that does not wait for the timer ------------------------


@pytest.mark.asyncio
async def test_an_unrated_material_is_refreshed_on_the_spot() -> None:
    """The first crossing of the threshold happens immediately.

    Until it does, the material says "nobody has answered enough of this yet"
    — and a paper a class of twenty has just worked through, still advertising
    that, is the catalogue contradicting itself in front of the people who
    proved it wrong.
    """
    material_id, questions, user_id = await _material(f"Crossing {uuid.uuid4()}")
    try:
        # Short of the threshold: refreshed, and still New, which is the
        # truth rather than a failure to update.
        await _answer(
            user_id, material_id, questions, answers=MIN_ANSWERS - 1, correct=0
        )
        async with async_session_factory() as session:
            assert await difficulty_service.refresh_if_unrated(session, material_id)
            row = await difficulty_service.material_difficulty(
                session, [material_id]
            )
        assert row[material_id]["band"] == "new"
        assert row[material_id]["answered"] == MIN_ANSWERS - 1

        # One more answer crosses it, and the band is there without anything
        # having run on a timer.
        await _answer(user_id, material_id, questions, answers=1, correct=0)
        async with async_session_factory() as session:
            assert await difficulty_service.refresh_if_unrated(session, material_id)
            row = await difficulty_service.material_difficulty(
                session, [material_id]
            )
        assert row[material_id]["band"] == "hard"
        assert row[material_id]["answered"] == MIN_ANSWERS
    finally:
        await _cleanup(material_id)


@pytest.mark.asyncio
async def test_a_rated_material_is_left_to_the_timer() -> None:
    """Past the threshold it does nothing, and that is the point: this runs on
    the path a learner is waiting on, and a band averaged over dozens of
    answers does not move enough in fifteen minutes to be worth a write
    there."""
    material_id, questions, user_id = await _material(f"Settled {uuid.uuid4()}")
    try:
        await _answer(user_id, material_id, questions, answers=40, correct=4)
        async with async_session_factory() as session:
            await difficulty_service.recompute(session, [material_id])

        await _answer(user_id, material_id, questions, answers=40, correct=40)
        async with async_session_factory() as session:
            assert (
                await difficulty_service.refresh_if_unrated(session, material_id)
                is False
            )
            row = await difficulty_service.material_difficulty(
                session, [material_id]
            )
        # Untouched: the forty perfect answers wait for the worker.
        assert row[material_id]["answered"] == 40
        assert row[material_id]["band"] == "hard"
    finally:
        await _cleanup(material_id)


@pytest.mark.asyncio
async def test_a_material_never_seen_before_is_refreshed() -> None:
    """No row at all is not "rated": it is the state every material is in
    until the first refresh reaches it, and the first attempt on one has to
    create the row rather than find nothing and give up."""
    material_id, questions, user_id = await _material(f"Firstever {uuid.uuid4()}")
    try:
        await _answer(user_id, material_id, questions, answers=4, correct=2)
        async with async_session_factory() as session:
            assert await difficulty_service.refresh_if_unrated(session, material_id)
            stored = await session.get(MaterialDifficulty, material_id)
        assert stored is not None
        assert stored.answered == 4
    finally:
        await _cleanup(material_id)
