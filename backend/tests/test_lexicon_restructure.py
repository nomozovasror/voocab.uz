"""The lexicon restructure tool (`app.services.lexicon_restructure`,
`scripts/lexicon_restructure.py`): every op, the in-order simulation, the dry
run, the journal and exact undo, the refused/alias rules, `translate`.

Runs ONLY against the throwaway database `voocab_restructure_test` (create it,
`alembic upgrade head`, point DATABASE_URL at it): each test starts by
truncating users/materials/lexemes with CASCADE, which must never happen to a
database anybody uses -- the fixture refuses any other name. Every sense,
sentence and Uzbek word is INVENTED.
"""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy import select as core_select
from sqlmodel import select

from app.core.database import async_session_factory, engine
from app.models.lexicon import Lexeme, LexemeSense, LexiconAiReview, TranslationReport
from app.models.material import Material
from app.models.part import Part
from app.models.user import REVIEW_BOT_EMAIL, User
from app.models.vocabulary import (
    Deck,
    DeckWord,
    MaterialVocabulary,
    SavedWord,
    SavedWordContext,
    VocabularyReviewLog,
)
from app.models.word_list import WordList, WordListEntry
from app.models.word_recording import WordRecording
from app.services import lexicon as lexicon_service
from app.services import lexicon_enrich as le
from app.services import lexicon_restructure as lr

TEST_DB = "voocab_restructure_test"
REAL_CALD_HEADWORD = lr.cald_has_headword  # the fixture replaces it with a stub


@pytest.fixture(autouse=True)
async def clean(tmp_path, monkeypatch):
    name = engine.url.database
    if name != TEST_DB:
        pytest.fail(f"refusing to run: DATABASE_URL names {name!r}, not {TEST_DB!r}")
    async with async_session_factory() as session:
        await session.exec(text(
            "truncate users, materials, lexemes, word_lists restart identity cascade"))
        await session.commit()
    monkeypatch.setattr(lexicon_service, "RULES_PATH", tmp_path / "rules.json")
    monkeypatch.setattr(lr, "cald_has_headword", lambda lemma: False)
    yield tmp_path


# --- the world ----------------------------------------------------------------------------------


class W:
    """Handles to what `world()` built."""


async def world() -> W:
    """lexeme `alpha` (n): senses a1 (rank 1, C1, flagged), a2, a3 with rows
    r1 (a1), r2 (a2), r3 (a3); two learners with saved words on a1 and a2;
    plus lexeme `omega` (n) with o1/o2, rows ro1 and a verb `alpha` (v) v1."""
    w = W()
    async with async_session_factory() as session:
        user = User(email="owner@test.local", display_name="owner")
        u2 = User(email="learner2@test.local", display_name="two")
        session.add_all([user, u2])
        await session.flush()
        material = Material(author_id=user.id, type="reading", title="m", visibility="private")
        m2 = Material(author_id=user.id, type="reading", title="m2", visibility="private")
        session.add_all([material, m2])
        await session.flush()
        part = Part(material_id=material.id, order_index=0, title="P",
                    passage={"paragraphs": []}, first_number=1)
        p2 = Part(material_id=m2.id, order_index=0, title="P", passage={"paragraphs": []},
                  first_number=1)
        session.add_all([part, p2])
        alpha = Lexeme(lemma="alpha", pos="n", frequency_band="core", frequency_source="ngsl",
                       cefr="C1", enriched_at=datetime.now(timezone.utc))
        omega = Lexeme(lemma="omega", pos="n", cefr="B1", enriched_at=datetime.now(timezone.utc))
        verb = Lexeme(lemma="alpha", pos="v", cefr="B1", enriched_at=datetime.now(timezone.utc))
        session.add_all([alpha, omega, verb])
        await session.flush()

        def sense(lexeme, rank, definition, uz, cefr, **kw):
            return LexemeSense(lexeme_id=lexeme.id, sense_rank=rank, definition_en=definition,
                               meaning_uz=uz, cefr=cefr, provisional=False, **kw)

        a1 = sense(alpha, 1, "an invented first thing", "birinchi", "C1",
                   needs_review=True, review_reasons=["ngsl_conflict"])
        a2 = sense(alpha, 2, "an invented second thing", "ikkinchi", "B2")
        a3 = sense(alpha, 3, "an invented third thing", "uchinchi", "B1")
        o1 = sense(omega, 1, "an invented last thing", "oxirgi", "B1")
        o2 = sense(omega, 2, "an invented final thing", "yakuniy", "B2")
        v1 = sense(verb, 1, "to invent a thing", "o'ylab topmoq", "B1")
        session.add_all([a1, a2, a3, o1, o2, v1])
        await session.flush()

        def row(material_, part_, lemma, lexeme, sense_, pos="n", phrase=False):
            return MaterialVocabulary(
                material_id=material_.id, part_id=part_.id, lemma=lemma, surface=lemma, pos=pos,
                meaning_en="m", meaning_uz="u", example="An invented sentence.", cefr_level="B2",
                lexeme_id=lexeme.id, sense_id=sense_.id, is_phrase=phrase)

        r1 = row(material, part, "alpha", alpha, a1)
        r2 = row(m2, p2, "alpha", alpha, a2)
        r3 = row(material, part, "alphas", alpha, a3)
        ro1 = row(material, part, "omega", omega, o1)
        session.add_all([r1, r2, r3, ro1])
        await session.flush()

        reviewed = datetime.now(timezone.utc) - timedelta(days=1)
        # learner 1 saved BOTH a1 and a2 (a2's word has more progress); learner 2 only a2
        sw1 = SavedWord(user_id=user.id, lemma="alpha", lexeme_sense_id=a1.id, reps=2,
                        passive_last_review=reviewed)
        sw2 = SavedWord(user_id=user.id, lemma="alpha", lexeme_sense_id=a2.id, reps=9,
                        passive_last_review=reviewed)
        sw3 = SavedWord(user_id=u2.id, lemma="alpha", lexeme_sense_id=a2.id, reps=1)
        session.add_all([sw1, sw2, sw3])
        await session.flush()
        c1 = SavedWordContext(saved_word_id=sw1.id, material_id=material.id, vocabulary_id=r1.id,
                              meaning_en="m", meaning_uz="u")
        c2 = SavedWordContext(saved_word_id=sw2.id, material_id=m2.id, vocabulary_id=r2.id,
                              meaning_en="m", meaning_uz="u")
        # the same material as c1: a duplicate that must be dropped on a fold
        c2b = SavedWordContext(saved_word_id=sw2.id, material_id=material.id,
                               meaning_en="m", meaning_uz="u")
        session.add_all([c1, c2, c2b])
        await session.flush()
        log = VocabularyReviewLog(user_id=user.id, saved_word_id=sw1.id, lemma="alpha",
                                  context_id=c1.id, direction="passive", exercise_type="choice",
                                  rating=3, state=1, reviewed_at=reviewed)
        deck = Deck(user_id=user.id, title="d")
        session.add(deck)
        await session.flush()
        session.add_all([log, DeckWord(deck_id=deck.id, saved_word_id=sw1.id)])
        report = TranslationReport(user_id=u2.id, lexeme_sense_id=a2.id, status="open", note="bad")
        listing = WordList(key="t", title="t")
        session.add_all([report, listing])
        await session.flush()
        entry = WordListEntry(list_id=listing.id, lemma="alpha", rank=1, lexeme_id=alpha.id,
                              sense_id=a3.id)
        rec_a2 = WordRecording(lexeme_sense_id=a2.id, accent="british", storage_key="rec/x.m4a",
                               duration_ms=10, source_file="x", basis="ref")
        rec_a1 = WordRecording(lexeme_sense_id=a1.id, accent="british", storage_key="rec/y.m4a",
                               duration_ms=10, source_file="y", basis="ref")
        rec_a3 = WordRecording(lexeme_sense_id=a3.id, accent="american", storage_key="rec/z.m4a",
                               duration_ms=10, source_file="z", basis="ref")
        ai = LexiconAiReview(sense_id=a3.id, run_id="old", action="approve", confidence="high",
                             before={}, after={})
        session.add_all([entry, rec_a1, rec_a2, rec_a3, ai])
        await session.commit()
        for name, obj in dict(
            user=user, u2=u2, material=material, m2=m2, alpha=alpha, omega=omega, verb=verb,
            a1=a1, a2=a2, a3=a3, o1=o1, o2=o2, v1=v1, r1=r1, r2=r2, r3=r3, ro1=ro1, sw1=sw1,
            sw2=sw2, sw3=sw3, c1=c1, c2=c2, c2b=c2b, log=log, report=report, entry=entry,
            rec_a1=rec_a1, rec_a2=rec_a2, rec_a3=rec_a3, ai=ai, deck=deck,
        ).items():
            setattr(w, name, obj.id)
    return w


async def dump() -> dict:
    """Every row of every table the tool may touch."""
    out = {}
    async with async_session_factory() as session:
        for name in lr.TABLE_ORDER:
            table = lr.TABLES[name]
            rows = (await session.execute(core_select(table))).mappings().all()
            out[name] = sorted((lr._image(r) for r in rows), key=lambda i: json.dumps(i, sort_keys=True))
        await session.rollback()
    return out


def op(kind: str, note: str = "because invented", **fields) -> dict:
    return {"op": kind, "note": note, **{k: (str(v) if isinstance(v, uuid.UUID) else v)
                                         for k, v in fields.items()}}


def ids(*values) -> list[str]:
    return [str(v) for v in values]


async def run(tmp_path, ops: list[dict], *, write: bool = True) -> tuple[list[lr.Result], str]:
    run_id = uuid.uuid4().hex[:12]
    async with async_session_factory() as session:
        results = await lr.process(session, list(enumerate(ops, start=1)), write=write,
                                   run_id=run_id, out_dir=tmp_path, database=TEST_DB,
                                   decisions="test")
        if write:
            await session.commit()
        else:
            await session.rollback()
    return results, run_id


async def undo(tmp_path, run_id, *, write=True, only=None):
    return await lr.undo(async_session_factory, run_id, write=write, out_dir=tmp_path, only=only)


def outcomes(results) -> list[str]:
    return [r.outcome for r in results]


async def get(model, ident):
    async with async_session_factory() as session:
        obj = await session.get(model, ident)
        return obj


async def count(model, *clause) -> int:
    async with async_session_factory() as session:
        return len((await session.exec(select(model).where(*clause))).all())


# --- parsing (no database) -----------------------------------------------------------------------


def test_parse_rejects_what_it_cannot_be_sure_of():
    u = str(uuid.uuid4())
    bad = [
        ({"op": "nope", "note": "xxx"}, "op must be"),
        ({"op": "delete_lexeme", "lexeme_id": u, "lemma": "x"}, "needs a note"),
        ({"op": "delete_lexeme", "note": "xxx", "lexeme_id": u}, "lemma is required"),
        ({"op": "delete_lexeme", "note": "xxx", "lexeme_id": u, "lemma": "x", "extra": 1}, "unknown key"),
        ({"op": "delete_lexeme", "note": "xxx", "lexeme_id": "zzz", "lemma": "x"}, "not a uuid"),
        ({"op": "merge_senses", "note": "xxx", "lexeme_id": u, "keep": u, "drop": [u]}, "also listed"),
        ({"op": "merge_senses", "note": "xxx", "lexeme_id": u, "keep": u, "drop": [str(uuid.uuid4())],
          "cefr": "Z9"}, "cefr"),
        ({"op": "merge_senses", "note": "xxx", "lexeme_id": u, "keep": u, "drop": [str(uuid.uuid4())],
          "meaning_uz": "ўзбек"}, "meaning_uz"),
        ({"op": "add_sense", "note": "xxx", "lexeme_id": u, "cald_ref": "a#0#0",
          "definition_en": "d", "cefr": "B1", "meaning_uz": ""}, "translate"),
        ({"op": "add_sense", "note": "xxx", "lexeme_id": u, "cald_ref": "a#0#0",
          "definition_en": "d", "cefr": "B1"}, "meaning_uz is required"),
        ({"op": "create_phrase", "note": "xxx", "lemma": "a b", "pos": "zz", "definition_en": "d",
          "cefr": "B1", "meaning_uz": "x", "rows": [u]}, "pos must"),
        ({"op": "human", "lexeme_id": u, "note": ""}, "needs a note"),
        ({"op": ["x"], "note": "xxx"}, "op must be a string"),
        ({"op": "keep", "lexeme_id": u, "oops": 1}, "unknown key"),
        ({"op": "skip", "lexeme_id": u, "cald_ref": "a", "surprise": 1}, "unknown key"),
        ({"op": "human", "lexeme_id": u, "note": "check", "x": 1}, "unknown key"),
        ({"op": "delete_lexeme", "note": "xxx", "lexeme_id": u, "lemma": "x",
          "allow_saved_words": "yes"}, "true or false"),
    ]
    for raw, why in bad:
        with pytest.raises(lr.Reject, match=why):
            lr.parse_op(raw)
    ok = lr.parse_op({"op": "create_entry", "note": "xxx", "lemma": "  Bank Account ", "definition_en":
                      "( a, b) a store of money", "cefr": "B1", "meaning_uz": "hisob", "rows": [u],
                      "cald_ref": "x#0#0", "_comment": "ignored"})
    assert ok["op"] == "create_phrase" and ok["lemma"] == "bank account" and ok["pos"] == "phr"
    assert ok["definition_en"] == "a store of money"  # the label-less list is dropped
    assert lr.parse_op({"op": "keep", "lexeme_id": u, "headword": "x"})["op"] == "keep"


# --- merge_senses, the saved-word rule, undo --------------------------------------------------------


async def test_merge_senses_moves_everything_and_keeps_the_word_with_more_progress(clean):
    w = await world()
    before = await dump()
    results, run_id = await run(clean, [op(
        "merge_senses", lexeme_id=w.alpha, keep=w.a1, drop=ids(w.a2, w.a3),
        cefr="B2", meaning_uz="birinchi, asosiy", meaning_uz_alt="avval")])
    assert outcomes(results) == ["applied"], results

    async with async_session_factory() as session:
        keep = await session.get(LexemeSense, w.a1)
        assert await session.get(LexemeSense, w.a2) is None
        assert await session.get(LexemeSense, w.a3) is None
        bot = (await session.exec(select(User).where(User.email == REVIEW_BOT_EMAIL))).one()
        assert keep.approved_by == bot.id and keep.approved_at is not None
        assert keep.meaning_uz == "birinchi, asosiy" and keep.meaning_uz_alt == "avval"
        assert keep.cefr == "B2" and keep.cefr_source == "ours"
        assert "invented" in keep.review_note or "because" in keep.review_note
        assert keep.sense_rank == 1
        assert (await session.get(Lexeme, w.alpha)).cefr == "B2"  # rank-1 sense
        for r in (w.r1, w.r2, w.r3):
            assert (await session.get(MaterialVocabulary, r)).sense_id == w.a1
        # the saved-word collision: learner 1's word on a2 (9 reps) beats the one on a1 (2)
        learner = (await session.exec(select(SavedWord).where(
            SavedWord.user_id == w.user))).all()
        assert [(x.id, x.lexeme_sense_id, x.reps) for x in learner] == [(w.sw2, w.a1, 9)]
        # contexts: c1 (material 1) and c2 (material 2) survive on the winner; c2b was the
        # winner's own duplicate of c1's material, so exactly one context per material remains
        contexts = (await session.exec(select(SavedWordContext).where(
            SavedWordContext.saved_word_id == w.sw2))).all()
        assert sorted(c.material_id for c in contexts) == sorted([w.material, w.m2])
        # the loser's review log is kept as history but detached: the winner's own
        # schedule is not extended by another card's answers (its context was a
        # duplicate and was dropped, so that link is gone too); the deck follows
        log = await session.get(VocabularyReviewLog, w.log)
        assert log is not None and log.saved_word_id is None and log.context_id is None
        winner = await session.get(SavedWord, w.sw2)
        assert (winner.reps, winner.lapses) == (9, 0)
        assert [d.saved_word_id for d in (await session.exec(select(DeckWord))).all()] == [w.sw2]
        # learner 2's word and report, the list entry
        assert (await session.get(SavedWord, w.sw3)).lexeme_sense_id == w.a1
        assert (await session.get(TranslationReport, w.report)).lexeme_sense_id == w.a1
        assert (await session.get(WordListEntry, w.entry)).sense_id == w.a1
        # recordings: a1 had british, a2's british is dropped, a3's american moves
        recs = (await session.exec(select(WordRecording))).all()
        assert sorted((r.lexeme_sense_id, r.accent) for r in recs) == [
            (w.a1, "american"), (w.a1, "british")]
        assert await session.get(LexiconAiReview, w.ai) is None
        await session.rollback()

    report = lr.read_report(lr.report_path(clean, run_id))
    assert [r["type"] for r in report] == ["run", "op", "commit"]

    undone = await undo(clean, run_id)
    assert outcomes(undone) == ["undone"], undone
    assert await dump() == before  # exact, every table


async def test_the_dry_run_executes_for_real_and_leaves_nothing(clean):
    w = await world()
    before = await dump()
    ops = [op("merge_senses", lexeme_id=w.alpha, keep=w.a1, drop=ids(w.a2)),
           op("delete_lexeme", lexeme_id=w.omega, lemma="omega")]
    dry, _ = await run(clean, ops, write=False)
    assert outcomes(dry) == ["would apply", "would apply"]
    assert await dump() == before
    assert list(clean.glob("run_*.jsonl")) == []
    assert lexicon_service.read_rules_file()["refused"] == []
    real, _ = await run(clean, ops)
    assert outcomes(real) == ["applied", "applied"]


async def test_a_person_approved_sense_is_never_dropped_or_overwritten(clean):
    w = await world()
    async with async_session_factory() as session:
        a2 = await session.get(LexemeSense, w.a2)
        a2.approved_by, a2.approved_at = w.user, datetime.now(timezone.utc)
        session.add(a2)
        await session.commit()
    results, _ = await run(clean, [
        op("merge_senses", lexeme_id=w.alpha, keep=w.a1, drop=[str(w.a2)]),
        op("merge_senses", lexeme_id=w.alpha, keep=w.a2, drop=[str(w.a3)], meaning_uz="boshqa"),
        op("merge_senses", lexeme_id=w.alpha, keep=w.a2, drop=[str(w.a3)]),  # keep untouched: fine
    ])
    assert outcomes(results) == ["rejected", "rejected", "applied"]
    assert "person" in results[0].detail and "person" in results[1].detail
    a2 = await get(LexemeSense, w.a2)
    assert a2.approved_by == w.user  # the person's approval stays


async def test_ops_are_validated_against_what_earlier_ops_left(clean):
    w = await world()
    results, _ = await run(clean, [
        op("merge_senses", lexeme_id=w.alpha, keep=w.a1, drop=[str(w.a3)]),
        op("merge_senses", lexeme_id=w.alpha, keep=w.a2, drop=[str(w.a3)]),
        # rows moved off omega first, then the (row-less) lexeme is deleted
        op("relink_rows", rows=[str(w.ro1)], sense_id=w.a2),
        op("delete_lexeme", lexeme_id=w.omega, lemma="omega"),
        op("delete_lexeme", lexeme_id=w.omega, lemma="omega"),
    ])
    assert outcomes(results) == ["applied", "rejected", "applied", "applied", "rejected"]
    assert f"removed by op #1" in results[1].detail
    assert f"removed by op #4" in results[4].detail
    assert (await get(MaterialVocabulary, w.ro1)).lexeme_id == w.alpha


async def test_a_failing_op_writes_nothing_and_the_next_still_runs(clean):
    w = await world()
    before_a3 = await get(LexemeSense, w.a3)
    results, _ = await run(clean, [
        # second drop id is not a sense of alpha: the whole op is refused
        op("merge_senses", lexeme_id=w.alpha, keep=w.a1, drop=ids(w.a2, w.o1)),
        op("merge_senses", lexeme_id=w.alpha, keep=w.a1, drop=[str(w.a3)]),
    ])
    assert outcomes(results) == ["rejected", "applied"]
    assert await get(LexemeSense, w.a2) is not None
    assert await get(LexemeSense, w.a3) is None and before_a3 is not None


async def test_undo_skips_an_op_whose_rows_changed_since_and_reverses_the_rest(clean):
    w = await world()
    before = await dump()
    results, run_id = await run(clean, [
        op("rename_lexeme", lexeme_id=w.omega, lemma="omegas"),
        op("merge_senses", lexeme_id=w.alpha, keep=w.a1, drop=[str(w.a3)]),
    ])
    assert outcomes(results) == ["applied", "applied"]
    async with async_session_factory() as session:  # a person edits the kept sense afterwards
        a1 = await session.get(LexemeSense, w.a1)
        a1.meaning_uz = "tahrirlangan"
        session.add(a1)
        await session.commit()
    undone = await undo(clean, run_id)
    by_n = {r.n: r for r in undone}
    assert by_n[2].outcome == "skipped" and "changed since" in by_n[2].detail
    assert by_n[1].outcome == "undone"
    assert (await get(Lexeme, w.omega)).lemma == "omega"
    assert await get(LexemeSense, w.a3) is None  # the merge stays
    again = await undo(clean, run_id)
    assert {r.n: r.outcome for r in again} == {2: "skipped", 1: "already undone"}
    assert before != await dump()


async def test_undo_dry_run_checks_without_writing(clean):
    w = await world()
    _, run_id = await run(clean, [op("rename_lexeme", lexeme_id=w.omega, lemma="omegas")])
    snap = await dump()
    assert outcomes(await undo(clean, run_id, write=False)) == ["would undo"]
    assert await dump() == snap


# --- delete_lexeme and the refused list -----------------------------------------------------------------


async def test_delete_lexeme_removes_everything_and_makes_the_lemma_refused(clean):
    w = await world()
    async with async_session_factory() as session:  # (alpha, v) would stop the refusal
        await session.delete(await session.get(LexemeSense, w.v1))
        await session.flush()
        await session.delete(await session.get(Lexeme, w.verb))
        await session.commit()
    before = await dump()
    results, run_id = await run(clean, [
        op("delete_lexeme", lexeme_id=w.alpha, lemma="WRONG", allow_saved_words=True),
        op("delete_lexeme", lexeme_id=w.alpha, lemma="alpha", allow_saved_words=True),
    ])
    assert outcomes(results) == ["rejected", "applied"]
    assert "mismatch" in results[0].detail
    assert "saved words: 3 of 2 learner(s)" in results[1].detail
    async with async_session_factory() as session:
        assert await session.get(Lexeme, w.alpha) is None
        for model in (SavedWord, SavedWordContext, TranslationReport, WordRecording,
                      LexiconAiReview, WordListEntry):
            assert (await session.exec(select(model))).all() == [], model
        assert (await session.exec(select(MaterialVocabulary))).all() == [
            await session.get(MaterialVocabulary, w.ro1)]
        log = await session.get(VocabularyReviewLog, w.log)
        assert log is not None and log.saved_word_id is None and log.context_id is None
        assert (await session.exec(select(DeckWord))).all() == []
        await session.rollback()
    assert lexicon_service.is_refused_lemma("alpha") and lexicon_service.is_refused_lemma("ALPHA")
    assert lexicon_service.read_rules_file()["refused"][0]["lemma"] == "alpha"
    undone = await undo(clean, run_id)
    assert {r.n: r.outcome for r in undone} == {2: "undone"}  # #1 was rejected: not in the report
    assert await dump() == before
    assert not lexicon_service.is_refused_lemma("alpha")


async def test_delete_lexeme_refuses_the_lemma_only_when_that_blocks_no_real_word(clean, monkeypatch):
    w = await world()
    monkeypatch.setattr(lr, "cald_has_headword", lambda lemma: lemma == "omega")
    async with async_session_factory() as session:  # `omegas` reduces to the existing `omega`
        session.add(Lexeme(lemma="omegas", pos="n"))
        await session.commit()
        omegas = (await session.exec(select(Lexeme).where(Lexeme.lemma == "omegas"))).one().id
    results, _ = await run(clean, [
        op("delete_lexeme", lexeme_id=w.verb, lemma="alpha"),   # (alpha, n) still exists
        op("delete_lexeme", lexeme_id=omegas, lemma="omegas"),  # an inflected form of omega
        op("delete_lexeme", lexeme_id=w.omega, lemma="omega"),  # a CALD headword
    ])
    assert outcomes(results) == ["applied", "applied", "applied"]
    assert "not refused: another lexeme has this lemma" in results[0].detail
    assert "not refused: it is an inflected form" in results[1].detail
    assert "not refused: CALD lists it as a headword" in results[2].detail
    assert lexicon_service.read_rules_file()["refused"] == []
    # a lone, non-headword lemma is refused (alpha (n) is now the only one left)
    results, run_id = await run(clean, [op("delete_lexeme", lexeme_id=w.alpha, lemma="alpha",
                                           allow_saved_words=True)])
    assert "lemma refused in future" in results[0].detail
    assert lexicon_service.is_refused_lemma("alpha")
    entry = lexicon_service.read_rules_file()["refused"][0]
    assert set(entry) == {"lemma", "run", "op"}  # never the reviewer's note
    await undo(clean, run_id)
    assert not lexicon_service.is_refused_lemma("alpha")


async def test_refusal_fails_loudly_without_the_cald_index(clean, monkeypatch):
    w = await world()
    monkeypatch.setattr(lr, "cald_has_headword", REAL_CALD_HEADWORD)
    monkeypatch.setattr(lr, "_INDEX", None)

    def boom():
        raise FileNotFoundError("no index here")

    monkeypatch.setattr(lr.lc, "load_index_data", boom)
    results, _ = await run(clean, [
        op("delete_lexeme", lexeme_id=w.omega, lemma="omega"),
        op("delete_lexeme", lexeme_id=w.omega, lemma="omega", refuse=False),
    ])
    assert outcomes(results) == ["rejected", "applied"]
    assert "CALD index could not be loaded" in results[0].detail
    assert "not refused" in results[1].detail
    assert lexicon_service.read_rules_file()["refused"] == []


async def test_delete_lexeme_will_not_delete_saved_words_unasked(clean):
    w = await world()
    before = await dump()
    results, _ = await run(clean, [op("delete_lexeme", lexeme_id=w.alpha, lemma="alpha")])
    assert outcomes(results) == ["rejected"]
    assert "3 saved word(s) of 2 learner(s)" in results[0].detail and "allow_saved_words" in results[0].detail
    assert await dump() == before


async def test_a_refused_lemma_stays_out_of_the_lookup_path_but_not_the_writers(clean):
    from app.services import word_lists_build as wlb

    lexicon_service.write_rules_file({"refused": [{"lemma": "zzjunk", "run": "x", "op": 1}],
                                      "aliases": []})
    assert lexicon_service.is_refused_lemma("ZZJunk")
    assert not lexicon_service.is_excluded_word("zzjunk")  # the learner's lookup still answers
    assert wlb.exclusion_reason("zzjunk", []) == "refused"


async def test_an_alias_never_beats_a_real_lexeme(clean):
    w = await world()
    lexicon_service.write_rules_file({"refused": [], "aliases": [
        {"from": {"lemma": "omega", "pos": "n"}, "to": {"lemma": "alpha", "pos": "n"}}]})
    async with async_session_factory() as session:
        row = MaterialVocabulary(
            material_id=w.m2, part_id=(await session.exec(select(MaterialVocabulary.part_id).where(
                MaterialVocabulary.id == w.r2))).one(), lemma="omega", surface="omega", pos="n",
            meaning_en="x", meaning_uz="x", cefr_level="B1")
        await lexicon_service.link_row(session, row)
        assert row.lexeme_id == w.omega  # omega (n) exists: exact match first
        await session.rollback()


async def test_merge_lexeme_skips_alias_sources_that_have_their_own_lexeme(clean):
    w = await world()
    async with async_session_factory() as session:
        session.add(Lexeme(lemma="gamma", pos="v"))
        ro1 = await session.get(MaterialVocabulary, w.ro1)
        ro1.lemma, ro1.pos = "gamma", "v"
        session.add(ro1)
        await session.commit()
    results, _ = await run(clean, [op(
        "merge_lexeme", **{"from": w.omega, "into": w.alpha,
                           "senses": {str(w.o1): "move", str(w.o2): "move"}})])
    assert outcomes(results) == ["applied"], results
    aliases = lexicon_service.lexicon_rules().aliases
    assert aliases == {("omega", "n"): ("alpha", "n")}  # (gamma, v) is a real lexeme


async def test_a_malformed_rules_file_never_raises_and_keeps_the_last_good_rules(clean):
    path = lexicon_service.RULES_PATH
    lexicon_service.write_rules_file({"refused": [{"lemma": "zzjunk", "run": "x", "op": 1}],
                                      "aliases": []})
    assert lexicon_service.is_refused_lemma("zzjunk")
    path.write_text("{ this is not json", encoding="utf-8")
    assert lexicon_service.is_refused_lemma("zzjunk")        # last good rules stay
    assert lexicon_service.lexicon_rules().aliases == {}
    with pytest.raises(ValueError):                           # the tool refuses to overwrite it
        lexicon_service.read_rules_file()
    path.write_text(json.dumps({"refused": [{"lemma": "ok1"}, 5, {"nolemma": 1}, {"lemma": ""}],
                                "aliases": [{"from": {"lemma": "a"}}, "x",
                                            {"from": {"lemma": "p", "pos": "n"},
                                             "to": {"lemma": "q", "pos": "n"}}]}))
    rules = lexicon_service.lexicon_rules()
    assert rules.refused == {"ok1"} and rules.aliases == {("p", "n"): ("q", "n")}
    path.write_text("[]")
    assert lexicon_service.lexicon_rules().refused == {"ok1"}   # not an object: keep last good
    path.unlink()
    assert lexicon_service.lexicon_rules().refused == frozenset()


async def test_rules_are_written_after_the_commit_from_a_fresh_read(clean):
    w = await world()
    lexicon_service.write_rules_file({"refused": [{"lemma": "hand", "run": "h", "op": 0}],
                                      "aliases": []})
    results, run_id = await run(clean, [op("rename_lexeme", lexeme_id=w.omega, lemma="omegon")])
    kinds = [r["type"] for r in lr.read_report(lr.report_path(clean, run_id))]
    assert kinds == ["run", "op", "commit", "rules"]
    data = lexicon_service.read_rules_file()
    assert [e["lemma"] for e in data["refused"]] == ["hand"]  # the hand edit survived
    assert data["aliases"][0]["op"] == 1 and "note" not in data["aliases"][0]
    # a hand edit made after the run is kept by undo too
    data["refused"].append({"lemma": "later", "run": "h", "op": 0})
    lexicon_service.write_rules_file(data)
    await undo(clean, run_id)
    data = lexicon_service.read_rules_file()
    assert data["aliases"] == [] and sorted(e["lemma"] for e in data["refused"]) == ["hand", "later"]


async def test_undo_reverts_written_rules_when_the_commit_marker_is_missing(clean):
    w = await world()
    _, run_id = await run(clean, [op("rename_lexeme", lexeme_id=w.omega, lemma="omegon")])
    path = lr.report_path(clean, run_id)
    lines = [ln for ln in path.read_text().splitlines() if '"type": "commit"' not in ln]
    path.write_text("\n".join(lines) + "\n")
    async with async_session_factory() as session:   # and the op's rows are gone / changed
        lexeme = await session.get(Lexeme, w.omega)
        lexeme.lemma = "somebody-else"
        session.add(lexeme)
        await session.commit()
    results = await undo(clean, run_id)
    assert results[0].outcome == "undone" and "never committed" in results[0].detail
    assert lexicon_service.lexicon_rules().aliases == {}


async def test_undo_validates_the_run_id_and_the_tables(clean):
    with pytest.raises(ValueError):
        await undo(clean, "../../etc")
    async with async_session_factory() as session:
        with pytest.raises(ValueError):
            await lr.reverse_changes(session, {"updated": [{"table": "users", "pk": {}, "after": {}}]},
                                     write=True)


async def test_merge_lexeme_refuses_a_name_target_and_marks_rows_of_a_phrase_target(clean):
    w = await world()
    async with async_session_factory() as session:
        ox = await session.get(Lexeme, w.alpha)
        ox.is_proper_noun = True
        session.add(ox)
        await session.commit()
    senses = {str(w.o1): "move", str(w.o2): "move"}
    results, _ = await run(clean, [op("merge_lexeme", **{"from": w.omega, "into": w.alpha,
                                                         "senses": senses})])
    assert outcomes(results) == ["rejected"] and "name or function word" in results[0].detail
    async with async_session_factory() as session:
        ox = await session.get(Lexeme, w.alpha)
        ox.is_proper_noun, ox.is_phrase = False, True
        session.add(ox)
        await session.commit()
    results, _ = await run(clean, [op("merge_lexeme", **{"from": w.omega, "into": w.alpha,
                                                         "senses": senses})])
    assert outcomes(results) == ["applied"]
    assert (await get(MaterialVocabulary, w.ro1)).is_phrase


async def test_the_fold_keeps_the_losers_exposures_and_detaches_its_logs(clean):
    from app.models.word_audio_log import OnTheGoExposure

    w = await world()
    async with async_session_factory() as session:
        session.add(OnTheGoExposure(user_id=w.user, saved_word_id=w.sw1, lemma="alpha"))
        await session.commit()
    await run(clean, [op("merge_senses", lexeme_id=w.alpha, keep=w.a1, drop=[str(w.a2)])])
    async with async_session_factory() as session:
        exposure = (await session.exec(select(OnTheGoExposure))).one()
        assert exposure.saved_word_id == w.sw2
        await session.rollback()


async def test_a_refused_lemma_is_not_written_again(clean):
    w = await world()
    await run(clean, [op("delete_lexeme", lexeme_id=w.omega, lemma="omega")])
    assert lexicon_service.is_refused_lemma("omega")
    assert not lexicon_service.is_refused_lemma("alpha")


# --- merge_lexeme / rename_lexeme and the alias -------------------------------------------------------------


async def test_merge_lexeme_absorbs_moves_and_leaves_an_alias(clean):
    w = await world()
    before = await dump()
    # `omega` into `alpha`: o1 absorbed into a2, o2 moved under alpha
    results, run_id = await run(clean, [op(
        "merge_lexeme", **{"from": w.omega, "into": w.alpha,
                           "senses": {str(w.o1): str(w.a2), str(w.o2): "move"}})])
    assert outcomes(results) == ["applied"], results
    async with async_session_factory() as session:
        assert await session.get(Lexeme, w.omega) is None
        senses = (await session.exec(select(LexemeSense).where(
            LexemeSense.lexeme_id == w.alpha).order_by(LexemeSense.sense_rank))).all()
        assert [s.sense_rank for s in senses] == [1, 2, 3, 4]
        assert senses[-1].id == w.o2  # moved ones are appended
        ro1 = await session.get(MaterialVocabulary, w.ro1)
        assert (ro1.lexeme_id, ro1.sense_id, ro1.lemma) == (w.alpha, w.a2, "omega")  # lemma kept
        await session.rollback()
    aliases = lexicon_service.lexicon_rules().aliases
    assert aliases[("omega", "n")] == ("alpha", "n")
    # a later write under the old spelling finds the survivor
    async with async_session_factory() as session:
        row = MaterialVocabulary(
            material_id=w.m2, part_id=(await session.exec(select(MaterialVocabulary.part_id).where(
                MaterialVocabulary.id == w.r2))).one(), lemma="omega", surface="omega", pos="n",
            meaning_en="an invented last thing", meaning_uz="x", cefr_level="B1")
        await lexicon_service.link_row(session, row)
        assert row.lexeme_id == w.alpha
        await session.rollback()
    await undo(clean, run_id)
    assert await dump() == before
    assert lexicon_service.lexicon_rules().aliases == {}


async def test_merge_lexeme_needs_every_sense_mapped(clean):
    w = await world()
    results, _ = await run(clean, [op(
        "merge_lexeme", **{"from": w.omega, "into": w.alpha, "senses": {str(w.o1): "move"}})])
    assert outcomes(results) == ["rejected"] and "must be mapped" in results[0].detail


async def test_merge_lexeme_across_parts_of_speech_and_chained_aliases(clean):
    w = await world()
    results, _ = await run(clean, [
        op("merge_lexeme", **{"from": w.omega, "into": w.verb,
                              "senses": {str(w.o1): "move", str(w.o2): "move"}}),
        op("merge_lexeme", **{"from": w.verb, "into": w.alpha,
                              "senses": {str(w.v1): str(w.a1), str(w.o1): "move",
                                         str(w.o2): "move"}}),
    ])
    assert outcomes(results) == ["applied", "applied"], results
    aliases = lexicon_service.lexicon_rules().aliases
    # omega -> alpha(v) was re-pointed when alpha(v) itself was merged
    assert aliases[("omega", "n")] == ("alpha", "n") and aliases[("alpha", "v")] == ("alpha", "n")
    ro1 = await get(MaterialVocabulary, w.ro1)
    assert ro1.lexeme_id == w.alpha and ro1.pos == "n"


async def test_rename_lexeme_and_its_collision(clean):
    w = await world()
    results, run_id = await run(clean, [
        op("rename_lexeme", lexeme_id=w.omega, lemma="alpha"),   # (alpha, n) exists
        op("rename_lexeme", lexeme_id=w.omega, lemma="omegon"),
    ])
    assert outcomes(results) == ["rejected", "applied"]
    assert "merge_lexeme" in results[0].detail
    assert (await get(Lexeme, w.omega)).lemma == "omegon"
    assert lexicon_service.lexicon_rules().aliases[("omega", "n")] == ("omegon", "n")
    assert (await get(MaterialVocabulary, w.ro1)).lemma == "omega"
    await undo(clean, run_id)
    assert (await get(Lexeme, w.omega)).lemma == "omega"
    assert lexicon_service.lexicon_rules().aliases == {}


# --- mark_function_word, relink, delete_sense, delete_rows ---------------------------------------------------


async def test_mark_function_word_hides_its_rows(clean):
    w = await world()
    before = await dump()
    results, run_id = await run(clean, [op("mark_function_word", lexeme_id=w.omega),
                                        op("mark_function_word", lexeme_id=w.omega)])
    assert outcomes(results) == ["applied", "unchanged"]
    assert (await get(Lexeme, w.omega)).is_function_word
    assert (await get(MaterialVocabulary, w.ro1)).hidden
    await undo(clean, run_id)
    assert await dump() == before


async def test_relink_rows_moves_across_lexemes(clean):
    w = await world()
    before = await dump()
    results, run_id = await run(clean, [
        op("relink_rows", rows=[str(w.r1)], sense_id=w.o2),
        op("relink_rows", rows=[str(w.r1)], sense_id=w.o2),
        op("relink_rows", rows=[str(uuid.uuid4())], sense_id=w.o2),
    ])
    assert outcomes(results) == ["applied", "unchanged", "rejected"]
    r1 = await get(MaterialVocabulary, w.r1)
    assert (r1.lexeme_id, r1.sense_id) == (w.omega, w.o2)
    await undo(clean, run_id)
    assert await dump() == before


async def test_delete_sense_needs_into_when_it_is_referenced(clean):
    w = await world()
    before = await dump()
    results, run_id = await run(clean, [
        op("delete_sense", sense_id=w.a2),
        op("delete_sense", sense_id=w.a2, into=w.a2),
        op("delete_sense", sense_id=w.a2, into=w.a1),
        op("delete_sense", sense_id=w.v1),   # a lexeme's only sense
        op("delete_sense", sense_id=w.o2),   # no dependants, no `into`
    ])
    assert outcomes(results) == ["rejected", "rejected", "applied", "rejected", "applied"]
    assert "still referenced" in results[0].detail and "delete_lexeme" in results[3].detail
    assert (await get(MaterialVocabulary, w.r2)).sense_id == w.a1
    assert await get(LexemeSense, w.o2) is None
    async with async_session_factory() as session:
        ranks = [s.sense_rank for s in (await session.exec(select(LexemeSense).where(
            LexemeSense.lexeme_id == w.alpha).order_by(LexemeSense.sense_rank))).all()]
        assert ranks == [1, 2]
        await session.rollback()
    await undo(clean, run_id)
    assert await dump() == before


async def test_delete_rows_unlinks_what_pointed_at_them(clean):
    w = await world()
    before = await dump()
    results, run_id = await run(clean, [op("delete_rows", rows=ids(w.r1, w.r2))])
    assert outcomes(results) == ["applied"]
    async with async_session_factory() as session:
        assert await session.get(MaterialVocabulary, w.r1) is None
        c1 = await session.get(SavedWordContext, w.c1)
        assert c1 is not None and c1.vocabulary_id is None  # the saved word stays
        assert await session.get(SavedWord, w.sw1) is not None
        await session.rollback()
    await undo(clean, run_id)
    assert await dump() == before


# --- create_phrase / create_entry / add_sense --------------------------------------------------------------


def _new_sense_fields(**extra) -> dict:
    return {"definition_en": "( x, y) an invented compound thing", "cefr": "B2",
            "meaning_uz": "yangi narsa", "meaning_uz_alt": "boshqa narsa",
            "cald_ref": "alpha beta#0#0", "cald_cefr": "B2", **extra}


async def test_create_phrase_moves_rows_and_drops_the_bare_words_sense(clean):
    w = await world()
    before = await dump()
    results, run_id = await run(clean, [
        # a2 still has r2 and a saved word: naming only a1's row is not enough
        op("create_phrase", lemma="alpha beta", rows=[str(w.r1)], drop_sense=w.a2,
           **_new_sense_fields()),
        op("create_phrase", lemma="alpha beta", rows=ids(w.r1, w.r2), drop_sense=w.a2,
           **_new_sense_fields()),
    ])
    assert outcomes(results) == ["rejected", "applied"], results
    assert "still has 1 material row" in results[0].detail
    async with async_session_factory() as session:
        phrase = (await session.exec(select(Lexeme).where(Lexeme.lemma == "alpha beta"))).one()
        assert phrase.pos == "phr" and phrase.is_phrase and phrase.enriched_at is not None
        sense = (await session.exec(select(LexemeSense).where(
            LexemeSense.lexeme_id == phrase.id))).one()
        assert sense.definition_en == "an invented compound thing"
        assert (sense.definition_source, sense.licence, sense.cald_ref) == ("cald", "cald", "alpha beta#0#0")
        assert sense.cefr_source == "cald" and sense.cald_cefr == "B2"
        assert sense.approved_by is not None and phrase.cefr == "B2"
        for r in (w.r1, w.r2):
            row = await session.get(MaterialVocabulary, r)
            assert (row.lexeme_id, row.sense_id, row.is_phrase, row.pos, row.lemma) == (
                phrase.id, sense.id, True, "phr", "alpha")
        assert await session.get(LexemeSense, w.a2) is None
        # learners' saved words on the dropped sense follow to the phrase sense
        assert (await session.get(SavedWord, w.sw3)).lexeme_sense_id == sense.id
        await session.rollback()
    await undo(clean, run_id)
    assert await dump() == before


async def test_create_entry_makes_a_single_word_lexeme(clean):
    w = await world()
    results, _ = await run(clean, [
        {"op": "create_entry", "note": "banking is its own word", "lemma": "alphing", "pos": "n",
         "rows": [str(w.r1)], **_new_sense_fields(cald_ref="alphing#0#0")}])
    assert outcomes(results) == ["applied"]
    async with async_session_factory() as session:
        lexeme = (await session.exec(select(Lexeme).where(Lexeme.lemma == "alphing"))).one()
        assert lexeme.pos == "n" and not lexeme.is_phrase
        row = await session.get(MaterialVocabulary, w.r1)
        assert row.lexeme_id == lexeme.id and not row.is_phrase
        await session.rollback()


async def test_add_sense_appends_a_locked_sense_without_re_enrichment(clean):
    w = await world()
    before = await dump()
    stamp = (await get(Lexeme, w.alpha)).enriched_at
    results, run_id = await run(clean, [
        op("add_sense", lexeme_id=w.alpha, rows=[str(w.r1)], **_new_sense_fields(cald_ref="alpha#0#4")),
        op("add_sense", lexeme_id=w.alpha, **_new_sense_fields(cald_ref="alpha#0#4")),  # twice
        op("add_sense", lexeme_id=w.alpha, **_new_sense_fields(cald_ref="alpha#1#0", meaning_uz="")),
        op("add_sense", lexeme_id=w.alpha, rows=[str(w.ro1)],
           **_new_sense_fields(cald_ref="alpha#2#0")),   # a row of another lexeme
    ])
    assert outcomes(results) == ["applied", "rejected", "rejected", "rejected"], results
    async with async_session_factory() as session:
        alpha = await session.get(Lexeme, w.alpha)
        assert alpha.enriched_at == stamp  # never sent back through enrichment
        new = (await session.exec(select(LexemeSense).where(
            LexemeSense.cald_ref == "alpha#0#4"))).one()
        assert new.sense_rank == 4 and new.definition_source == "cald" and new.licence == "cald"
        assert new.approved_by is not None and new.provisional is False
        assert (await session.get(MaterialVocabulary, w.r1)).sense_id == new.id
        await session.rollback()
    await undo(clean, run_id)
    assert await dump() == before


async def test_a_judge_that_was_unsure_is_carried_onto_the_sense(clean):
    w = await world()
    results, _ = await run(clean, [op(
        "add_sense", lexeme_id=w.alpha, needs_review=True, review_reasons=["judge_unsure"],
        **_new_sense_fields())])
    assert outcomes(results) == ["applied"]
    async with async_session_factory() as session:
        sense = (await session.exec(select(LexemeSense).where(
            LexemeSense.cald_ref == "alpha beta#0#0"))).one()
        assert sense.needs_review and sense.review_reasons == ["judge_unsure"]
        await session.rollback()


# --- no-ops ---------------------------------------------------------------------------------------------


async def test_keep_skip_and_human_are_counted_and_human_flags_a_sense(clean):
    w = await world()
    results, run_id = await run(clean, [
        {"op": "keep", "lexeme_id": str(w.alpha)},
        {"op": "skip", "lexeme_id": str(w.alpha), "cald_ref": "x#0#0", "covered_by": str(w.a1)},
        {"op": "human", "lexeme_id": str(w.omega), "sense_id": None, "note": "which sense is it?"},
        {"op": "human", "lexeme_id": str(w.omega), "sense_id": None, "note": "which sense is it?"},
        {"op": "keep", "lexeme_id": str(uuid.uuid4())},
    ])
    assert outcomes(results) == ["noop", "noop", "applied", "unchanged", "rejected"]
    o1 = await get(LexemeSense, w.o1)  # rank 1
    assert o1.needs_review and "which sense is it?" in o1.review_note
    undone = await undo(clean, run_id)
    assert (await get(LexemeSense, w.o1)).review_note == ""
    assert "undone" in outcomes(undone)


# --- the journal guards itself ---------------------------------------------------------------------------


async def test_a_write_the_journal_did_not_capture_is_refused():
    w = await world()
    async with async_session_factory() as session:
        journal = lr.Journal(session)
        journal.attach()
        try:
            sense = await session.get(LexemeSense, w.a1)
            sense.meaning_uz = "x"
            session.add(sense)
            with pytest.raises(lr.UncapturedWrite):
                await session.flush()
        finally:
            journal.detach()
            await session.rollback()


# --- status -----------------------------------------------------------------------------------------------


async def test_status_lists_runs(clean):
    w = await world()
    _, run_id = await run(clean, [op("rename_lexeme", lexeme_id=w.omega, lemma="omegon")])
    runs = lr.list_runs(clean)
    assert [r["run_id"] for r in runs] == [run_id]
    assert runs[0]["ops"] == 1 and runs[0]["committed"] == 1 and runs[0]["undone"] == 0
    assert runs[0]["by_op"] == {"rename_lexeme:applied": 1}
    await undo(clean, run_id)
    assert lr.list_runs(clean)[0]["undone"] == 1


# --- translate ----------------------------------------------------------------------------------------------


class FakeGemini:
    def __init__(self, verdict="same", hard_after=None, fail=False):
        self.usage = le.UsageLog()
        self.hard_status = None
        self.verdict, self.hard_after, self.fail = verdict, hard_after, fail
        self.calls = 0

    async def aclose(self):
        pass

    async def ask(self, model, prompt, *, step, max_tokens=0, repair_flat=False, parse=None):
        self.calls += 1
        if self.fail or (self.hard_after is not None and self.calls > self.hard_after):
            self.hard_status = 402
            return None
        keys = re.findall(r"^k(\d+):", prompt, re.M)
        if step == "judge":
            reply = {"verdicts": {f"k{k}": {"verdict": self.verdict, "better": "b"} for k in keys}}
        else:
            tag = "a" if model == le.MODEL_MAIN else "b"
            reply = {"uz": {f"k{k}": f"tarjima {tag}{k}" for k in keys}}
        self.usage.add(model, step, 100_000, 100_000)
        return parse(json.dumps(reply)) if parse else reply


def _write_translate_file(path, w, n=3):
    lines = [json.dumps({"op": "add_sense", "note": "why not", "lexeme_id": str(w.alpha),
                         "cald_ref": f"alpha#9#{i}", "definition_en": f"an invented sense {i}",
                         "cefr": "B1", "meaning_uz": "", "meaning_uz_alt": ""}) for i in range(n)]
    lines.append(json.dumps({"op": "keep", "lexeme_id": str(w.alpha)}))
    lines.append("not json at all")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def test_translate_fills_empty_meanings_and_carries_the_judge(clean):
    w = await world()
    src = clean / "b_001.decisions.jsonl"
    _write_translate_file(src, w)
    stats = await lr.translate_file(src, FakeGemini(verdict="unsure"), async_session_factory,
                                    max_usd=50.0, log=lambda *_: None)
    assert stats["translated"] == 3 and stats["remaining"] == 0 and stats["stopped"] is None
    out = lr.translated_path(src)
    assert out.name == "b_001.decisions.jsonl.translated.jsonl"
    lines = out.read_text().splitlines()
    assert lines[-1] == "not json at all" and json.loads(lines[3]) == {
        "op": "keep", "lexeme_id": str(w.alpha)}
    first = json.loads(lines[0])
    assert first["meaning_uz"].startswith("tarjima a") and first["meaning_uz_alt"].startswith("tarjima b")
    assert first["judge"]["verdict"] == "unsure"
    assert first["needs_review"] is True and first["review_reasons"] == ["judge_unsure"]
    # and apply accepts the translated line, carrying needs_review onto the sense
    ops = [(i, json.loads(line)) for i, line in enumerate(lines[:1], start=1)]
    async with async_session_factory() as session:
        results = await lr.process(session, ops, write=True, out_dir=clean)
        await session.commit()
    assert outcomes(results) == ["applied"]
    sense = (await get_by_ref("alpha#9#0"))
    assert sense.needs_review and sense.review_reasons == ["judge_unsure"]


async def get_by_ref(ref):
    async with async_session_factory() as session:
        return (await session.exec(select(LexemeSense).where(LexemeSense.cald_ref == ref))).one()


async def test_translate_stops_cleanly_on_the_spend_cap(clean):
    w = await world()
    src = clean / "c.jsonl"
    _write_translate_file(src, w, n=5)
    stats = await lr.translate_file(src, FakeGemini(), async_session_factory, max_usd=0.0001,
                                    chunk=2, log=lambda *_: None)
    # the cap is checked before each chunk: the first runs (nothing spent yet), the second does not
    assert stats["translated"] == 2 and "spend cap" in stats["stopped"] and stats["remaining"] == 3
    done = [json.loads(x) for x in lr.translated_path(src).read_text().splitlines()[:5]]
    assert [bool(d["meaning_uz"]) for d in done] == [True, True, False, False, False]


async def test_translate_stops_on_a_payment_failure_and_leaves_the_rest_empty(clean):
    w = await world()
    src = clean / "d.jsonl"
    _write_translate_file(src, w, n=4)
    stats = await lr.translate_file(src, FakeGemini(fail=True), async_session_factory,
                                    max_usd=50.0, chunk=2, log=lambda *_: None)
    assert stats["translated"] == 0 and "402" in stats["stopped"] and stats["remaining"] == 4
    assert lr.translated_path(src).exists()
