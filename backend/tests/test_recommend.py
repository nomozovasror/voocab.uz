"""What to practise next (app/services/recommend.py).

Two halves, and the first is where the design lives. Choosing three unsat
materials is a query; deciding what to SAY about them is the part that can be
wrong in a way nobody notices, so the rules that guard the "your weakest part"
claim are tested as pure functions with the numbers written out.

That claim is guarded because it has already been got wrong once: the sidebar
used to name the lowest-scoring part outright, and 62% against 66% over a few
dozen answers is noise. The tests below are the shape of that lesson — a gap
that isn't decisive, a worst part that isn't weak, a part nobody has answered
enough of.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.attempt import Attempt, AttemptStatus
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import QuestionGroup
from app.models.collection import Collection, CollectionItem
from app.models.user import User
from app.services import collections as collections_service
from app.services import recommend
from app.services.learner_stats import MIN_ANSWERS

# --- The rules, on their own -------------------------------------------------


def _parts(**accuracy: int | None) -> list[dict]:
    """`_parts(p1=40, p2=None)` — the shape `_by_part` returns, briefly."""
    return [
        {
            "part": int(name[1:]),
            "accuracy_pct": pct,
            "answered": 0 if pct is None else 40,
        }
        for name, pct in accuracy.items()
    ]


def test_a_part_is_named_when_it_is_clearly_behind() -> None:
    weak = recommend._weak_part(_parts(p1=72, p2=70, p3=45, p4=68))
    assert weak is not None
    assert weak["part"] == 3


def test_a_close_run_thing_is_not_a_weakness() -> None:
    """62 against 66 is which questions you happened to get, not which part
    you are bad at. Naming it sends somebody to Part 2 one week and Part 3 the
    next on evidence that never changed."""
    assert recommend._weak_part(_parts(p1=66, p2=62, p3=70, p4=68)) is None


def test_a_good_worst_part_is_not_a_weak_one() -> None:
    """Somebody whose worst part is 78% has four good parts, and telling them
    otherwise is inventing a problem to solve."""
    assert recommend._weak_part(_parts(p1=95, p2=78, p3=94, p4=96)) is None


def test_an_unmeasured_part_is_not_a_weak_one() -> None:
    """No percentage means not enough answers, not zero. A part somebody has
    barely touched is the one thing that must never be called their weakest."""
    assert recommend._weak_part(_parts(p1=64, p2=None, p3=None, p4=None)) is not None
    assert recommend._weak_part(_parts(p1=None, p2=None)) is None


def test_one_measured_part_has_nothing_to_be_clear_of() -> None:
    """And that is enough: one measured part against three unmeasured ones is
    not a close-run thing, it is the only thing we know."""
    weak = recommend._weak_part(_parts(p1=None, p2=50, p3=None, p4=None))
    assert weak is not None
    assert weak["part"] == 2


@pytest.mark.parametrize(
    "average,first",
    [
        (None, "easy"),
        (35, "easy"),
        (59, "easy"),
        (60, "medium"),
        (79, "medium"),
        (85, "medium"),
        (100, "medium"),
    ],
)
def test_the_ladder_never_opens_with_hard(average, first) -> None:
    """Including for the people doing well. The difference between 85% and
    65% is which of medium and hard comes SECOND — not whether somebody's
    evening starts with a paper most people fail."""
    ranks = recommend._ranks_for(average)
    assert min(ranks, key=ranks.get) == first
    # And an unrated material is always last: "might be anything" is not a
    # recommendation.
    assert ranks["new"] == max(ranks.values())


# --- End to end --------------------------------------------------------------


async def _user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name="Next up")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _material(
    author_id: uuid.UUID, title: str, part_number: int, *, questions: int = 4
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """A public listening material holding exactly one part, numbered
    ``part_number``. ``questions=0`` makes an empty one — a shell an author
    started and never filled in, which is the thing a recommendation must
    never be."""
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id, type="listening", title=title, visibility="public"
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)

        part = Part(
            material_id=material.id,
            order_index=part_number - 1,
            title=f"Part {part_number}",
        )
        session.add(part)
        await session.commit()
        await session.refresh(part)

        if questions == 0:
            return material.id, []

        group = QuestionGroup(
            part_id=part.id,
            type="form_completion",
            order_index=0,
            instructions="Complete the notes.",
            config={"template": "a {{1}}"},
        )
        session.add(group)
        await session.commit()
        await session.refresh(group)

        ids = []
        for number in range(1, questions + 1):
            question = Question(
                group_id=group.id, number=number, correct_answers=["x"]
            )
            session.add(question)
            await session.commit()
            await session.refresh(question)
            ids.append(question.id)
        return material.id, ids


async def _sit(
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


async def _cleanup(material_ids: list[uuid.UUID], email: str) -> None:
    async with async_session_factory() as session:
        for material_id in material_ids:
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
                await session.exec(
                    select(Part).where(Part.material_id == material_id)
                )
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
            material = await session.get(Material, material_id)
            if material is not None:
                await session.delete(material)
        await session.flush()
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            await session.delete(user)
        await session.commit()


@pytest.mark.asyncio
async def test_somebody_with_no_history_is_sent_to_part_one() -> None:
    """The gentlest section of the paper, and the one whose task types the
    rest are built on. Nothing is asserted about a reader we know nothing
    about."""
    email = f"next-new-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    first, _q = await _material(user.id, f"Next {uuid.uuid4()}", 1)
    try:
        async with async_session_factory() as session:
            out = await recommend.next_up(session, user.id)
        assert out["reason"] == "start"
        assert out["part"] == 1
        assert out["accuracy_pct"] is None
        assert any(row["id"] == first for row in out["items"])
    finally:
        await _cleanup([first], email)


@pytest.mark.asyncio
async def test_a_paper_already_sat_is_never_recommended() -> None:
    """Recommending something somebody finished last week is the page not
    paying attention."""
    email = f"next-sat-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    sat, questions = await _material(user.id, f"Sat {uuid.uuid4()}", 1)
    fresh, _q = await _material(user.id, f"Fresh {uuid.uuid4()}", 1)
    try:
        await _sit(user.id, sat, questions, answers=4, correct=2)
        async with async_session_factory() as session:
            out = await recommend.next_up(session, user.id)
        ids = [row["id"] for row in out["items"]]
        assert sat not in ids
        assert fresh in ids
    finally:
        await _cleanup([sat, fresh], email)


@pytest.mark.asyncio
async def test_an_empty_shell_is_never_recommended() -> None:
    """A material with no questions is not practice, and a recommendation is
    the page choosing on the learner's behalf how to spend their evening."""
    email = f"next-empty-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    shell, _none = await _material(user.id, f"Shell {uuid.uuid4()}", 1, questions=0)
    try:
        async with async_session_factory() as session:
            out = await recommend.next_up(session, user.id)
        assert all(row["id"] != shell for row in out["items"])
    finally:
        await _cleanup([shell], email)


@pytest.mark.asyncio
async def test_a_lopsided_learner_is_sent_to_the_part_they_are_behind_on() -> None:
    """Two parts, far enough apart to mean something, and the recommendation
    is material holding the weaker one — with the reason attached, so the page
    can say why rather than just presenting three papers."""
    email = f"next-weak-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    strong, strong_q = await _material(user.id, f"Strong {uuid.uuid4()}", 1)
    weak, weak_q = await _material(user.id, f"Weak {uuid.uuid4()}", 3)
    more_weak, _q = await _material(user.id, f"More part 3 {uuid.uuid4()}", 3)
    try:
        # Part 1 answered well, Part 3 answered badly, both over the evidence
        # threshold. Every attempt is a first attempt — different materials —
        # which is the only kind that counts.
        await _sit(user.id, strong, strong_q, answers=MIN_ANSWERS, correct=MIN_ANSWERS)
        await _sit(user.id, weak, weak_q, answers=MIN_ANSWERS, correct=0)

        async with async_session_factory() as session:
            out = await recommend.next_up(session, user.id)

        assert out["reason"] == "weak_part"
        assert out["part"] == 3
        assert out["accuracy_pct"] == 0
        assert [row["id"] for row in out["items"]] == [more_weak]
    finally:
        await _cleanup([strong, weak, more_weak], email)


@pytest.mark.asyncio
async def test_an_even_learner_is_told_about_their_level_instead() -> None:
    """The ordinary case, and not a failure of the other branch: most people
    practising are not lopsided, they are just practising. The page still has
    something true to say — these suit how you are doing."""
    email = f"next-even-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    one, one_q = await _material(user.id, f"Even one {uuid.uuid4()}", 1)
    two, two_q = await _material(user.id, f"Even two {uuid.uuid4()}", 2)
    spare, _q = await _material(user.id, f"Even spare {uuid.uuid4()}", 4)
    try:
        # Both parts at exactly the same accuracy: nothing is behind anything.
        for material, questions in ((one, one_q), (two, two_q)):
            await _sit(
                user.id,
                material,
                questions,
                answers=MIN_ANSWERS,
                correct=MIN_ANSWERS // 2,
            )

        async with async_session_factory() as session:
            out = await recommend.next_up(session, user.id)

        assert out["reason"] == "level"
        assert out["part"] is None
        assert out["accuracy_pct"] == 50
        assert spare in [row["id"] for row in out["items"]]
    finally:
        await _cleanup([one, two, spare], email)


# --- Where the two halves of the page meet -----------------------------------


async def _collection(
    author_id: uuid.UUID, title: str, material_ids: list[uuid.UUID]
) -> uuid.UUID:
    async with async_session_factory() as session:
        collection = Collection(
            author_id=author_id, title=title, visibility="public"
        )
        session.add(collection)
        await session.commit()
        await session.refresh(collection)
        for index, material_id in enumerate(material_ids):
            session.add(
                CollectionItem(
                    collection_id=collection.id,
                    material_id=material_id,
                    order_index=index,
                )
            )
        await session.commit()
        return collection.id


async def _drop_collections(email: str) -> None:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is None:
            return
        for collection in (
            await session.exec(
                select(Collection).where(Collection.author_id == user.id)
            )
        ).all():
            for item in (
                await session.exec(
                    select(CollectionItem).where(
                        CollectionItem.collection_id == collection.id
                    )
                )
            ).all():
                await session.delete(item)
            await session.flush()
            await session.delete(collection)
        await session.commit()


@pytest.mark.asyncio
async def test_a_course_in_progress_outranks_everything_else() -> None:
    """Somebody four papers into a six-paper course does not want three
    unrelated ones.

    They chose the course, and its order is a person's judgement about what to
    do when — both of which are better than anything this module can work out
    from a first-try average. So the recommendation carries on with it, in its
    order, and says which lesson it is.
    """
    email = f"next-course-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    course = [
        await _material(user.id, f"Lesson {i} {uuid.uuid4()}", 1) for i in range(4)
    ]
    loose, loose_q = await _material(user.id, f"Loose {uuid.uuid4()}", 1)
    made = [m for m, _q in course] + [loose]

    try:
        collection_id = await _collection(
            user.id, "Part 1 from scratch", [m for m, _q in course]
        )
        # The first two sat, so the course is started and unfinished.
        for material_id, questions in course[:2]:
            await _sit(user.id, material_id, questions, answers=4, correct=2)

        async with async_session_factory() as session:
            out = await recommend.next_up(session, user.id)

        assert out["reason"] == "course"
        assert out["collection"]["id"] == collection_id
        # Lesson three of four, and the rows are the rest of it IN ORDER.
        assert out["position"] == 3
        assert out["of"] == 4
        assert out["done"] == 2
        assert [row["id"] for row in out["items"]] == [
            course[2][0],
            course[3][0],
        ]
        # Not the loose material, however well it would have fitted.
        assert loose not in [row["id"] for row in out["items"]]
        assert loose_q is not None
    finally:
        await _drop_collections(email)
        await _cleanup(made, email)


@pytest.mark.asyncio
async def test_the_course_carried_on_with_is_the_one_last_touched() -> None:
    """Not the one furthest through.

    The question a page answers when somebody comes back is where they left
    off. Furthest-through would keep pointing at a course they abandoned in
    March because they happened to get most of the way through it first.
    """
    email = f"next-recent-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    old = [await _material(user.id, f"Old {i} {uuid.uuid4()}", 1) for i in range(4)]
    new = [await _material(user.id, f"New {i} {uuid.uuid4()}", 2) for i in range(3)]
    made = [m for m, _q in old + new]

    try:
        await _collection(user.id, "Abandoned in March", [m for m, _q in old])
        recent_id = await _collection(user.id, "Started today", [m for m, _q in new])

        # Three of four in the old one, then one in the new one — so the old
        # course is further through and the new one is more recent.
        for material_id, questions in old[:3]:
            await _sit(user.id, material_id, questions, answers=4, correct=2)
        await _sit(user.id, new[0][0], new[0][1], answers=4, correct=2)

        async with async_session_factory() as session:
            out = await recommend.next_up(session, user.id)

        assert out["reason"] == "course"
        assert out["collection"]["id"] == recent_id
        assert out["position"] == 2
    finally:
        await _drop_collections(email)
        await _cleanup(made, email)


@pytest.mark.asyncio
async def test_a_finished_course_is_not_something_to_carry_on_with() -> None:
    """Nor is one they have never opened. Both are recommendations rather than
    continuations, which is a different sentence and a different rung."""
    email = f"next-done-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    done_material, done_q = await _material(user.id, f"Done {uuid.uuid4()}", 1)
    untouched, _q = await _material(user.id, f"Untouched {uuid.uuid4()}", 1)
    spare, _q2 = await _material(user.id, f"Spare {uuid.uuid4()}", 1)
    made = [done_material, untouched, spare]

    try:
        await _collection(user.id, "Finished course", [done_material])
        await _collection(user.id, "Never opened", [untouched])
        await _sit(user.id, done_material, done_q, answers=4, correct=2)

        async with async_session_factory() as session:
            out = await recommend.next_up(session, user.id)

        assert out["reason"] != "course"
    finally:
        await _drop_collections(email)
        await _cleanup(made, email)


@pytest.mark.asyncio
async def test_a_loose_suggestion_never_jumps_a_course_queue() -> None:
    """Lesson five is not offered to somebody on lesson three.

    The reader here has finished the course they started, so the branch above
    does not fire — but a course they never opened still holds materials, and
    those must not be handed out in the wrong order either.
    """
    email = f"next-queue-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    course = [
        await _material(user.id, f"Queued {i} {uuid.uuid4()}", 1) for i in range(3)
    ]
    made = [m for m, _q in course]

    try:
        await _collection(user.id, "Sequenced", [m for m, _q in course])
        # First one sat: the course is started, so lessons two and three are
        # waiting their turn — and two IS the turn.
        await _sit(user.id, course[0][0], course[0][1], answers=4, correct=2)

        async with async_session_factory() as session:
            waiting = await collections_service.sequenced_material_ids(
                session, user.id
            )

        assert course[2][0] in waiting
        assert course[1][0] not in waiting
    finally:
        await _drop_collections(email)
        await _cleanup(made, email)


@pytest.mark.asyncio
async def test_done_is_counted_not_read_off_the_queue() -> None:
    """Somebody who skipped ahead has done more than their place suggests.

    Lessons one and three sat, so the next one up is two — but three lessons'
    worth of work is two, not one. A bar drawn from the position would
    under-report their own work back at them.
    """
    email = f"next-skip-{uuid.uuid4().hex[:8]}@example.com"
    user = await _user(email)
    course = [
        await _material(user.id, f"Skip {i} {uuid.uuid4()}", 1) for i in range(4)
    ]
    made = [m for m, _q in course]

    try:
        await _collection(user.id, "Skipped about", [m for m, _q in course])
        for index in (0, 2):
            material_id, questions = course[index]
            await _sit(user.id, material_id, questions, answers=4, correct=2)

        async with async_session_factory() as session:
            out = await recommend.next_up(session, user.id)

        assert out["reason"] == "course"
        assert out["position"] == 2  # the next one still waiting
        assert out["done"] == 2  # and two are behind them
        assert out["of"] == 4
    finally:
        await _drop_collections(email)
        await _cleanup(made, email)
