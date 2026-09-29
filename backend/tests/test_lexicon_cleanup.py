"""`scripts/lexicon_cleanup.py`'s three added-2026-09-29 data-only
subcommands (`hide-proper-nouns`, `function-words`, `restore-retranslation`)
-- no model call in any of the three, so they are tested directly against a
real database rather than through a scripted Gemini stand-in.
`wordnet-provenance` needs the real OEWN extract to backfill against and is
exercised end to end by `test_apply_work_persists_the_oewn_semcor_rank` in
`test_lexicon_link.py` instead (`apply_work`, the function it backfills for,
is the thing actually worth proving).
"""

import json
import uuid
from pathlib import Path

import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense
from app.models.material import Material
from app.models.part import Part
from app.models.user import User
from app.models.vocabulary import MaterialVocabulary
from scripts import lexicon_cleanup as cleanup


async def _delete_lexemes(*lemmas: str) -> None:
    async with async_session_factory() as session:
        lexemes = (await session.exec(select(Lexeme).where(Lexeme.lemma.in_(lemmas)))).all()
        for lexeme in lexemes:
            for sense in (await session.exec(
                select(LexemeSense).where(LexemeSense.lexeme_id == lexeme.id)
            )).all():
                await session.delete(sense)
            await session.flush()
            await session.delete(lexeme)
        await session.commit()


# --- A: hide-proper-nouns -----------------------------------------------------


@pytest.mark.asyncio
async def test_hide_proper_nouns_hides_existing_rows_and_is_idempotent() -> None:
    tag = uuid.uuid4().hex[:8]
    lemma = f"zorbnoun{tag}"
    user = User(email=f"hide-pn-{tag}@test.local", display_name="hide pn test")
    async with async_session_factory() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
        material = Material(author_id=user.id, type="reading", title=f"hide pn {tag}",
                            visibility="private")
        session.add(material)
        await session.flush()
        part = Part(material_id=material.id, order_index=0, title="Part 1", passage={})
        session.add(part)
        await session.flush()
        lexeme = Lexeme(lemma=lemma, pos="n", is_proper_noun=True)
        session.add(lexeme)
        await session.flush()
        row = MaterialVocabulary(
            material_id=material.id, part_id=part.id, lemma=lemma, surface=lemma.title(),
            pos="n", meaning_en="a name", meaning_uz="ism", lexeme_id=lexeme.id,
            hidden=False,
        )
        session.add(row)
        await session.commit()
        row_id = row.id
    try:
        await cleanup.hide_proper_nouns()
        async with async_session_factory() as session:
            row = await session.get(MaterialVocabulary, row_id)
            assert row.hidden is True

        # Idempotent: nothing left to hide, so a second run touches zero rows
        # and does not error re-hiding an already-hidden row.
        await cleanup.hide_proper_nouns()
        async with async_session_factory() as session:
            row = await session.get(MaterialVocabulary, row_id)
            assert row.hidden is True
    finally:
        async with async_session_factory() as session:
            await session.delete(await session.get(MaterialVocabulary, row_id))
            await session.delete(await session.get(Part, part.id))
            await session.delete(await session.get(Material, material.id))
            await session.delete(await session.get(User, user.id))
            await session.commit()
        await _delete_lexemes(lemma)


# --- C2: function-words --------------------------------------------------------


@pytest.mark.asyncio
async def test_function_words_dry_run_writes_nothing() -> None:
    """Without ``--apply``, a list-only excluded lexeme is reported as
    "would delete" but is still in the database afterwards."""
    tag = uuid.uuid4().hex[:8]
    lemma = "about"  # a real FUNCTION_WORDS member -- see `is_excluded_word`
    # Use a lemma that is genuinely in FUNCTION_WORDS but re-create it fresh
    # under a lexeme with no references, so this test does not depend on
    # (or disturb) whatever the one-off 2026-09-29 pass already did to the
    # real "about" lexeme.
    async with async_session_factory() as session:
        existing = (await session.exec(select(Lexeme).where(Lexeme.lemma == lemma))).first()
        if existing is not None:
            pytest.skip(f"{lemma!r} lexeme already cleaned up in this database")
        lexeme = Lexeme(lemma=lemma, pos="prep")
        session.add(lexeme)
        await session.commit()
    try:
        await cleanup.function_words(apply=False)
        async with async_session_factory() as session:
            still_there = (await session.exec(
                select(Lexeme).where(Lexeme.lemma == lemma)
            )).first()
            assert still_there is not None
            assert still_there.is_function_word is False
    finally:
        await _delete_lexemes(lemma)


@pytest.mark.asyncio
async def test_function_words_apply_deletes_an_unreferenced_lexeme() -> None:
    tag = uuid.uuid4().hex[:8]
    lemma = f"z{tag[:1]}"[:1]  # a single character -- excluded regardless of the list
    async with async_session_factory() as session:
        lexeme = Lexeme(lemma=lemma, pos="n")
        session.add(lexeme)
        await session.commit()
    await cleanup.function_words(apply=True)
    async with async_session_factory() as session:
        gone = (await session.exec(select(Lexeme).where(Lexeme.lemma == lemma))).first()
        assert gone is None


@pytest.mark.asyncio
async def test_function_words_apply_marks_and_hides_a_referenced_lexeme() -> None:
    tag = uuid.uuid4().hex[:8]
    lemma = f"z{tag[:1]}"[:1]
    user = User(email=f"fw-mark-{tag}@test.local", display_name="fw mark test")
    async with async_session_factory() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
        material = Material(author_id=user.id, type="reading", title=f"fw mark {tag}",
                            visibility="private")
        session.add(material)
        await session.flush()
        part = Part(material_id=material.id, order_index=0, title="Part 1", passage={})
        session.add(part)
        await session.flush()
        lexeme = Lexeme(lemma=lemma, pos="n")
        session.add(lexeme)
        await session.flush()
        row = MaterialVocabulary(
            material_id=material.id, part_id=part.id, lemma=lemma, surface=lemma,
            pos="n", meaning_en="the letter", meaning_uz="harf", lexeme_id=lexeme.id,
            hidden=False,
        )
        session.add(row)
        await session.commit()
        row_id, lexeme_id = row.id, lexeme.id
    try:
        await cleanup.function_words(apply=True)
        async with async_session_factory() as session:
            lexeme = await session.get(Lexeme, lexeme_id)
            assert lexeme is not None  # referenced -- kept, not deleted
            assert lexeme.is_function_word is True
            row = await session.get(MaterialVocabulary, row_id)
            assert row.hidden is True
    finally:
        async with async_session_factory() as session:
            await session.delete(await session.get(MaterialVocabulary, row_id))
            await session.delete(await session.get(Part, part.id))
            await session.delete(await session.get(Material, material.id))
            await session.delete(await session.get(User, user.id))
            await session.commit()
        await _delete_lexemes(lemma)


# --- C1: restore-retranslation --------------------------------------------------


@pytest.mark.asyncio
async def test_restore_retranslation_puts_back_the_old_pair(tmp_path: Path) -> None:
    tag = uuid.uuid4().hex[:8]
    lemma = f"trialword{tag}"
    async with async_session_factory() as session:
        lexeme = Lexeme(lemma=lemma, pos="n", frequency_band="off-list")
        session.add(lexeme)
        await session.commit()
        await session.refresh(lexeme)
        sense = LexemeSense(
            lexeme_id=lexeme.id, sense_rank=1, definition_en="a test sense",
            meaning_uz="yangi", meaning_uz_alt="yangi2", provisional=False,
            review_reasons=["judge_different"], needs_review=True,
        )
        session.add(sense)
        await session.commit()
        await session.refresh(sense)

    trial_file = tmp_path / "trial.json"
    trial_file.write_text(json.dumps({
        str(sense.id): {
            "lemma": lemma, "pos": "n", "definition": "a test sense",
            "old_uz": "eski", "old_alt": "eski2", "old_verdict": "same",
            "new_uz": "yangi", "new_alt": "yangi2", "new_verdict": "different",
        }
    }))
    try:
        await cleanup.restore_retranslation(trial_file, None)
        async with async_session_factory() as session:
            row = await session.get(LexemeSense, sense.id)
            assert row.meaning_uz == "eski" and row.meaning_uz_alt == "eski2"
            # The OLD verdict's own reason replaces the trial's `judge_different`.
            assert "judge_different" not in row.review_reasons
    finally:
        await _delete_lexemes(lemma)


@pytest.mark.asyncio
async def test_restore_retranslation_filters_by_sense_id_and_reports_unknown(
    tmp_path: Path,
) -> None:
    tag = uuid.uuid4().hex[:8]
    lemma = f"trialword2{tag}"
    async with async_session_factory() as session:
        lexeme = Lexeme(lemma=lemma, pos="n", frequency_band="off-list")
        session.add(lexeme)
        await session.commit()
        await session.refresh(lexeme)
        sense = LexemeSense(
            lexeme_id=lexeme.id, sense_rank=1, definition_en="a test sense",
            meaning_uz="yangi", provisional=False,
        )
        session.add(sense)
        await session.commit()
        await session.refresh(sense)

    other_id = str(uuid.uuid4())
    trial_file = tmp_path / "trial.json"
    trial_file.write_text(json.dumps({
        str(sense.id): {
            "lemma": lemma, "pos": "n", "definition": "a test sense",
            "old_uz": "eski", "old_alt": "", "old_verdict": None,
            "new_uz": "yangi", "new_alt": "", "new_verdict": None,
        },
        other_id: {
            "lemma": "other", "pos": "n", "definition": "x",
            "old_uz": "o", "old_alt": "", "old_verdict": None,
            "new_uz": "n", "new_alt": "", "new_verdict": None,
        },
    }))
    try:
        # Restoring an id not in the file at all is reported, not applied.
        missing_id = str(uuid.uuid4())
        await cleanup.restore_retranslation(trial_file, [missing_id])
        async with async_session_factory() as session:
            row = await session.get(LexemeSense, sense.id)
            assert row.meaning_uz == "yangi"  # untouched -- not the id asked for

        # Restoring by the real id only touches that one sense.
        await cleanup.restore_retranslation(trial_file, [str(sense.id)])
        async with async_session_factory() as session:
            row = await session.get(LexemeSense, sense.id)
            assert row.meaning_uz == "eski"
    finally:
        await _delete_lexemes(lemma)
