"""Vocabulary practice: rating, verdicts, the gap, scheduling, and the budget.

Split the way `app/services/practice.py` itself is: the pure functions
(rating table, verdict, gap building, context rotation) are tested with no
database at all, because they are pure -- a fixture would only be noise.
Everything that touches `saved_words`/`vocabulary_review_logs` for real
(FSRS actually running, the daily budget, `forget`, `save`'s dedup) goes
through the real Postgres the rest of the suite uses.
"""

import uuid
from datetime import datetime, timedelta, timezone

import fsrs
import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.material import Material
from app.models.part import Part
from app.models.user import User
from app.models.vocabulary import (
    MaterialVocabulary,
    SavedWord,
    SavedWordContext,
    VocabularyReviewLog,
    VocabularySettings,
)
from app.services import practice as practice_service
from app.services import vocabulary as vocabulary_service

# --- Pure functions: no database ---------------------------------------------


def test_rating_table_matches_the_brief_exactly():
    """One cell per exercise per verdict, spelled out so a change here is a
    change anybody reviewing a diff will actually see."""
    Again, Hard, Good, Easy = (
        fsrs.Rating.Again,
        fsrs.Rating.Hard,
        fsrs.Rating.Good,
        fsrs.Rating.Easy,
    )
    assert practice_service.RATING_TABLE == {
        "recognise": {"correct": Good, "close": Again, "wrong": Again},
        "recall": {"correct": Good, "close": Hard, "wrong": Again},
        "produce": {"correct": Easy, "close": Good, "wrong": Again},
        "listen": {"correct": Good, "close": Hard, "wrong": Again},
    }


def test_rating_for_reads_the_table():
    assert practice_service.rating_for("recall", "correct") == fsrs.Rating.Good
    assert practice_service.rating_for("recall", "close") == fsrs.Rating.Hard
    assert practice_service.rating_for("produce", "correct") == fsrs.Rating.Easy
    assert practice_service.rating_for("recognise", "close") == fsrs.Rating.Again


def test_verdict_exact_match_is_correct():
    assert practice_service.verdict_for("undertaken", "Undertaken") == "correct"
    # Case and surrounding whitespace never matter -- the same rule grading
    # itself uses (`normalize_answer`).
    assert practice_service.verdict_for("  UNDERTAKEN ", "undertaken") == "correct"


def test_verdict_a_spelling_slip_is_close():
    # "necessary" is 9 letters, so up to two edits still counts as a slip
    # rather than a different word (see `mistakes.MAX_SPELLING_EDITS`).
    assert practice_service.verdict_for("neccessary", "necessary") == "close"


def test_verdict_a_plural_slip_is_close():
    assert practice_service.verdict_for("tickets", "ticket") == "close"
    assert practice_service.verdict_for("hectare", "hectares") == "close"


def test_verdict_a_different_word_is_wrong():
    assert practice_service.verdict_for("banana", "undertake") == "wrong"


def test_verdict_an_empty_answer_is_wrong():
    # Not its own bucket -- the brief is explicit that "missed entirely"
    # (the classifier's own name for this) counts as `wrong` here, same as
    # any other verdict the classifier does not call spelling or plural.
    assert practice_service.verdict_for("", "undertake") == "wrong"


def _context(**overrides) -> SavedWordContext:
    defaults = dict(
        id=uuid.uuid4(),
        saved_word_id=uuid.uuid4(),
        material_id=uuid.uuid4(),
        meaning_en="to begin a piece of work",
        meaning_uz="zimmasiga olmoq",
    )
    defaults.update(overrides)
    return SavedWordContext(**defaults)


def test_gap_uses_the_inflected_surface_from_the_sentence():
    word = SavedWord(user_id=uuid.uuid4(), lemma="undertake")
    context = _context(
        surface="Undertaken",
        example="Undertaken carefully, the scheme accommodates two hectares.",
    )
    gap = practice_service.resolve_gap(word, context)
    assert gap.kind == "sentence"
    assert gap.answer == "Undertaken"
    assert gap.before == ""
    assert gap.after == " carefully, the scheme accommodates two hectares."
    # The reveal is where the meaning appears -- the cue is only a letter.
    assert gap.cue == "U"


def test_gap_falls_back_to_the_lemma_when_the_surface_is_stale():
    """The surface stored on the context is not actually IN the example --
    a stale copy, or one that predates a correction. The lemma is tried
    next, in the same sentence, before giving up on it entirely."""
    word = SavedWord(user_id=uuid.uuid4(), lemma="vogue")
    context = _context(
        surface="trend",  # wrong on purpose: not what this context stored
        example="It has long been in vogue among readers.",
    )
    gap = practice_service.resolve_gap(word, context)
    assert gap.kind == "sentence"
    assert gap.answer == "vogue"
    assert gap.before == "It has long been in "
    assert gap.after == " among readers."


def test_gap_fallback_definition_when_the_word_is_nowhere_in_the_sentence():
    word = SavedWord(user_id=uuid.uuid4(), lemma="undertake",
                     meaning_core_en="to begin a piece of work")
    context = _context(surface="xyz", example="A sentence about something else.")
    gap = practice_service.resolve_gap(word, context)
    assert gap.kind == "definition"
    assert gap.answer == "undertake"
    assert gap.before == gap.after == ""
    assert gap.definition == "to begin a piece of work"
    assert gap.cue == "u"


def test_gap_fallback_definition_prefers_word_level_meaning_over_contextual():
    word = SavedWord(user_id=uuid.uuid4(), lemma="claim",
                     meaning_core_en="a demand for something you have a right to")
    context = _context(meaning_en="a statement made without proof")
    gap = practice_service.resolve_gap(word, None)
    assert gap.definition == "a demand for something you have a right to"

    # With no word-level meaning at all, the CONTEXT's own sense stands in --
    # "meaning_core_en, else contextual", per the brief.
    bare = SavedWord(user_id=uuid.uuid4(), lemma="claim")
    gap2 = practice_service.resolve_gap(bare, context)
    assert gap2.definition == "a statement made without proof"


def test_gap_with_no_context_at_all_is_the_definition_fallback():
    word = SavedWord(user_id=uuid.uuid4(), lemma="undertake",
                     meaning_core_en="to begin a piece of work")
    gap = practice_service.resolve_gap(word, None)
    assert gap.kind == "definition"
    assert gap.answer == "undertake"


def test_context_rotation_is_least_recently_used_ties_broken_by_newest():
    saved_word_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    old = _context(saved_word_id=saved_word_id, created_at=now - timedelta(days=5))
    newer = _context(saved_word_id=saved_word_id, created_at=now - timedelta(days=1))
    contexts = [old, newer]

    # Neither has ever been reviewed -- "the newest context the first time"
    # is the SAME rule as the tie-break, not a special case of it.
    assert practice_service._pick_context(contexts, {}) is newer

    # `old` was used recently; `newer` was used longer ago and so is the
    # LEAST recently used -- it wins.
    assert (
        practice_service._pick_context(
            contexts, {old.id: now, newer.id: now - timedelta(days=10)}
        )
        is newer
    )

    # Swap which one was used recently: the answer swaps with it.
    assert (
        practice_service._pick_context(
            contexts, {old.id: now - timedelta(days=10), newer.id: now}
        )
        is old
    )


# --- Against the real database -----------------------------------------------


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        found = (await session.exec(select(User).where(User.email == email))).first()
        if found is not None:
            return found
        user = User(email=email, display_name=f"Practice test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_material(author_id: uuid.UUID, title: str) -> Material:
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id, type="reading", title=title, visibility="public"
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)
        return material


async def _make_part(material_id: uuid.UUID) -> Part:
    async with async_session_factory() as session:
        part = Part(material_id=material_id, order_index=0, title="Part 1")
        session.add(part)
        await session.commit()
        await session.refresh(part)
        return part


async def _make_saved_word(user_id: uuid.UUID, lemma: str, **fields) -> SavedWord:
    async with async_session_factory() as session:
        word = SavedWord(user_id=user_id, lemma=lemma, **fields)
        session.add(word)
        await session.commit()
        await session.refresh(word)
        return word


async def _make_context(
    saved_word_id: uuid.UUID, material_id: uuid.UUID, **fields
) -> SavedWordContext:
    fields.setdefault("meaning_en", "to begin a piece of work")
    fields.setdefault("meaning_uz", "zimmasiga olmoq")
    async with async_session_factory() as session:
        context = SavedWordContext(
            saved_word_id=saved_word_id, material_id=material_id, **fields
        )
        session.add(context)
        await session.commit()
        await session.refresh(context)
        return context


async def _reload(word_id: uuid.UUID) -> SavedWord:
    async with async_session_factory() as session:
        word = await session.get(SavedWord, word_id)
        assert word is not None
        return word


async def _cleanup(*, user_ids=(), material_ids=()) -> None:
    async with async_session_factory() as session:
        for user_id in user_ids:
            for row in (
                await session.exec(
                    select(VocabularyReviewLog).where(
                        VocabularyReviewLog.user_id == user_id
                    )
                )
            ).all():
                await session.delete(row)
        await session.flush()
        for material_id in material_ids:
            for row in (
                await session.exec(
                    select(SavedWordContext).where(
                        SavedWordContext.material_id == material_id
                    )
                )
            ).all():
                await session.delete(row)
            for row in (
                await session.exec(
                    select(MaterialVocabulary).where(
                        MaterialVocabulary.material_id == material_id
                    )
                )
            ).all():
                await session.delete(row)
        await session.flush()
        for user_id in user_ids:
            for row in (
                await session.exec(
                    select(SavedWord).where(SavedWord.user_id == user_id)
                )
            ).all():
                await session.delete(row)
            settings = await session.get(VocabularySettings, user_id)
            if settings is not None:
                await session.delete(settings)
        await session.flush()
        for material_id in material_ids:
            for row in (
                await session.exec(
                    select(Part).where(Part.material_id == material_id)
                )
            ).all():
                await session.delete(row)
        await session.flush()
        for material_id in material_ids:
            material = await session.get(Material, material_id)
            if material is not None:
                await session.delete(material)
        await session.flush()
        for user_id in user_ids:
            user = await session.get(User, user_id)
            if user is not None:
                await session.delete(user)
        await session.commit()


@pytest.mark.asyncio
async def test_a_wrong_answer_on_a_new_word_returns_it_and_schedules_ten_minutes():
    """`Again` on a never-practised word: no lapse (it was never in Review),
    `returns_this_session` true, and a card due back in the plan's single
    10-minute learning step."""
    email = f"practice-again-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Practice: again")
    word = await _make_saved_word(user.id, "undertake")
    context = await _make_context(
        word.id, material.id,
        surface="Undertaken",
        example="Undertaken carefully, the team finished the project.",
    )
    try:
        async with async_session_factory() as session:
            result = await practice_service.record_answer(
                session, user,
                word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                given="completely wrong", elapsed_ms=4000,
            )
        assert result["verdict"] == "wrong"
        assert result["rating"] == int(fsrs.Rating.Again)
        assert result["returns_this_session"] is True
        assert result["answer"] == "Undertaken"

        due_in = result["next_due_at"] - datetime.now(timezone.utc)
        assert timedelta(minutes=9) < due_in < timedelta(minutes=11)

        reloaded = await _reload(word.id)
        assert reloaded.status == "learning"
        assert reloaded.lapses == 0  # never reached Review, so not a lapse
        assert reloaded.reps == 1
        assert reloaded.passive_state == int(fsrs.State.Learning)

        # The client re-queues it and answers again within the same
        # sitting -- this time correctly.
        async with async_session_factory() as session:
            second = await practice_service.record_answer(
                session, user,
                word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                given="Undertaken", elapsed_ms=3000,
            )
        assert second["verdict"] == "correct"
        assert second["returns_this_session"] is False

        again = await _reload(word.id)
        assert again.status == "review"  # the last learning step promotes it
        assert again.reps == 2  # every answer counts, not only the wrong one
        assert again.lapses == 0
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


@pytest.mark.asyncio
async def test_a_lapse_is_only_a_review_state_card_failing():
    """A card already in Review, answered Again, is a lapse -- and is sent
    to relearning for the same 10 minutes as a fresh card, never a shrunk
    interval."""
    email = f"practice-lapse-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(
        user.id, "accommodate",
        status="review",
        passive_state=int(fsrs.State.Review),
        passive_stability=12.0,
        passive_difficulty=5.0,
        passive_due=now - timedelta(days=1),
        passive_last_review=now - timedelta(days=13),
    )
    try:
        async with async_session_factory() as session:
            result = await practice_service.record_answer(
                session, user,
                word_id=word.id, context_id=None,
                direction="passive", exercise_type="recall",
                given="nothing like it", elapsed_ms=5000,
            )
        assert result["rating"] == int(fsrs.Rating.Again)
        # The schedule this answer is judged against is the card's real,
        # thirteen-day-old due date -- not null, because this card DID have
        # a history.
        assert result["next_due_at"] - datetime.now(timezone.utc) < timedelta(
            minutes=11
        )

        reloaded = await _reload(word.id)
        assert reloaded.lapses == 1
        assert reloaded.reps == 1
        assert reloaded.status == "learning"  # Relearning counts as learning
        assert reloaded.passive_state == int(fsrs.State.Relearning)
        # Stability dropped (FSRS's own penalty) rather than being halved by
        # anything of ours -- just checking it moved, not by how much, since
        # the exact value is the library's to decide.
        assert reloaded.passive_stability < 12.0
    finally:
        await _cleanup(user_ids=[user.id])


@pytest.mark.asyncio
async def test_budget_planning_lets_reviews_crowd_out_new_words():
    """The whole point of a TIME budget: pile up quiet, overdue reviews and
    watch new-word intake shrink to nothing without anybody choosing a cap."""
    email = f"practice-budget-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)

    # Twenty answers slow enough to pull the running average up to 30s --
    # dated two days ago, so they feed the AVERAGE without counting as time
    # spent TODAY.
    async with async_session_factory() as session:
        for _ in range(20):
            session.add(
                VocabularyReviewLog(
                    user_id=user.id,
                    lemma="filler",
                    direction="passive",
                    exercise_type="recall",
                    rating=int(fsrs.Rating.Good),
                    elapsed_ms=30_000,
                    reviewed_at=now - timedelta(days=2),
                    state=int(fsrs.State.Review),
                )
            )
        await session.commit()

    # Fifteen overdue reviews, ten minutes apart, so the most-overdue-first
    # order is checkable; five words never practised.
    due_words = [
        await _make_saved_word(
            user.id, f"due-word-{i}",
            status="review",
            passive_state=int(fsrs.State.Review),
            passive_stability=5.0,
            passive_difficulty=5.0,
            passive_due=now - timedelta(minutes=(15 - i) * 10),
            passive_last_review=now - timedelta(days=10),
        )
        for i in range(15)
    ]
    for i in range(5):
        await _make_saved_word(user.id, f"new-word-{i}")

    try:
        async with async_session_factory() as session:
            await practice_service.set_daily_minutes(session, user.id, 5)

        async with async_session_factory() as session:
            plan = await practice_service.summary(session, user, tz=None)

        assert plan["daily_minutes"] == 5
        assert plan["avg_seconds"] == 30.0
        assert plan["due_now"] == 15
        assert plan["new_available"] == 5
        # budget = 300s; 300 // 30 = 10 reviews; nothing left for new words.
        assert plan["planned_reviews"] == 10
        assert plan["planned_new"] == 0

        async with async_session_factory() as session:
            items = await practice_service.build_session(session, user, tz=None)

        assert len(items) == 10
        assert all(item["is_new"] is False for item in items)
        # Most overdue first: `due-word-0`, whose `passive_due` is the
        # earliest of the fifteen.
        assert items[0]["lemma"] == "due-word-0"
    finally:
        await _cleanup(user_ids=[user.id])


@pytest.mark.asyncio
async def test_forgetting_a_word_keeps_the_logs_it_produced():
    """`forget` deletes the word and its contexts; the training data a
    lapse or a correct answer produced is not the forget button's to
    erase."""
    email = f"practice-forget-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Practice: forget")
    word = await _make_saved_word(user.id, "vogue")
    context = await _make_context(
        word.id, material.id, surface="vogue", example="It is in vogue again."
    )
    try:
        async with async_session_factory() as session:
            await practice_service.record_answer(
                session, user,
                word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                given="vogue", elapsed_ms=2000,
            )

        async with async_session_factory() as session:
            logs_before = (
                await session.exec(
                    select(VocabularyReviewLog).where(
                        VocabularyReviewLog.user_id == user.id
                    )
                )
            ).all()
        assert len(logs_before) == 1
        assert logs_before[0].saved_word_id == word.id

        async with async_session_factory() as session:
            gone = await vocabulary_service.forget(session, user.id, "vogue")
        assert gone is True

        async with async_session_factory() as session:
            logs_after = (
                await session.exec(
                    select(VocabularyReviewLog).where(
                        VocabularyReviewLog.user_id == user.id
                    )
                )
            ).all()
        assert len(logs_after) == 1
        assert logs_after[0].id == logs_before[0].id
        assert logs_after[0].lemma == "vogue"
        # The pointer went null; the word it once named did not.
        assert logs_after[0].saved_word_id is None
        assert logs_after[0].context_id is None
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


@pytest.mark.asyncio
async def test_saving_a_word_fills_its_core_meaning_once_not_on_every_material():
    email = f"practice-save-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    first = await _make_material(user.id, "Practice: save (first)")
    second = await _make_material(user.id, "Practice: save (second)")
    first_part = await _make_part(first.id)
    second_part = await _make_part(second.id)
    try:
        async with async_session_factory() as session:
            # No `meaning_core_en` yet -- an entry from before that column
            # was enriched -- so the fallback to the contextual meaning is
            # what has to reach the saved word.
            session.add(
                MaterialVocabulary(
                    material_id=first.id, part_id=first_part.id,
                    lemma="threshold", surface="threshold", pos="n",
                    meaning_en="a point that must be crossed for something "
                              "to happen",
                    meaning_uz="chegara", cefr_level="B2",
                )
            )
            session.add(
                MaterialVocabulary(
                    material_id=second.id, part_id=second_part.id,
                    lemma="threshold", surface="thresholds", pos="n",
                    meaning_core_en="a DIFFERENT usual meaning entirely",
                    meaning_core_uz="boshqa asosiy ma'no",
                    meaning_en="a different contextual sense",
                    meaning_uz="boshqa ma'no", cefr_level="B2",
                )
            )
            await session.commit()

        async with async_session_factory() as session:
            await vocabulary_service.save(
                session, user_id=user.id, material_id=first.id,
                lemmas=["threshold"],
            )

        async with async_session_factory() as session:
            saved = (
                await session.exec(
                    select(SavedWord).where(
                        SavedWord.user_id == user.id, SavedWord.lemma == "threshold"
                    )
                )
            ).one()
            assert saved.pos == "n"
            # Fell back to the contextual meaning, because the entry had no
            # usual one.
            assert saved.meaning_core_en == (
                "a point that must be crossed for something to happen"
            )
            assert saved.meaning_core_uz == "chegara"

        # A second save, from a material whose entry has a DIFFERENT core
        # meaning, must not touch what the learner already has.
        async with async_session_factory() as session:
            await vocabulary_service.save(
                session, user_id=user.id, material_id=second.id,
                lemmas=["threshold"],
            )

        async with async_session_factory() as session:
            saved_again = (
                await session.exec(
                    select(SavedWord).where(
                        SavedWord.user_id == user.id, SavedWord.lemma == "threshold"
                    )
                )
            ).one()
            assert saved_again.meaning_core_en == (
                "a point that must be crossed for something to happen"
            )
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[first.id, second.id])
