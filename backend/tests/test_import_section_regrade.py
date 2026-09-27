"""``scripts.import_section.import_questions``: the re-import path that
updates a part's questions IN PLACE instead of deleting and recreating them.

This is the ``voocab-reimport-regrade`` decision (see the module's own
docstring and ``seed/README.md``'s "A marker's turn is not always its
evidence"): a corrected replay span or a corrected answer key must reach a
question somebody has already answered, the attempt has to survive it with
the same id, and its score has to be RE-GRADED against the corrected row
rather than frozen at whatever the uncorrected question said. Only a genuine
shape change -- a group added or removed, a group's own question numbers no
longer matching -- refuses.

No HTTP here: these three behaviours are about a script, not an endpoint, so
the tests build the rows directly and call ``import_questions`` the way
``import_section``/``import_passage`` do.
"""

import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.attempt import Attempt, AttemptStatus
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import QuestionGroup

from scripts import import_section


def _fresh_email() -> str:
    return f"import-regrade-{uuid.uuid4().hex[:12]}@example.com"


async def _make_user() -> uuid.UUID:
    """A throwaway user id.

    Raw SQL rather than ``app.models.user.User`` -- this repo's dev database
    currently carries a `users.is_admin NOT NULL` column that predates this
    branch's own model (a schema the concurrent lexicon work landed, ahead of
    what this worktree's migrations know about). Working around it here,
    once, is cheaper than dragging an unrelated migration into a fix that is
    only about replay spans and re-grading.
    """
    user_id = uuid.uuid4()
    async with async_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, display_name, created_at, is_admin) "
                "VALUES (:id, :email, :display_name, now(), false)"
            ),
            {"id": user_id, "email": _fresh_email(),
             "display_name": "Import regrade test"},
        )
        await session.commit()
    return user_id


async def _make_part(user_id: uuid.UUID) -> Part:
    async with async_session_factory() as session:
        material = Material(
            author_id=user_id, type="listening", title="Regrade test material",
            reference=f"ZZ-{uuid.uuid4().hex[:8]}", visibility="private",
        )
        session.add(material)
        await session.flush()
        part = Part(material_id=material.id, order_index=0, title="Part 1")
        session.add(part)
        await session.commit()
        await session.refresh(part)
        return part


def _form_group_payload(*, spans: dict[int, tuple[int, int]],
                        answers: dict[int, list[str]]) -> dict:
    numbers = sorted(spans)
    template = " ".join(f"{{{{{n}}}}}" for n in numbers)
    return {
        "type": "form_completion",
        "instructions": "Complete the notes.",
        "word_limit": 1,
        "config": {"template": template, "options": [], "image_letters": 0},
        "questions": [
            {
                "number": n,
                "correct_answers": answers[n],
                "replay_start_ms": spans[n][0],
                "replay_end_ms": spans[n][1],
            }
            for n in numbers
        ],
    }


async def _seed_group(part: Part, *, spans: dict[int, tuple[int, int]],
                      answers: dict[int, list[str]]) -> QuestionGroup:
    """Write one form-completion group + its questions directly -- what a
    FIRST import would have produced -- so the test starts from an already
    seeded material the way a re-import always does."""
    async with async_session_factory() as session:
        numbers = sorted(spans)
        template = " ".join(f"{{{{{n}}}}}" for n in numbers)
        group = QuestionGroup(
            part_id=part.id, order_index=0, type="form_completion",
            instructions="Complete the notes.", word_limit=1,
            config={"template": template, "options": [], "image_letters": 0},
        )
        session.add(group)
        await session.flush()
        for n in numbers:
            session.add(Question(
                group_id=group.id, number=n, correct_answers=answers[n],
                replay_start_ms=spans[n][0], replay_end_ms=spans[n][1],
            ))
        await session.commit()
        await session.refresh(group)
        return group


async def _seed_attempt(part: Part, user_id: uuid.UUID, question: Question, *,
                        given: str, correct: bool) -> tuple[Attempt, QuestionAttempt]:
    async with async_session_factory() as session:
        attempt = Attempt(
            user_id=user_id, material_id=part.material_id,
            status=AttemptStatus.SUBMITTED,
            score=1.0 if correct else 0.0, total_questions=1,
            submitted_at=datetime.now(timezone.utc),
        )
        session.add(attempt)
        await session.flush()
        qa = QuestionAttempt(
            attempt_id=attempt.id, question_id=question.id,
            given_answer=given, is_correct=correct,
        )
        session.add(qa)
        await session.commit()
        await session.refresh(attempt)
        await session.refresh(qa)
        return attempt, qa


def _write_questions_json(tmp_path, monkeypatch, section_id: str, groups: list[dict]) -> None:
    seed_root = tmp_path / "seed"
    work = seed_root / "work" / section_id
    work.mkdir(parents=True, exist_ok=True)
    (work / "questions.json").write_text(
        json.dumps({"source": {"kind": "listening"}, "groups": groups}))
    monkeypatch.setattr(import_section, "SEED", seed_root)


async def test_in_place_update_keeps_ids_when_only_spans_change(tmp_path, monkeypatch) -> None:
    user = await _make_user()
    part = await _make_part(user)
    group = await _seed_group(
        part, spans={1: (0, 100), 2: (200, 300)},
        answers={1: ["cat"], 2: ["dog"]})

    async with async_session_factory() as session:
        questions = {
            q.number: q for q in (await session.exec(
                select(Question).where(Question.group_id == group.id))).all()
        }
    attempt, qa1 = await _seed_attempt(
        part, user, questions[1], given="cat", correct=True)

    section_id = f"zz-regrade-{uuid.uuid4().hex[:8]}"
    _write_questions_json(tmp_path, monkeypatch, section_id, [
        _form_group_payload(
            spans={1: (81546, 91920), 2: (200, 300)},
            answers={1: ["cat"], 2: ["dog"]}),
    ])

    async with async_session_factory() as session:
        written = await import_section.import_questions(session, part.id, section_id)
        await session.commit()

    assert written == 2

    async with async_session_factory() as session:
        after_questions = {
            q.number: q for q in (await session.exec(
                select(Question).where(Question.group_id == group.id))).all()
        }
        # Same rows -- same ids -- just moved.
        assert after_questions[1].id == questions[1].id
        assert after_questions[2].id == questions[2].id
        assert (after_questions[1].replay_start_ms, after_questions[1].replay_end_ms) == (81546, 91920)
        assert after_questions[1].correct_answers == ["cat"]

        after_qa = await session.get(QuestionAttempt, qa1.id)
        assert after_qa is not None
        assert after_qa.id == qa1.id
        # Nothing about the key changed, so the grade must not move.
        assert after_qa.is_correct is True

        after_attempt = await session.get(Attempt, attempt.id)
        assert after_attempt is not None
        assert after_attempt.id == attempt.id
        assert after_attempt.score == attempt.score


async def test_regrade_on_a_changed_key_updates_the_score(tmp_path, monkeypatch) -> None:
    user = await _make_user()
    part = await _make_part(user)
    group = await _seed_group(
        part, spans={1: (0, 100)}, answers={1: ["cat"]})

    async with async_session_factory() as session:
        question = (await session.exec(
            select(Question).where(Question.group_id == group.id))).one()
    # The learner typed "dog"; against the (wrong) key "cat" that was marked
    # wrong.
    attempt, qa = await _seed_attempt(part, user, question, given="dog", correct=False)
    assert attempt.score == 0.0

    section_id = f"zz-regrade-{uuid.uuid4().hex[:8]}"
    _write_questions_json(tmp_path, monkeypatch, section_id, [
        _form_group_payload(spans={1: (0, 100)}, answers={1: ["dog"]}),
    ])

    async with async_session_factory() as session:
        written = await import_section.import_questions(session, part.id, section_id)
        await session.commit()

    assert written == 1

    async with async_session_factory() as session:
        after_question = await session.get(Question, question.id)
        assert after_question is not None
        assert after_question.correct_answers == ["dog"]

        after_qa = await session.get(QuestionAttempt, qa.id)
        assert after_qa is not None
        assert after_qa.id == qa.id
        assert after_qa.given_answer == "dog"
        # Re-graded against the corrected key: "dog" now matches.
        assert after_qa.is_correct is True

        after_attempt = await session.get(Attempt, attempt.id)
        assert after_attempt is not None
        assert after_attempt.id == attempt.id
        assert after_attempt.score == 1.0
        assert after_attempt.total_questions == 1


async def test_shape_change_still_refuses(tmp_path, monkeypatch) -> None:
    user = await _make_user()
    part = await _make_part(user)
    group = await _seed_group(
        part, spans={1: (0, 100), 2: (200, 300)},
        answers={1: ["cat"], 2: ["dog"]})

    async with async_session_factory() as session:
        questions = {
            q.number: q for q in (await session.exec(
                select(Question).where(Question.group_id == group.id))).all()
        }
    attempt, qa = await _seed_attempt(
        part, user, questions[1], given="cat", correct=True)

    # A third gap appears -- a genuine shape change: the group now has three
    # questions where it had two, so numbers can't be matched 1:1.
    section_id = f"zz-regrade-{uuid.uuid4().hex[:8]}"
    _write_questions_json(tmp_path, monkeypatch, section_id, [
        _form_group_payload(
            spans={1: (0, 100), 2: (200, 300), 3: (400, 500)},
            answers={1: ["cat"], 2: ["dog"], 3: ["bird"]}),
    ])

    async with async_session_factory() as session:
        written = await import_section.import_questions(session, part.id, section_id)
        await session.commit()

    assert written == 0

    async with async_session_factory() as session:
        after_questions = {
            q.number: q for q in (await session.exec(
                select(Question).where(Question.group_id == group.id))).all()
        }
        # Untouched: still two questions, same ids, same spans.
        assert set(after_questions) == {1, 2}
        assert after_questions[1].id == questions[1].id
        assert (after_questions[1].replay_start_ms, after_questions[1].replay_end_ms) == (0, 100)

        after_qa = await session.get(QuestionAttempt, qa.id)
        assert after_qa is not None
        assert after_qa.is_correct is True

        after_attempt = await session.get(Attempt, attempt.id)
        assert after_attempt is not None
        assert after_attempt.score == attempt.score


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
