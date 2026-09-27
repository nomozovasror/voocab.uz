"""Vocabulary practice: rating, verdicts, the gap, scheduling, and the budget.

Split the way `app/services/practice.py` itself is: the pure functions
(rating table, verdict, gap building, context rotation) are tested with no
database at all, because they are pure -- a fixture would only be noise.
Everything that touches `saved_words`/`vocabulary_review_logs` for real
(FSRS actually running, the daily budget, `forget`, `save`'s dedup) goes
through the real Postgres the rest of the suite uses.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

import fsrs
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func
from sqlmodel import select

from app.api.vocabulary import _saved_word_out
from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense
from app.models.material import Material
from app.models.part import Part
from app.models.user import User
from app.models.vocabulary import (
    ACTIVE_LADDER,
    PASSIVE_LADDER,
    MaterialVocabulary,
    SavedWord,
    SavedWordContext,
    VocabularyReviewLog,
    VocabularySettings,
)
from app.schemas.vocabulary import VocabularySettingsIn
from app.services import distractors
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
    """A saved word, with a real `LexemeSense` behind it (P4:
    `lexeme_sense_id` is NOT NULL) -- built fresh, one per call, unless the
    caller already has one to reuse (`lexeme_sense_id=...`). Its
    `definition_en`/`meaning_uz` mirror whatever `meaning_core_en`/
    `meaning_core_uz` the caller passed, so every existing assertion about
    "the word's usual meaning" keeps holding whether it happens to read the
    dead column or the live sense.
    """
    async with async_session_factory() as session:
        sense_id = fields.pop("lexeme_sense_id", None)
        if sense_id is None:
            pos = fields.get("pos", "") or ""
            # Found first, not blindly created: two calls for the SAME
            # lemma (two users saving "shared-lemma", or a second word on
            # the same one) must not collide on `uq_lexeme_lemma_pos` --
            # the same find-or-create shape `app.services.lexicon.link_row`
            # itself uses.
            lexeme = (
                await session.exec(
                    select(Lexeme).where(Lexeme.lemma == lemma, Lexeme.pos == pos)
                )
            ).first()
            if lexeme is None:
                lexeme = Lexeme(lemma=lemma, pos=pos)
                session.add(lexeme)
                await session.flush()
            existing_senses = (
                await session.exec(
                    select(func.count(LexemeSense.id)).where(
                        LexemeSense.lexeme_id == lexeme.id
                    )
                )
            ).one()
            sense = LexemeSense(
                lexeme_id=lexeme.id, sense_rank=existing_senses + 1,
                definition_en=fields.get("meaning_core_en", "") or "",
                meaning_uz=fields.get("meaning_core_uz", "") or "",
            )
            session.add(sense)
            await session.flush()
            sense_id = sense.id
        word = SavedWord(
            user_id=user_id, lemma=lemma, lexeme_sense_id=sense_id, **fields
        )
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


async def _make_vocab_entry(
    material_id: uuid.UUID, part_id: uuid.UUID, *, lemma: str, **fields
) -> MaterialVocabulary:
    defaults = dict(pos="n", meaning_en="a plain definition", meaning_uz="tarjima",
                    cefr_level="B2")
    defaults.update(fields)
    async with async_session_factory() as session:
        entry = MaterialVocabulary(
            material_id=material_id, part_id=part_id, lemma=lemma, surface=lemma,
            **defaults,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return entry


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
        # `_make_saved_word` mints a fresh `Lexeme`/`LexemeSense` per call
        # (P4: `lexeme_sense_id` is NOT NULL) -- collected here, before the
        # words themselves go, so a lemma this run made up (`"intransigent"`,
        # `"shared-lemma"`, ...) does not collide with the next run's use of
        # the same word: `(lemma, pos)` is globally unique on `lexemes`.
        sense_ids: set[uuid.UUID] = set()
        for user_id in user_ids:
            for word in (
                await session.exec(
                    select(SavedWord).where(SavedWord.user_id == user_id)
                )
            ).all():
                sense_ids.add(word.lexeme_sense_id)
                await session.delete(word)
            settings = await session.get(VocabularySettings, user_id)
            if settings is not None:
                await session.delete(settings)
        await session.flush()
        lexeme_ids: set[uuid.UUID] = set()
        for sense_id in sense_ids:
            sense = await session.get(LexemeSense, sense_id)
            if sense is not None:
                lexeme_ids.add(sense.lexeme_id)
                await session.delete(sense)
        await session.flush()
        for lexeme_id in lexeme_ids:
            remaining = (
                await session.exec(
                    select(func.count(LexemeSense.id)).where(
                        LexemeSense.lexeme_id == lexeme_id
                    )
                )
            ).one()
            if remaining:
                continue  # another sense (outside this cleanup) still uses it
            lexeme = await session.get(Lexeme, lexeme_id)
            if lexeme is not None:
                await session.delete(lexeme)
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
            gone = await vocabulary_service.forget(session, user.id, word.id)
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
async def test_saving_a_word_twice_finds_the_same_sense_and_does_not_split():
    """P4: a saved word is one SENSE, not one lemma. Two materials glossing
    `threshold` with the same wording resolve to the same `LexemeSense`
    (`link_row`'s own dedup-by-wording rule) and therefore the same saved
    word -- the context list grows, the word's identity and its live usual
    meaning do not move. (Two materials glossing a lemma with a genuinely
    DIFFERENT meaning are a different sense and a different word -- see
    `test_vocabulary.py`'s own save/split coverage for that half.)
    """
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
            # what `link_row` builds the sense from, and the SAME wording on
            # the second row is what makes it resolve to the SAME sense.
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
                    meaning_en="A point that must be crossed for something "
                              "to happen!",
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
            sense = await session.get(LexemeSense, saved.lexeme_sense_id)
            # Fell back to the contextual meaning, because the entry had no
            # usual one of its own.
            assert sense.definition_en == (
                "a point that must be crossed for something to happen"
            )
            assert sense.meaning_uz == "chegara"

        # A second save, from a material whose entry glosses the SAME
        # meaning in different words, must find the same sense and the same
        # word -- not split it, and not touch what is already there.
        async with async_session_factory() as session:
            await vocabulary_service.save(
                session, user_id=user.id, material_id=second.id,
                lemmas=["threshold"],
            )

        async with async_session_factory() as session:
            words = (
                await session.exec(
                    select(SavedWord).where(
                        SavedWord.user_id == user.id, SavedWord.lemma == "threshold"
                    )
                )
            ).all()
            assert len(words) == 1
            saved_again = words[0]
            assert saved_again.id == saved.id
            sense_again = await session.get(LexemeSense, saved_again.lexeme_sense_id)
            assert sense_again.id == sense.id
            assert sense_again.definition_en == (
                "a point that must be crossed for something to happen"
            )
            contexts = (
                await session.exec(
                    select(SavedWordContext).where(
                        SavedWordContext.saved_word_id == saved.id
                    )
                )
            ).all()
            assert {c.material_id for c in contexts} == {first.id, second.id}
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[first.id, second.id])


# --- The ladder ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_ladder_promotes_after_two_consecutive_corrects_at_the_floor():
    email = f"ladder-promote-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Ladder: promote")
    word = await _make_saved_word(user.id, "lumen")
    context = await _make_context(
        word.id, material.id, surface="lumen",
        example="A lumen measures the light a bulb gives off.",
    )
    try:
        async with async_session_factory() as session:
            first = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                planned_exercise="recognise", given="lumen", elapsed_ms=1500,
            )
        # One correct is not enough yet.
        assert first["level"] == "recognise"
        assert (await _reload(word.id)).passive_level == "recognise"

        async with async_session_factory() as session:
            second = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                planned_exercise="recognise", given="lumen", elapsed_ms=1500,
            )
        assert second["level"] == "recall"
        assert (await _reload(word.id)).passive_level == "recall"
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


@pytest.mark.asyncio
async def test_ladder_re_promotes_after_one_correct_once_it_has_been_demoted():
    email = f"ladder-repromote-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Ladder: re-promote")
    word = await _make_saved_word(user.id, "lumen")
    context = await _make_context(
        word.id, material.id, surface="lumen", example="A lumen measures light.",
    )
    try:
        # Promote to `recall` the ordinary way.
        for _ in range(2):
            async with async_session_factory() as session:
                await practice_service.record_answer(
                    session, user, word_id=word.id, context_id=context.id,
                    direction="passive", exercise_type="recall",
                    planned_exercise="recognise", given="lumen", elapsed_ms=1000,
                )
        assert (await _reload(word.id)).passive_level == "recall"

        # Demote: an Again at the top rung.
        async with async_session_factory() as session:
            await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                planned_exercise="recall", given="completely wrong",
                elapsed_ms=1000,
            )
        assert (await _reload(word.id)).passive_level == "recognise"

        # It has been at `recall` before, so ONE correct is enough this time.
        async with async_session_factory() as session:
            result = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                planned_exercise="recognise", given="lumen", elapsed_ms=1000,
            )
        assert result["level"] == "recall"
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


@pytest.mark.asyncio
async def test_hard_does_not_demote_the_top_rung():
    email = f"ladder-hard-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(
        user.id, "accommodate", status="review", passive_level="recall",
        passive_state=int(fsrs.State.Review), passive_stability=12.0,
        passive_difficulty=5.0, passive_due=now - timedelta(days=1),
        passive_last_review=now - timedelta(days=13),
    )
    try:
        async with async_session_factory() as session:
            result = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=None,
                direction="passive", exercise_type="recall",
                planned_exercise="recall", given="acommodate",  # one letter short
                elapsed_ms=3000,
            )
        assert result["rating"] == int(fsrs.Rating.Hard)  # a spelling slip, not Again
        assert result["level"] == "recall"
        assert (await _reload(word.id)).passive_level == "recall"
    finally:
        await _cleanup(user_ids=[user.id])


# --- Active unlock -------------------------------------------------------------


@pytest.mark.asyncio
async def test_active_unlocks_only_with_direction_both_and_stability_21_days():
    email = f"active-unlock-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    stable = await _make_saved_word(
        user.id, "stable-word", status="review",
        passive_state=int(fsrs.State.Review), passive_stability=25.0,
        passive_due=now + timedelta(days=5),
    )
    unstable = await _make_saved_word(
        user.id, "unstable-word", status="review",
        passive_state=int(fsrs.State.Review), passive_stability=5.0,
        passive_due=now + timedelta(days=5),
    )
    try:
        async with async_session_factory() as session:
            candidates = await practice_service._active_unlock_candidates(
                session, user.id
            )
        lemmas = {word.lemma for word in candidates}
        assert "stable-word" in lemmas
        assert "unstable-word" not in lemmas

        # `direction` defaults to `passive` -- no active-unlock candidate
        # reaches the queue at all.
        async with async_session_factory() as session:
            settings = await practice_service.get_settings(session, user.id)
            _due, new = await practice_service._gather_candidates(
                session, user, settings, mode="auto", material_id=None
            )
        assert not any(c.direction == "active" for c in new)

        async with async_session_factory() as session:
            await practice_service.update_settings(
                session, user.id, daily_minutes=10, direction="both",
                exercise_types=None,
            )

        async with async_session_factory() as session:
            settings = await practice_service.get_settings(session, user.id)
            _due, new = await practice_service._gather_candidates(
                session, user, settings, mode="auto", material_id=None
            )
        active_new = {c.word.lemma for c in new if c.direction == "active"}
        assert active_new == {"stable-word"}
    finally:
        await _cleanup(user_ids=[user.id])


# --- One word, one slot ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_word_never_appears_twice_in_one_session():
    email = f"one-slot-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(
        user.id, "dual-due", status="review",
        passive_state=int(fsrs.State.Review), passive_stability=25.0,
        passive_due=now - timedelta(minutes=10),
        active_level="produce",
        active_state=int(fsrs.State.Review), active_stability=25.0,
        active_due=now - timedelta(minutes=1),
    )
    try:
        # `direction: "both"` -- otherwise the active card is paused and
        # never reaches the dedup logic this test is actually about.
        async with async_session_factory() as session:
            await practice_service.update_settings(
                session, user.id, daily_minutes=20, direction="both",
                exercise_types=None,
            )
        async with async_session_factory() as session:
            items = await practice_service.build_session(session, user, tz=None)
        assert len(items) == 1
        assert items[0]["lemma"] == "dual-due"
        # More overdue wins -- the passive due date is further in the past.
        assert items[0]["direction"] == "passive"
    finally:
        await _cleanup(user_ids=[user.id])


# --- Mode -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mode_takes_only_cards_at_the_matching_level():
    email = f"mode-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    recognise_word = await _make_saved_word(
        user.id, "recognise-word", status="review", passive_level="recognise",
        passive_state=int(fsrs.State.Review), passive_stability=5.0,
        passive_due=now - timedelta(minutes=5),
    )
    recall_word = await _make_saved_word(
        user.id, "recall-word", status="review", passive_level="recall",
        passive_state=int(fsrs.State.Review), passive_stability=5.0,
        passive_due=now - timedelta(minutes=5),
    )
    try:
        async with async_session_factory() as session:
            await practice_service.set_daily_minutes(session, user.id, 20)
        async with async_session_factory() as session:
            items = await practice_service.build_session(
                session, user, tz=None, mode="recall"
            )
        lemmas = {item["lemma"] for item in items}
        assert lemmas == {"recall-word"}
        assert all(item["planned_exercise"] == "recall" for item in items)
    finally:
        await _cleanup(user_ids=[user.id])


# --- Distractors -----------------------------------------------------------


def test_option_id_does_not_reveal_the_answer():
    word_id = uuid.uuid4()
    right = distractors.option_id(word_id, "the correct definition")
    wrong = distractors.option_id(word_id, "a distractor definition")
    assert right != wrong
    assert len(right) == 16
    assert "correct" not in right
    # Deterministic in (word_id, text), which is what lets an answer be
    # graded by recomputing the right id rather than storing anything.
    assert distractors.option_id(word_id, "the correct definition") == right
    # But scoped to the word, so the same text means a different id for a
    # different word.
    assert distractors.option_id(uuid.uuid4(), "the correct definition") != right


@pytest.mark.asyncio
async def test_distractor_candidates_filter_by_pos_and_cefr():
    email = f"distractor-filter-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Distractors: filter")
    part = await _make_part(material.id)
    try:
        await _make_vocab_entry(material.id, part.id, lemma="ally", pos="n",
                                 cefr_level="B2",
                                 meaning_en="a country that supports another")
        await _make_vocab_entry(material.id, part.id, lemma="quickly", pos="adv",
                                 cefr_level="B2", meaning_en="done at speed")
        await _make_vocab_entry(material.id, part.id, lemma="entity", pos="n",
                                 cefr_level="C2",
                                 meaning_en="a distinct independent thing")
        async with async_session_factory() as session:
            found = await distractors._candidates(
                session, pos="n", cefr_level="B2", exclude_lemma="alliance",
                family_keys=frozenset(),
            )
        lemmas = {entry.lemma for entry in found}
        assert "ally" in lemmas
        assert "quickly" not in lemmas  # wrong part of speech
        assert "entity" not in lemmas  # two CEFR levels away
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


@pytest.mark.asyncio
async def test_distractor_pipeline_prefers_the_source_material():
    email = f"distractor-source-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    source = await _make_material(user.id, "Distractors: source")
    other = await _make_material(user.id, "Distractors: other")
    source_part = await _make_part(source.id)
    other_part = await _make_part(other.id)
    try:
        await _make_vocab_entry(source.id, source_part.id, lemma="ally", pos="n",
                                 cefr_level="B2",
                                 meaning_en="a country that supports another")
        await _make_vocab_entry(other.id, other_part.id, lemma="rival", pos="n",
                                 cefr_level="B2",
                                 meaning_en="somebody competing for the same prize")
        await _make_vocab_entry(other.id, other_part.id, lemma="colleague", pos="n",
                                 cefr_level="B2", meaning_en="somebody you work with")
        await _make_vocab_entry(other.id, other_part.id, lemma="outcome", pos="n",
                                 cefr_level="B2",
                                 meaning_en="the result of an action or event")

        async with async_session_factory() as session:
            built = await distractors.build(
                session, word_id=uuid.uuid4(),
                right_text="a formal agreement between two or more countries",
                right_definition="a formal agreement between two or more countries",
                pos="n", cefr_level="B2", source_material_ids=frozenset({source.id}),
                family_keys=frozenset(), exclude_lemma="alliance",
                option_field="definition", rng_seed=1,
            )
        assert built.fallback_reason is None
        assert len(built.options) == 4  # right + 3 distractors
        # `ally` is the only candidate from the source material, and the
        # source always sorts first -- it is never the one left out when
        # there are more eligible candidates than slots.
        texts = {option.text for option in built.options}
        assert any("country that supports" in text for text in texts)
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[source.id, other.id])


@pytest.mark.asyncio
async def test_distractor_pipeline_excludes_the_learning_family():
    email = f"distractor-family-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Distractors: family")
    part = await _make_part(material.id)
    try:
        await _make_vocab_entry(material.id, part.id, lemma="emergence", pos="n",
                                 cefr_level="B2",
                                 meaning_en="the process of coming into being")
        await _make_vocab_entry(material.id, part.id, lemma="occasion", pos="n",
                                 cefr_level="B2",
                                 meaning_en="a particular time something happens")
        await _make_vocab_entry(material.id, part.id, lemma="incident", pos="n",
                                 cefr_level="B2",
                                 meaning_en="an event, especially an unpleasant one")

        async with async_session_factory() as session:
            found = await distractors._candidates(
                session, pos="n", cefr_level="B2", exclude_lemma="rise",
                family_keys=frozenset({distractors.family_key("emerge")}),
            )
        lemmas = {entry.lemma for entry in found}
        assert "emergence" not in lemmas  # shares `emerge`'s family
        assert "occasion" in lemmas
        assert "incident" in lemmas
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


@pytest.mark.asyncio
async def test_distractor_guard_drops_near_duplicate_definitions():
    email = f"distractor-guard-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Distractors: guard")
    part = await _make_part(material.id)
    try:
        # Shares "formal", "agreement" and "countries" with the right
        # definition -- a second correct answer, not a wrong one.
        await _make_vocab_entry(material.id, part.id, lemma="pact", pos="n",
                                 cefr_level="B2",
                                 meaning_en="a formal agreement between two countries")
        await _make_vocab_entry(material.id, part.id, lemma="rival", pos="n",
                                 cefr_level="B2",
                                 meaning_en="somebody competing for the same prize")
        await _make_vocab_entry(material.id, part.id, lemma="colleague", pos="n",
                                 cefr_level="B2", meaning_en="somebody you work with")
        await _make_vocab_entry(material.id, part.id, lemma="outcome", pos="n",
                                 cefr_level="B2",
                                 meaning_en="the result of an action or event")

        async with async_session_factory() as session:
            built = await distractors.build(
                session, word_id=uuid.uuid4(),
                right_text="a formal agreement between two or more countries",
                right_definition="a formal agreement between two or more countries",
                pos="n", cefr_level="B2", source_material_ids=frozenset(),
                family_keys=frozenset(), exclude_lemma="alliance",
                option_field="definition", rng_seed=1,
            )
        assert built.fallback_reason is None
        texts = {option.text for option in built.options}
        assert not any("two countries" in text for text in texts)  # `pact` dropped
        assert len(built.options) == 4
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


@pytest.mark.asyncio
async def test_distractor_reads_the_candidates_sense_when_meaning_core_is_empty():
    """A candidate written since P3 carries no `meaning_core_en` of its own
    (see `link_row`'s docstring) -- its distractor text must come from its
    own `LexemeSense.definition_en`, the same fallback order as the API's
    `_entry()` shim, not from `meaning_en` (the per-material CONTEXTUAL
    gloss), which would show a plausible-but-wrong distractor built from
    the wrong field entirely.
    """
    email = f"distractor-sense-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Distractors: sense fallback")
    part = await _make_part(material.id)
    try:
        lexeme = Lexeme(lemma="rival", pos="n")
        async with async_session_factory() as session:
            session.add(lexeme)
            await session.commit()
            await session.refresh(lexeme)
            sense = LexemeSense(
                lexeme_id=lexeme.id, sense_rank=1,
                definition_en="somebody competing for the same prize",
                meaning_uz="raqib",
            )
            session.add(sense)
            await session.commit()
            await session.refresh(sense)

        await _make_vocab_entry(
            material.id, part.id, lemma="rival", pos="n", cefr_level="B2",
            # `meaning_core_en` empty (a row written since P3); `meaning_en`
            # is a CONTEXTUAL gloss that must NOT be what a distractor shows.
            meaning_core_en="", meaning_en="the material's own contextual gloss",
            lexeme_id=lexeme.id, sense_id=sense.id,
        )
        await _make_vocab_entry(material.id, part.id, lemma="colleague", pos="n",
                                 cefr_level="B2", meaning_en="somebody you work with")
        await _make_vocab_entry(material.id, part.id, lemma="outcome", pos="n",
                                 cefr_level="B2",
                                 meaning_en="the result of an action or event")

        async with async_session_factory() as session:
            built = await distractors.build(
                session, word_id=uuid.uuid4(),
                right_text="a formal agreement between two or more countries",
                right_definition="a formal agreement between two or more countries",
                # The source material ranks first, so the three rows made
                # here are the ones chosen even on a shared database that
                # already holds other B2 nouns.
                pos="n", cefr_level="B2",
                source_material_ids=frozenset({material.id}),
                family_keys=frozenset(), exclude_lemma="alliance",
                option_field="definition", rng_seed=1,
            )
        assert built.fallback_reason is None
        texts = {option.text for option in built.options}
        assert any("competing for the same prize" in text for text in texts)
        assert not any("contextual gloss" in text for text in texts)
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])
        async with async_session_factory() as session:
            db_sense = (
                await session.exec(
                    select(LexemeSense).where(LexemeSense.lexeme_id == lexeme.id)
                )
            ).first()
            if db_sense is not None:
                await session.delete(db_sense)
            await session.flush()
            db_lexeme = await session.get(Lexeme, lexeme.id)
            if db_lexeme is not None:
                await session.delete(db_lexeme)
            await session.commit()


@pytest.mark.asyncio
async def test_distractor_fallback_on_a_short_definition():
    async with async_session_factory() as session:
        built = await distractors.build(
            session, word_id=uuid.uuid4(), right_text="go", right_definition="go",
            pos="v", cefr_level="B1", source_material_ids=frozenset(),
            family_keys=frozenset(), exclude_lemma="go", option_field="definition",
            rng_seed=1,
        )
    assert built.options is None
    assert built.fallback_reason == "short_definition"


@pytest.mark.asyncio
async def test_distractor_fallback_on_too_few_candidates():
    async with async_session_factory() as session:
        built = await distractors.build(
            session, word_id=uuid.uuid4(),
            right_text="a lasting arrangement between two allies",
            right_definition="a lasting arrangement between two allies",
            pos="a-part-of-speech-nothing-uses", cefr_level="B2",
            source_material_ids=frozenset(), family_keys=frozenset(),
            exclude_lemma="alliance", option_field="definition", rng_seed=1,
        )
    assert built.options is None
    assert built.fallback_reason == "too_few_candidates"


@pytest.mark.asyncio
async def test_recognise_fallback_in_session_is_measurable_and_logged(caplog):
    email = f"fallback-session-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Fallback: session")
    word = await _make_saved_word(
        user.id, "zzz-obscure-lemma",
        meaning_core_en="a suitably long definition nobody else shares",
    )
    context = await _make_context(
        word.id, material.id, surface="zzz-obscure-lemma",
        example="We studied zzz-obscure-lemma carefully in class.",
    )
    try:
        async with async_session_factory() as session:
            await practice_service.set_daily_minutes(session, user.id, 10)
        with caplog.at_level(logging.INFO, logger="app.services.practice"):
            async with async_session_factory() as session:
                items = await practice_service.build_session(session, user, tz=None)
        assert len(items) == 1
        item = items[0]
        # No catalogue candidate shares this word's invented pos/definition,
        # so the pipeline falls back -- served harder, never with bad
        # options, and the mismatch IS the measurement.
        assert item["planned_exercise"] == "recognise"
        assert item["exercise_type"] == "recall"
        reasons = {
            getattr(record, "reason", None) for record in caplog.records
            if record.message == "vocabulary distractor fallback"
        }
        assert reasons == {"too_few_candidates"}
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


# --- Produce ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_produce_accepts_the_lemma_and_every_context_surface():
    email = f"produce-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Produce: accepted forms")
    # The active card already started (at its top rung) -- this test is
    # about the grading, not the unlock gate `record_answer` now checks for
    # a card that has never started.
    word = await _make_saved_word(user.id, "go", active_level="produce")
    context = await _make_context(
        word.id, material.id, surface="went", example="She went home early.",
    )
    try:
        async with async_session_factory() as session:
            by_surface = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="active", exercise_type="produce",
                planned_exercise="produce", given="went", elapsed_ms=4000,
            )
        assert by_surface["verdict"] == "correct"
        assert by_surface["rating"] == int(fsrs.Rating.Easy)

        async with async_session_factory() as session:
            by_lemma = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=None,
                direction="active", exercise_type="produce",
                planned_exercise="produce", given="go", elapsed_ms=4000,
            )
        assert by_lemma["verdict"] == "correct"
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


# --- "I know this" -----------------------------------------------------------


@pytest.mark.asyncio
async def test_known_check_correct_marks_the_word_known():
    email = f"known-check-correct-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Known-check: correct")
    word = await _make_saved_word(user.id, "vogue")
    context = await _make_context(
        word.id, material.id, surface="vogue", example="It is in vogue again.",
    )
    try:
        async with async_session_factory() as session:
            item = await practice_service.build_known_check_item(
                session, user, word.id
            )
        assert item is not None
        assert item["exercise_type"] == "recall"
        assert item["is_new"] is True

        async with async_session_factory() as session:
            result = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                planned_exercise="recall", given="vogue", elapsed_ms=1500,
                claim_known=True,
            )
        assert result["known"] is True
        assert result["rating"] == int(fsrs.Rating.Easy)
        assert (await _reload(word.id)).status == "known"
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


@pytest.mark.asyncio
async def test_known_check_wrong_answer_stays_in_rotation():
    email = f"known-check-wrong-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Known-check: wrong")
    word = await _make_saved_word(user.id, "vogue")
    context = await _make_context(
        word.id, material.id, surface="vogue", example="It is in vogue again.",
    )
    try:
        async with async_session_factory() as session:
            result = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                planned_exercise="recall", given="nonsense", elapsed_ms=1500,
                claim_known=True,
            )
        assert result["known"] is False
        assert result["rating"] == int(fsrs.Rating.Again)
        reloaded = await _reload(word.id)
        assert reloaded.status == "learning"
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


# --- Leech -------------------------------------------------------------------


def _lapse_pair_logs(user_id, word, *, good_at, again_at) -> list[VocabularyReviewLog]:
    """A Review-state Good followed by an Again -- the state chain
    :func:`practice._lapses_since_reset` needs to see one lapse."""
    return [
        VocabularyReviewLog(
            user_id=user_id, saved_word_id=word.id, lemma=word.lemma,
            direction="passive", exercise_type="recall", planned_exercise="recall",
            rating=int(fsrs.Rating.Good), reviewed_at=good_at,
            state=int(fsrs.State.Review), stability=8.0, difficulty=5.0,
        ),
        VocabularyReviewLog(
            user_id=user_id, saved_word_id=word.id, lemma=word.lemma,
            direction="passive", exercise_type="recall", planned_exercise="recall",
            rating=int(fsrs.Rating.Again), reviewed_at=again_at,
            state=int(fsrs.State.Relearning), stability=4.0, difficulty=7.0,
        ),
    ]


def _review_anchor_log(user_id, word, *, at) -> VocabularyReviewLog:
    """A plain Review-state Good, with no lapse of its own -- used to make
    the synthetic log HISTORY agree with the SavedWord row's own
    ``passive_state`` (also Review) right before a real answer is
    recorded, so :func:`practice._lapses_since_reset`'s state-chain
    reconstruction and the live card are looking at the same fact."""
    return VocabularyReviewLog(
        user_id=user_id, saved_word_id=word.id, lemma=word.lemma,
        direction="passive", exercise_type="recall", planned_exercise="recall",
        rating=int(fsrs.Rating.Good), reviewed_at=at,
        state=int(fsrs.State.Review), stability=8.0, difficulty=5.0,
    )


@pytest.mark.asyncio
async def test_becomes_leech_at_six_lapses_since_reset():
    email = f"leech-six-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(
        user.id, "stubborn", status="review",
        passive_state=int(fsrs.State.Review), passive_stability=8.0,
        passive_difficulty=6.0, passive_due=now - timedelta(days=1),
        passive_last_review=now - timedelta(days=20),
    )
    try:
        # Five lapses already on record, spread far apart so the 14-day
        # threshold plays no part in this test.
        async with async_session_factory() as session:
            for i in range(5):
                marker = now - timedelta(days=200 - i * 20)
                for log in _lapse_pair_logs(
                    user.id, word, good_at=marker - timedelta(minutes=1),
                    again_at=marker,
                ):
                    session.add(log)
            # Anchors the log history to the SavedWord row's actual current
            # state (Review) right before the real answer below.
            session.add(_review_anchor_log(user.id, word, at=now - timedelta(minutes=1)))
            await session.commit()

        # The sixth lapse arrives through a real answer.
        async with async_session_factory() as session:
            result = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=None,
                direction="passive", exercise_type="recall",
                planned_exercise="recall", given="completely wrong",
                elapsed_ms=3000,
            )
        assert result["became_leech"] is True
        assert (await _reload(word.id)).status == "leech"
    finally:
        await _cleanup(user_ids=[user.id])


@pytest.mark.asyncio
async def test_becomes_leech_at_four_lapses_within_fourteen_days():
    email = f"leech-four-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(
        user.id, "recurring", status="review",
        passive_state=int(fsrs.State.Review), passive_stability=8.0,
        passive_difficulty=6.0, passive_due=now - timedelta(days=1),
        passive_last_review=now - timedelta(days=2),
    )
    try:
        async with async_session_factory() as session:
            for days_ago in (2, 5, 9):
                marker = now - timedelta(days=days_ago)
                for log in _lapse_pair_logs(
                    user.id, word, good_at=marker - timedelta(minutes=1),
                    again_at=marker,
                ):
                    session.add(log)
            session.add(_review_anchor_log(user.id, word, at=now - timedelta(minutes=1)))
            await session.commit()

        async with async_session_factory() as session:
            result = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=None,
                direction="passive", exercise_type="recall",
                planned_exercise="recall", given="completely wrong",
                elapsed_ms=3000,
            )
        assert result["became_leech"] is True
        assert (await _reload(word.id)).status == "leech"
    finally:
        await _cleanup(user_ids=[user.id])


@pytest.mark.asyncio
async def test_learning_phase_misses_never_count_as_lapses():
    email = f"leech-learning-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    word = await _make_saved_word(user.id, "fresh-word")
    try:
        for _ in range(8):
            async with async_session_factory() as session:
                result = await practice_service.record_answer(
                    session, user, word_id=word.id, context_id=None,
                    direction="passive", exercise_type="recall",
                    planned_exercise="recall", given="nonsense", elapsed_ms=1000,
                )
            assert result["became_leech"] is False
        reloaded = await _reload(word.id)
        assert reloaded.lapses == 0
        assert reloaded.status != "leech"
    finally:
        await _cleanup(user_ids=[user.id])


@pytest.mark.asyncio
async def test_leech_choices_reset_the_lapse_window():
    email = f"leech-reset-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(
        user.id, "chronic", status="leech",
        passive_state=int(fsrs.State.Review), passive_stability=6.0,
        passive_due=now + timedelta(days=1),
    )
    try:
        async with async_session_factory() as session:
            for log in _lapse_pair_logs(
                user.id, word, good_at=now - timedelta(days=10, minutes=1),
                again_at=now - timedelta(days=10),
            ):
                session.add(log)
            await session.commit()

        async with async_session_factory() as session:
            resolved = await practice_service.resolve_leech(
                session, user, word_id=word.id, choice="keep"
            )
        assert resolved is not None
        assert resolved.status != "leech"
        assert resolved.leech_reset_at is not None

        async with async_session_factory() as session:
            lapses = await practice_service._lapses_since_reset(
                session, resolved, "passive"
            )
        assert lapses == []  # the old lapse predates the reset

        async with async_session_factory() as session:
            set_aside = await practice_service.resolve_leech(
                session, user, word_id=word.id, choice="set_aside"
            )
        assert set_aside.status == "suspended"
        assert set_aside.suspended_until is not None
    finally:
        await _cleanup(user_ids=[user.id])


@pytest.mark.asyncio
async def test_suspended_word_returns_automatically_after_thirty_days():
    email = f"leech-suspend-return-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(
        user.id, "dormant", status="suspended",
        passive_state=int(fsrs.State.Review), passive_stability=6.0,
        passive_due=now - timedelta(days=1),
        suspended_until=now - timedelta(minutes=1),
    )
    try:
        async with async_session_factory() as session:
            await practice_service._reap_suspensions(session, user.id)
        reloaded = await _reload(word.id)
        assert reloaded.status != "suspended"
        assert reloaded.suspended_until is None
        assert reloaded.leech_reset_at is not None
    finally:
        await _cleanup(user_ids=[user.id])


# --- Bulk actions and the word page -----------------------------------------


@pytest.mark.asyncio
async def test_bulk_action_only_touches_the_callers_own_words():
    owner = await _make_user(f"bulk-owner-{uuid.uuid4()}@test.local")
    other = await _make_user(f"bulk-other-{uuid.uuid4()}@test.local")
    mine = await _make_saved_word(owner.id, "shared-lemma")
    theirs = await _make_saved_word(other.id, "shared-lemma")
    try:
        async with async_session_factory() as session:
            changed = await vocabulary_service.bulk_action(
                session, user_id=owner.id, word_ids=[mine.id], action="known"
            )
        assert changed == 1
        assert (await _reload(mine.id)).status == "known"
        assert (await _reload(theirs.id)).status != "known"
    finally:
        await _cleanup(user_ids=[owner.id, other.id])


@pytest.mark.asyncio
async def test_word_detail_is_404_for_another_users_word():
    owner = await _make_user(f"detail-owner-{uuid.uuid4()}@test.local")
    other = await _make_user(f"detail-other-{uuid.uuid4()}@test.local")
    mine = await _make_saved_word(owner.id, "private-word")
    try:
        async with async_session_factory() as session:
            as_other = await vocabulary_service.saved_word_with_history(
                session, other.id, mine.id
            )
        assert as_other is None

        async with async_session_factory() as session:
            as_owner = await vocabulary_service.saved_word_with_history(
                session, owner.id, mine.id
            )
        assert as_owner is not None
        word, _contexts, history = as_owner
        assert word.lemma == "private-word"
        assert history == []
    finally:
        await _cleanup(user_ids=[owner.id, other.id])


# --- record_answer is server-authoritative, not client-trusted --------------


@pytest.mark.asyncio
async def test_forged_planned_exercise_is_ignored_the_server_derives_its_own():
    """A client cannot plant a fabricated `planned_exercise="recall"` log
    against a word that is really still at the passive floor -- that log
    would later make `_has_reached_level` believe the word had already
    reached `recall`, buying a future real promotion the cheap 1-correct
    re-promotion price instead of `PROMOTE_STREAK`. The server recomputes
    the value from the word's own stored level and ignores the claim."""
    email = f"forged-planned-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Forged: planned_exercise")
    word = await _make_saved_word(user.id, "lumen")  # passive_level: "recognise"
    context = await _make_context(
        word.id, material.id, surface="lumen", example="A lumen measures light.",
    )
    try:
        async with async_session_factory() as session:
            result = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                planned_exercise="recall",  # FORGED: claims the top rung
                given="lumen", elapsed_ms=1000,
            )
        assert result is not None

        async with async_session_factory() as session:
            log = (
                await session.exec(
                    select(VocabularyReviewLog).where(
                        VocabularyReviewLog.saved_word_id == word.id
                    )
                )
            ).one()
        # The word's REAL floor, never the forged claim.
        assert log.planned_exercise == "recognise"
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


@pytest.mark.asyncio
async def test_exercise_type_must_match_the_planned_level_or_its_fallback():
    """A word still at the passive floor may be served `recall` (the one
    permitted fallback), but never `produce` -- that is not a level this
    direction's ladder has, let alone one the fallback pipeline would ever
    choose."""
    email = f"forged-exercise-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    word = await _make_saved_word(user.id, "lumen")
    try:
        with pytest.raises(HTTPException) as excinfo:
            async with async_session_factory() as session:
                await practice_service.record_answer(
                    session, user, word_id=word.id, context_id=None,
                    direction="passive", exercise_type="produce",
                    given="lumen", elapsed_ms=1000,
                )
        assert excinfo.value.status_code == 422
    finally:
        await _cleanup(user_ids=[user.id])


@pytest.mark.asyncio
async def test_active_answer_rejected_when_not_started_and_not_unlocked():
    """A brand-new word's active card has not started, and the learner's
    settings do not unlock it (`direction` defaults to `passive`) -- a
    client asking to grade a `produce`/`recognise` answer in that direction
    anyway is forging a card that was never granted."""
    email = f"forged-active-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    word = await _make_saved_word(user.id, "fresh-active-word")
    try:
        with pytest.raises(HTTPException) as excinfo:
            async with async_session_factory() as session:
                await practice_service.record_answer(
                    session, user, word_id=word.id, context_id=None,
                    direction="active", exercise_type="recognise",
                    given="fresh-active-word", elapsed_ms=1000,
                )
        assert excinfo.value.status_code == 422
    finally:
        await _cleanup(user_ids=[user.id])


@pytest.mark.asyncio
async def test_active_answer_allowed_once_the_unlock_gate_is_actually_met():
    """The mirror of the test above: the SAME never-started active card is
    accepted once `direction` is `both` and passive stability has actually
    crossed `ACTIVE_UNLOCK_STABILITY_DAYS` -- the gate is a real check, not
    a blanket refusal of every first active answer."""
    email = f"unlocked-active-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    word = await _make_saved_word(
        user.id, "unlockable-word", status="review",
        passive_state=int(fsrs.State.Review), passive_stability=25.0,
    )
    try:
        async with async_session_factory() as session:
            await practice_service.update_settings(
                session, user.id, daily_minutes=10, direction="both",
                exercise_types=None,
            )
        async with async_session_factory() as session:
            result = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=None,
                direction="active", exercise_type="recognise",
                given="unlockable-word", elapsed_ms=1000,
            )
        assert result is not None
        assert (await _reload(word.id)).active_level is not None
    finally:
        await _cleanup(user_ids=[user.id])


@pytest.mark.asyncio
async def test_claim_known_rejected_once_the_word_has_been_practised():
    """"I know this" is new-word-only -- a word whose passive card has
    already been practised is already in rotation, and a `claim_known`
    against it is not the bypass the brief describes."""
    email = f"forged-known-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(
        user.id, "already-practised", status="review",
        passive_state=int(fsrs.State.Review), passive_stability=8.0,
        passive_due=now - timedelta(days=1),
    )
    try:
        with pytest.raises(HTTPException) as excinfo:
            async with async_session_factory() as session:
                await practice_service.record_answer(
                    session, user, word_id=word.id, context_id=None,
                    direction="passive", exercise_type="recall",
                    given="already-practised", elapsed_ms=1000,
                    claim_known=True,
                )
        assert excinfo.value.status_code == 422
    finally:
        await _cleanup(user_ids=[user.id])


@pytest.mark.asyncio
async def test_recognise_answer_with_a_forged_option_id_is_wrong_not_an_error():
    """`given` need not be one of the four ids actually shown -- grading
    recomputes the RIGHT option's id and compares, so an unrecognised id is
    simply a wrong answer, never a crash or a 500."""
    email = f"forged-option-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    word = await _make_saved_word(
        user.id, "lumen", meaning_core_en="a unit of luminous flux",
    )
    try:
        async with async_session_factory() as session:
            result = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=None,
                direction="passive", exercise_type="recognise",
                given="not-a-real-option-id", elapsed_ms=1000,
            )
        assert result is not None
        assert result["verdict"] == "wrong"
    finally:
        await _cleanup(user_ids=[user.id])


# --- Active practice pauses, rather than resets, with `direction` ------------


@pytest.mark.asyncio
async def test_active_cards_pause_under_passive_and_resume_unchanged():
    email = f"active-pause-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(
        user.id, "paused-word", status="review",
        passive_state=int(fsrs.State.Review), passive_stability=25.0,
        passive_due=now + timedelta(days=5),
        active_level="produce",
        active_state=int(fsrs.State.Review), active_stability=9.0,
        active_due=now - timedelta(minutes=5),
    )
    try:
        # `direction` defaults to `passive` -- the active card is due, but
        # paused: it must not enter either queue.
        async with async_session_factory() as session:
            settings = await practice_service.get_settings(session, user.id)
            due, new = await practice_service._gather_candidates(
                session, user, settings, mode="auto", material_id=None
            )
        assert not any(c.word.id == word.id for c in due)
        assert not any(c.word.id == word.id for c in new)

        # The settings screen's own count still sees it -- pausing is not
        # the same fact as "retired".
        async with async_session_factory() as session:
            in_progress = await practice_service.active_in_progress_count(
                session, user.id
            )
        assert in_progress == 1

        # Switching back to `both` resumes it, unchanged.
        async with async_session_factory() as session:
            await practice_service.update_settings(
                session, user.id, daily_minutes=10, direction="both",
                exercise_types=None,
            )
        async with async_session_factory() as session:
            settings = await practice_service.get_settings(session, user.id)
            due, _new = await practice_service._gather_candidates(
                session, user, settings, mode="auto", material_id=None
            )
        resumed = next(c for c in due if c.word.id == word.id)
        assert resumed.direction == "active"

        reloaded = await _reload(word.id)
        assert reloaded.active_stability == 9.0  # untouched by the pause
        assert reloaded.active_due == word.active_due
        assert reloaded.active_level == "produce"
    finally:
        await _cleanup(user_ids=[user.id])


# --- B2: the ladder is a named list, walked by index --------------------------


def test_ladder_constants_match_the_addendum_exactly():
    """Named exactly as the addendum's own table, in text matching
    `EXERCISE_TYPES`, never a bare integer -- see the constants' own
    docstring for why a single shared "level 2" was the bug."""
    assert PASSIVE_LADDER == ("recognise", "recall")
    assert ACTIVE_LADDER == ("recognise", "produce")


def test_ladder_for_direction_reads_the_named_lists():
    assert practice_service._ladder_for("passive") is PASSIVE_LADDER
    assert practice_service._ladder_for("active") is ACTIVE_LADDER


# --- B1: the same-session requeue ---------------------------------------------


@pytest.mark.asyncio
async def test_requeued_answer_does_not_move_the_ladder_or_log_as_a_fallback():
    """The client re-shows the SAME item after an Again, at the end of the
    session. That second answer must not undo the demotion the first answer
    already earned (it is not promotion evidence), and its log row is not a
    fallback -- `planned_exercise` is logged NULL, never the exercise
    actually served, so it can be neither the ladder's plan nor evidence
    that the word has ever reached that level."""
    email = f"requeue-top-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(
        user.id, "lumen", status="review", passive_level="recall",
        passive_state=int(fsrs.State.Review), passive_stability=12.0,
        passive_difficulty=5.0, passive_due=now - timedelta(days=1),
        passive_last_review=now - timedelta(days=13),
    )
    try:
        async with async_session_factory() as session:
            first = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=None,
                direction="passive", exercise_type="recall",
                planned_exercise="recall", given="completely wrong",
                elapsed_ms=1000,
            )
        assert first["rating"] == int(fsrs.Rating.Again)
        assert first["returns_this_session"] is True
        assert (await _reload(word.id)).passive_level == "recognise"  # demoted

        # The requeued serving of the SAME item, answered correctly.
        async with async_session_factory() as session:
            second = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=None,
                direction="passive", exercise_type="recall",
                planned_exercise="recall", given="lumen", elapsed_ms=1000,
                requeued=True,
            )
        assert second is not None
        assert second["verdict"] == "correct"
        # Not promoted back up by this single answer -- it was never
        # evidence towards it.
        assert (await _reload(word.id)).passive_level == "recognise"

        async with async_session_factory() as session:
            logs = (
                await session.exec(
                    select(VocabularyReviewLog)
                    .where(VocabularyReviewLog.saved_word_id == word.id)
                    .order_by(VocabularyReviewLog.reviewed_at)
                )
            ).all()
        assert len(logs) == 2
        # Logged with NO plan at all -- never the exercise actually served,
        # which would forge "this word has reached recall" evidence
        # (`_has_reached_level`) for a rung this answer never earned, and
        # never a fallback substitution for the (now-lower) floor either.
        assert logs[1].planned_exercise is None
        assert logs[1].exercise_type == "recall"
    finally:
        await _cleanup(user_ids=[user.id])


@pytest.mark.asyncio
async def test_requeued_claim_rejected_without_a_matching_recent_again():
    """A client cannot claim `requeued` out of nowhere -- there must be a
    real, recent `Again` at exactly this exercise for this word."""
    email = f"requeue-forged-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    word = await _make_saved_word(user.id, "lumen")  # never practised at all
    try:
        with pytest.raises(HTTPException) as excinfo:
            async with async_session_factory() as session:
                await practice_service.record_answer(
                    session, user, word_id=word.id, context_id=None,
                    direction="passive", exercise_type="recall",
                    given="lumen", elapsed_ms=1000, requeued=True,
                )
        assert excinfo.value.status_code == 422
    finally:
        await _cleanup(user_ids=[user.id])


@pytest.mark.asyncio
async def test_requeued_claim_rejected_once_the_window_has_passed():
    """A stale claim -- an Again from days ago -- is not "the same
    session"; :data:`practice_service.REQUEUE_WINDOW` is the cutoff."""
    email = f"requeue-stale-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(
        user.id, "lumen", status="review", passive_level="recall",
        passive_state=int(fsrs.State.Review), passive_stability=12.0,
        passive_due=now - timedelta(days=1),
    )
    try:
        async with async_session_factory() as session:
            session.add(VocabularyReviewLog(
                user_id=user.id, saved_word_id=word.id, lemma=word.lemma,
                direction="passive", exercise_type="recall",
                planned_exercise="recall", rating=int(fsrs.Rating.Again),
                reviewed_at=now - practice_service.REQUEUE_WINDOW - timedelta(minutes=1),
                state=int(fsrs.State.Relearning), stability=4.0, difficulty=7.0,
            ))
            await session.commit()

        with pytest.raises(HTTPException) as excinfo:
            async with async_session_factory() as session:
                await practice_service.record_answer(
                    session, user, word_id=word.id, context_id=None,
                    direction="passive", exercise_type="recall",
                    given="lumen", elapsed_ms=1000, requeued=True,
                )
        assert excinfo.value.status_code == 422
    finally:
        await _cleanup(user_ids=[user.id])


# --- Ladder integrity: a known-check or a requeue is never ladder evidence --


def _recognise_given(word: SavedWord, context: SavedWordContext | None) -> str:
    """The correct `given` for a passive `recognise` answer -- the right
    option's id, recomputed the same way `grade_choice` does, so a test can
    answer a recognise item correctly without building the four options."""
    right_text = practice_service._recognise_right_text(word, context, "passive")
    return distractors.option_id(word.id, right_text)


@pytest.mark.asyncio
async def test_known_check_pass_does_not_grant_a_free_repromotion():
    """A CORRECT "I know this" answer must be logged with no plan at all.
    Logged as `planned_exercise="recall"` (the bug), it would make
    `_has_reached_level` believe the word had genuinely reached the top
    rung, so a single correct `recognise` answer afterwards would promote
    it -- one, not the usual two."""
    email = f"known-repromo-pass-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Known-check: no free repromotion (pass)")
    word = await _make_saved_word(
        user.id, "lumen", meaning_core_en="a unit of luminous flux",
    )
    context = await _make_context(
        word.id, material.id, surface="lumen", example="A lumen measures light.",
    )
    try:
        async with async_session_factory() as session:
            known = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                given="lumen", elapsed_ms=1200, claim_known=True,
            )
        assert known["known"] is True

        async with async_session_factory() as session:
            log = (
                await session.exec(
                    select(VocabularyReviewLog).where(
                        VocabularyReviewLog.saved_word_id == word.id
                    )
                )
            ).one()
        assert log.planned_exercise is None

        given = _recognise_given(word, context)
        async with async_session_factory() as session:
            first = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recognise",
                given=given, elapsed_ms=1200,
            )
        # One correct is not enough -- the known-check row bought nothing.
        assert first["level"] == "recognise"
        assert (await _reload(word.id)).passive_level == "recognise"

        async with async_session_factory() as session:
            second = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recognise",
                given=given, elapsed_ms=1200,
            )
        assert second["level"] == "recall"
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


@pytest.mark.asyncio
async def test_known_check_fail_does_not_grant_a_free_repromotion():
    """A WRONG "I know this" answer is still an answer AT `recall`, and must
    be logged with no plan either -- pass or fail, per the brief's fix."""
    email = f"known-repromo-fail-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Known-check: no free repromotion (fail)")
    word = await _make_saved_word(
        user.id, "lumen", meaning_core_en="a unit of luminous flux",
    )
    context = await _make_context(
        word.id, material.id, surface="lumen", example="A lumen measures light.",
    )
    try:
        async with async_session_factory() as session:
            failed = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                given="completely wrong", elapsed_ms=1200, claim_known=True,
            )
        assert failed["known"] is False

        async with async_session_factory() as session:
            log = (
                await session.exec(
                    select(VocabularyReviewLog).where(
                        VocabularyReviewLog.saved_word_id == word.id
                    )
                )
            ).one()
        assert log.planned_exercise is None
        assert (await _reload(word.id)).passive_level == "recognise"

        given = _recognise_given(word, context)
        async with async_session_factory() as session:
            first = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recognise",
                given=given, elapsed_ms=1200,
            )
        assert first["level"] == "recognise"

        async with async_session_factory() as session:
            second = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recognise",
                given=given, elapsed_ms=1200,
            )
        assert second["level"] == "recall"
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


@pytest.mark.asyncio
async def test_fallback_then_requeue_does_not_grant_a_free_repromotion():
    """A fallback-served `recall` answered Again, then requeued and answered
    correctly: the requeue's `exercise_type` ("recall") is the fallback's
    HARDER task, never a rung the ladder itself promoted this word to, and
    must not be logged as one -- either bug would let a single correct
    `recognise` answer afterwards promote the word."""
    email = f"fallback-repromo-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Fallback+requeue: no free repromotion")
    word = await _make_saved_word(
        user.id, "lumen", meaning_core_en="a unit of luminous flux",
    )
    context = await _make_context(
        word.id, material.id, surface="lumen", example="A lumen measures light.",
    )
    try:
        # A fallback-served `recall` answer at the passive floor, wrong.
        async with async_session_factory() as session:
            first = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                given="completely wrong", elapsed_ms=1200,
            )
        assert first["rating"] == int(fsrs.Rating.Again)
        assert (await _reload(word.id)).passive_level == "recognise"

        # The client requeues that same fallback item and answers correctly.
        async with async_session_factory() as session:
            requeue = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                given="lumen", elapsed_ms=1200, requeued=True,
            )
        assert requeue["verdict"] == "correct"

        async with async_session_factory() as session:
            logs = (
                await session.exec(
                    select(VocabularyReviewLog)
                    .where(VocabularyReviewLog.saved_word_id == word.id)
                    .order_by(VocabularyReviewLog.reviewed_at)
                )
            ).all()
        assert len(logs) == 2
        # Not "recall" -- that would claim the ladder itself served this
        # word at its top rung, which it never did.
        assert logs[1].planned_exercise is None
        # Never a fallback either: the metric requires a non-null plan.
        assert not (
            logs[1].planned_exercise is not None
            and logs[1].planned_exercise != logs[1].exercise_type
        )
        assert (await _reload(word.id)).passive_level == "recognise"

        given = _recognise_given(word, context)
        async with async_session_factory() as session:
            second = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recognise",
                given=given, elapsed_ms=1200,
            )
        # One correct is not enough -- the requeue row bought nothing.
        assert second["level"] == "recognise"

        async with async_session_factory() as session:
            third = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recognise",
                given=given, elapsed_ms=1200,
            )
        assert third["level"] == "recall"
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


# --- B3: passive recognise is the bare word, never a marked sentence --------


@pytest.mark.asyncio
async def test_passive_recognise_shows_the_bare_word_no_sentence():
    """The brief: passive `recognise` is the English word alone. `before`/
    `after` are empty and `target` is the lemma, even though this word HAS
    a sentence that could have been marked."""
    email = f"passive-recognise-bare-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Passive recognise: bare word")
    part = await _make_part(material.id)
    word = await _make_saved_word(
        user.id, "steadfast", pos="adj",
        meaning_core_en="firm and not changing in attitude or purpose",
    )
    context = await _make_context(
        word.id, material.id, surface="steadfast", cefr_level="B2",
        example="She remained steadfast despite the criticism.",
    )
    await _make_vocab_entry(
        material.id, part.id, lemma="loyal", pos="adj", cefr_level="B2",
        meaning_en="faithful to a person or cause",
    )
    await _make_vocab_entry(
        material.id, part.id, lemma="rigid", pos="adj", cefr_level="B2",
        meaning_en="unable to bend or be forced out of shape",
    )
    await _make_vocab_entry(
        material.id, part.id, lemma="cautious", pos="adj", cefr_level="B2",
        meaning_en="careful to avoid danger or mistakes",
    )
    try:
        async with async_session_factory() as session:
            passive_item = await practice_service._build_item(
                session, word, "passive", "recognise", context, is_new=True,
                source_material_ids=frozenset({material.id}),
                family_keys=frozenset(),
            )
        assert passive_item["exercise_type"] == "recognise"
        assert passive_item["prompt"]["kind"] == "choice"
        assert passive_item["prompt"]["before"] == ""
        assert passive_item["prompt"]["after"] == ""
        assert passive_item["prompt"]["target"] == "steadfast"
        assert len(passive_item["prompt"]["options"]) == 4

        # Active `recognise` is unaffected -- still no target word, only
        # the Uzbek meaning.
        async with async_session_factory() as session:
            active_item = await practice_service._build_item(
                session, word, "active", "recognise", context, is_new=True,
                source_material_ids=frozenset({material.id}),
                family_keys=frozenset(),
            )
        assert active_item["prompt"]["target"] == ""
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


# --- B4: the settings screen's exercise type is ONE choice --------------------


def test_settings_exercise_types_accepts_null_or_exactly_one():
    auto = VocabularySettingsIn(daily_minutes=10, direction="passive",
                                 exercise_types=None)
    assert auto.exercise_types is None

    one = VocabularySettingsIn(daily_minutes=10, direction="passive",
                                exercise_types=["produce"])
    assert one.exercise_types == ["produce"]

    with pytest.raises(ValidationError):
        VocabularySettingsIn(daily_minutes=10, direction="passive",
                              exercise_types=["recognise", "produce"])

    with pytest.raises(ValidationError):
        VocabularySettingsIn(daily_minutes=10, direction="passive",
                              exercise_types=[])


@pytest.mark.asyncio
async def test_manual_produce_choice_only_serves_active_produce_cards():
    """`Produce` maps to active `produce` cards only -- a word still at
    passive `recognise` offers nothing, per the addendum's table."""
    email = f"manual-produce-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    await _make_saved_word(
        user.id, "recognise-only", status="review", passive_level="recognise",
        passive_state=int(fsrs.State.Review), passive_stability=5.0,
        passive_due=now - timedelta(minutes=5),
    )
    await _make_saved_word(
        user.id, "produce-ready", status="review",
        passive_state=int(fsrs.State.Review), passive_stability=25.0,
        passive_due=now + timedelta(days=5),
        active_level="produce",
        active_state=int(fsrs.State.Review), active_stability=5.0,
        active_due=now - timedelta(minutes=5),
    )
    try:
        async with async_session_factory() as session:
            await practice_service.update_settings(
                session, user.id, daily_minutes=20, direction="both",
                exercise_types=["produce"],
            )
        async with async_session_factory() as session:
            items = await practice_service.build_session(session, user, tz=None)
        lemmas = {item["lemma"] for item in items}
        assert lemmas == {"produce-ready"}
        assert all(item["exercise_type"] == "produce" for item in items)
    finally:
        await _cleanup(user_ids=[user.id])


# --- B5: per-direction lapse counts, derived from the logs ---------------------


@pytest.mark.asyncio
async def test_lapse_counts_for_split_by_direction_from_the_logs():
    email = f"lapse-split-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(user.id, "split-lapses")
    try:
        async with async_session_factory() as session:
            for marker in (
                now - timedelta(days=10), now - timedelta(days=5),
            ):
                for log in _lapse_pair_logs(
                    user.id, word, good_at=marker - timedelta(minutes=1),
                    again_at=marker,
                ):
                    session.add(log)
            session.add(VocabularyReviewLog(
                user_id=user.id, saved_word_id=word.id, lemma=word.lemma,
                direction="active", exercise_type="produce",
                planned_exercise="produce", rating=int(fsrs.Rating.Good),
                reviewed_at=now - timedelta(days=3, minutes=1),
                state=int(fsrs.State.Review), stability=8.0, difficulty=5.0,
            ))
            session.add(VocabularyReviewLog(
                user_id=user.id, saved_word_id=word.id, lemma=word.lemma,
                direction="active", exercise_type="produce",
                planned_exercise="produce", rating=int(fsrs.Rating.Again),
                reviewed_at=now - timedelta(days=3),
                state=int(fsrs.State.Relearning), stability=4.0, difficulty=7.0,
            ))
            await session.commit()

        async with async_session_factory() as session:
            counts = await practice_service.lapse_counts_for(session, [word.id])
        assert counts[word.id] == {"passive": 2, "active": 1}
    finally:
        await _cleanup(user_ids=[user.id])


def test_saved_word_out_exposes_the_per_direction_lapse_counts():
    word = SavedWord(user_id=uuid.uuid4(), lemma="tally", lapses=5)
    out = _saved_word_out(
        word, [], {}, direction="passive",
        lapse_counts={"passive": 3, "active": 2},
    )
    assert out.passive_lapses == 3
    assert out.active_lapses == 2


# --- B6: the leech card's own context, and the "see it in context" choice ---


@pytest.mark.asyncio
async def test_leech_answer_returns_the_newest_context_with_a_sentence():
    email = f"leech-context-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material = await _make_material(user.id, "Leech: context")
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(
        user.id, "obstinate", status="review",
        passive_state=int(fsrs.State.Review), passive_stability=8.0,
        passive_difficulty=6.0, passive_due=now - timedelta(days=1),
        passive_last_review=now - timedelta(days=20),
    )
    context = await _make_context(
        word.id, material.id, surface="obstinate",
        example="He was obstinate about the schedule.",
    )
    try:
        async with async_session_factory() as session:
            for i in range(5):
                marker = now - timedelta(days=200 - i * 20)
                for log in _lapse_pair_logs(
                    user.id, word, good_at=marker - timedelta(minutes=1),
                    again_at=marker,
                ):
                    session.add(log)
            session.add(_review_anchor_log(user.id, word, at=now - timedelta(minutes=1)))
            await session.commit()

        async with async_session_factory() as session:
            result = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=context.id,
                direction="passive", exercise_type="recall",
                planned_exercise="recall", given="completely wrong",
                elapsed_ms=3000,
            )
        assert result["became_leech"] is True
        leech_context = result["leech_context"]
        assert leech_context is not None
        assert leech_context["target"] == "obstinate"
        assert leech_context["before"] == "He was "
        assert leech_context["after"] == " about the schedule."
        assert leech_context["material_id"] == material.id
        assert leech_context["material_title"] == "Leech: context"
    finally:
        await _cleanup(user_ids=[user.id], material_ids=[material.id])


@pytest.mark.asyncio
async def test_leech_answer_with_no_sentence_anywhere_returns_a_null_context():
    email = f"leech-context-null-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(
        user.id, "recalcitrant", status="review",
        passive_state=int(fsrs.State.Review), passive_stability=8.0,
        passive_difficulty=6.0, passive_due=now - timedelta(days=1),
        passive_last_review=now - timedelta(days=20),
    )
    try:
        async with async_session_factory() as session:
            for i in range(5):
                marker = now - timedelta(days=200 - i * 20)
                for log in _lapse_pair_logs(
                    user.id, word, good_at=marker - timedelta(minutes=1),
                    again_at=marker,
                ):
                    session.add(log)
            session.add(_review_anchor_log(user.id, word, at=now - timedelta(minutes=1)))
            await session.commit()

        async with async_session_factory() as session:
            result = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=None,
                direction="passive", exercise_type="recall",
                planned_exercise="recall", given="completely wrong",
                elapsed_ms=3000,
            )
        assert result["became_leech"] is True
        assert result["leech_context"] is None
    finally:
        await _cleanup(user_ids=[user.id])


@pytest.mark.asyncio
async def test_leech_see_context_choice_keeps_the_level_and_resets_lapses():
    """"See it in context" is graded the same as "keep going" -- status
    recomputed, lapse window reset -- and, per the brief, the word stays at
    its own level: seeing the sentence again is not practice."""
    email = f"leech-see-context-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    now = datetime.now(timezone.utc)
    word = await _make_saved_word(
        user.id, "intransigent", status="leech", passive_level="recall",
        passive_state=int(fsrs.State.Review), passive_stability=6.0,
        passive_due=now + timedelta(days=1),
    )
    try:
        async with async_session_factory() as session:
            for log in _lapse_pair_logs(
                user.id, word, good_at=now - timedelta(days=10, minutes=1),
                again_at=now - timedelta(days=10),
            ):
                session.add(log)
            await session.commit()

        async with async_session_factory() as session:
            resolved = await practice_service.resolve_leech(
                session, user, word_id=word.id, choice="see_context"
            )
        assert resolved is not None
        assert resolved.status != "leech"
        assert resolved.passive_level == "recall"  # unchanged
        assert resolved.leech_reset_at is not None

        async with async_session_factory() as session:
            lapses = await practice_service._lapses_since_reset(
                session, resolved, "passive"
            )
        assert lapses == []  # reset, same as the other two choices
    finally:
        await _cleanup(user_ids=[user.id])
