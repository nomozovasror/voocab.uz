"""CALD review findings: a human decision locks the sense.

* Studio's approve/fix (`lexicon_review`) survives a re-run of `apply` and of
  `restore` (`locked by review`), whether the approval came before or after
  the first apply; a rewritten definition becomes ``definition_source =
  'human'``; an approved sense is never re-opened (`needs_review`), and
  ``needs_review`` itself is backed up and restored;
* `lexicon_enrich` never absorbs, deletes, relabels or re-flags a CALD /
  reviewed sense;
* the one-off cleanup commands and `word_lists_build`/`link_row` meet CALD
  senses correctly;
* `restore_senses(None)` (`--all`) and the `--confirm-db` guard.

Every dictionary entry is INVENTED (no CALD text in this repository); the
fixtures are those of `tests/test_cald_apply.py`.
"""

import json
import uuid

import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense
from app.models.vocabulary import MaterialVocabulary
from app.services import lexicon as lexicon_service
from app.services import lexicon_cald as lc
from app.services import lexicon_enrich as le
from app.services import lexicon_review as review
from app.services import word_lists_build as wb
from scripts import cald as cald_cli
from scripts import lexicon_cleanup as cleanup
from tests.test_cald_apply import (
    JUDGE,
    EnrichModel,
    FakeModel,
    _build_index,
    _drop,
    _lemma,
    _seed,
    _state,
)


async def _apply_all(out, ids: dict) -> dict:
    """The plans of the lexeme's every sense (approved ones included, as the
    CLI's `apply` builds them), applied; the counts."""
    index = lc.CaldIndex(lc.load_index_data(out))
    log = lc.DecisionLog(out / lc.DECISIONS_FILE)
    items = await lc.load_items(index, lexeme_ids=[ids["lexeme"]], log=log)
    await lc.run_map(items, index, log, FakeModel())
    plans = lc.plan_items(items, index, log, JUDGE)
    async with async_session_factory() as session:
        counts = await lc.apply_plans(session, plans)
        await session.commit()
    return counts


async def _approve(ids: dict, key: str, **fix) -> None:
    """Studio's Approve (no ``fix``) or Fix (``meaning_uz``/``definition_en``/``cefr``)."""
    async with async_session_factory() as session:
        sense = await session.get(LexemeSense, ids[key])
        if fix:
            await review.fix_and_approve(
                session, sense, admin_id=ids["user"], meaning_uz=fix.get("meaning_uz"),
                definition_en=fix.get("definition_en"), cefr=fix.get("cefr"))
        else:
            await review.approve(session, sense, admin_id=ids["user"])


# --- 1. Studio edits survive apply and restore -------------------------------------------


async def test_a_studio_fix_survives_a_reapply_and_a_restore(tmp_path):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    try:
        before = await _state(ids)
        await lc.map_new_lexemes([ids["lexeme"]], gemini=FakeModel(), out_dir=out, judge=JUDGE)
        applied = await _state(ids)
        cald_ref = applied["senses"][ids["light"]]["cald_ref"]
        await _approve(ids, "light", meaning_uz="mening tarjimam", definition_en="my own words",
                       cefr="C2")
        fixed = await _state(ids)
        light = fixed["senses"][ids["light"]]
        # Rewritten definition: the words are the reviewer's, the provenance stays.
        assert (light["definition_en"], light["definition_source"], light["cald_ref"],
                light["licence"]) == ("my own words", "human", cald_ref, "cald")
        assert (light["cefr"], light["cefr_source"], light["meaning_uz"]) == (
            "C2", "ours", "mening tarjimam")
        assert light["applied"] and not light["needs_review"]

        counts = await _apply_all(out, ids)
        assert counts["locked by review"] == 1 and counts["re-applied"] == 1  # hope only
        assert (await _state(ids))["senses"][ids["light"]] == light

        async with async_session_factory() as session:
            restored, _ = await lc.restore_senses(session, None)  # `--all`
            await session.commit()
        assert restored["locked by review"] == 1 and restored["senses restored"] == 1
        final = await _state(ids)
        assert final["senses"][ids["light"]] == light  # still the reviewer's
        assert final["senses"][ids["hope"]] == before["senses"][ids["hope"]]  # undone
        assert final["rows"] == applied["rows"]  # the locked sense's rows keep their level
        # Explicit ids: a locked sense is skipped there too.
        async with async_session_factory() as session:
            again, _ = await lc.restore_senses(session, [ids["light"]])
            await session.commit()
        assert again["locked by review"] == 1 and not again["senses restored"]
        assert (await _state(ids))["senses"][ids["light"]] == light
    finally:
        await _drop(ids)


async def test_an_approval_alone_keeps_the_sense_cald_and_locked(tmp_path):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    try:
        await lc.map_new_lexemes([ids["lexeme"]], gemini=FakeModel(), out_dir=out, judge=JUDGE)
        applied = (await _state(ids))["senses"][ids["light"]]
        await _approve(ids, "light", definition_en=applied["definition_en"] + " ",
                       cefr=applied["cefr"])  # nothing really changed
        after = (await _state(ids))["senses"][ids["light"]]
        assert (after["definition_source"], after["cefr_source"]) == ("cald", "cald")
        counts = await _apply_all(out, ids)
        assert counts["locked by review"] == 1
    finally:
        await _drop(ids)


async def test_a_sense_approved_before_the_first_apply_is_never_applied(tmp_path):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    try:
        await _approve(ids, "light")
        before = await _state(ids)
        counts = await _apply_all(out, ids)
        assert counts["locked by review"] == 1 and counts["newly applied"] == 1  # hope
        after = await _state(ids)
        assert after["senses"][ids["light"]] == before["senses"][ids["light"]]
        assert not after["senses"][ids["light"]]["applied"]
        # The hook does not even ask about it.
        model = FakeModel()
        await lc.map_new_lexemes([ids["lexeme"]], gemini=model, out_dir=out, judge=JUDGE)
        assert model.calls == []
        # The dry run says so.
        index = lc.CaldIndex(lc.load_index_data(out))
        log = lc.DecisionLog(out / lc.DECISIONS_FILE)
        items = await lc.load_items(index, lexeme_ids=[ids["lexeme"]], log=log)
        summary = lc.summarise(lc.plan_items(items, index, log, JUDGE), {})
        assert summary["other"]["locked by review (apply and restore skip it)"] == 1
    finally:
        await _drop(ids)


# --- 2. needs_review ----------------------------------------------------------------------


async def test_an_approved_sense_is_not_reopened_and_needs_review_is_backed_up(tmp_path):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)  # light: needs_review, reasons ["judge_unsure"]
    try:
        await lc.map_new_lexemes([ids["lexeme"]], gemini=FakeModel(), out_dir=out, judge=JUDGE)
        async with async_session_factory() as session:
            light = await session.get(LexemeSense, ids["light"])
            hope = await session.get(LexemeSense, ids["hope"])
            assert light.needs_review_pre_cald is True  # it WAS flagged before CALD
            assert hope.needs_review_pre_cald is False
            # A flag on a sense the reviewer then approves: the reasons stay
            # as the audit trail, `needs_review` is cleared.
            hope.review_reasons = ["ngsl_conflict"]
            hope.needs_review = True
            session.add(hope)
            await session.commit()
        await _approve(ids, "hope")
        counts = await _apply_all(out, ids)
        assert counts["locked by review"] == 1 and counts["re-applied"] == 1
        async with async_session_factory() as session:
            hope = await session.get(LexemeSense, ids["hope"])
            assert hope.needs_review is False and hope.review_reasons == ["ngsl_conflict"]
            restored, _ = await lc.restore_senses(session, None)
            await session.commit()
            await session.refresh(hope)
        assert restored["locked by review"] == 1
        assert hope.needs_review is False  # not re-opened by restore either
    finally:
        await _drop(ids)


async def test_restore_puts_the_old_needs_review_back(tmp_path):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    try:
        before = await _state(ids)
        await lc.map_new_lexemes([ids["lexeme"]], gemini=FakeModel(), out_dir=out, judge=JUDGE)
        applied = await _state(ids)
        assert not applied["senses"][ids["light"]]["needs_review"]  # the judge passed it
        async with async_session_factory() as session:
            await lc.restore_senses(session, None)
            await session.commit()
        restored = await _state(ids)
        assert restored["senses"][ids["light"]]["needs_review"] is True
        assert restored["senses"][ids["light"]]["review_reasons"] == ["judge_unsure"]
        assert restored == before
    finally:
        await _drop(ids)


# --- 3. lexicon_enrich never absorbs, deletes, relabels or re-flags a locked sense -------


def _work(senses: list[le.Sense], rows: list[le.Row], oewn: list[dict]) -> le.LexemeWork:
    return le.LexemeWork(id=uuid.uuid4(), lemma="w", pos="n", is_phrase=False,
                         frequency_band="core", oewn=oewn, senses=senses, rows=rows)


def _row(sense_id: uuid.UUID, meaning: str) -> le.Row:
    return le.Row(id=uuid.uuid4(), sense_id=sense_id, meaning_en=meaning, meaning_uz="u",
                  core_en=meaning, core_uz="cu", example="an example", cefr_level="B2")


def _label_every_use(uses: list[le.Use], label: str) -> dict:
    return {"uses": {u.id: label for u in uses}, "senses": {}}


@pytest.mark.parametrize("source", ["cald", "human"])
def test_enrichment_never_absorbs_a_locked_sense_that_lost_its_rows(source):
    locked_id, top_id = uuid.uuid4(), uuid.uuid4()
    oewn = [{"synset": "s-1", "rank": 1, "count": 5, "definition": "an oewn gloss"}]
    locked = le.Sense(id=locked_id, definition_en="test sense: kept", meaning_uz="saqlangan",
                      cefr="B2", licence="cald", oewn_synset_id="s-5", oewn_rank=5, oewn_count=1,
                      source_id="oewn", locked=True, review_reasons=[])
    top = le.Sense(id=top_id, definition_en="an oewn gloss", oewn_synset_id="s-1", oewn_rank=1,
                   oewn_count=5, source_id="oewn", licence=le.OEWN_LICENCE)
    rows = [_row(locked_id, "m1"), _row(top_id, "m2")]
    work = _work([locked, top], rows, oewn)
    uses = le.build_uses(work.rows)
    # The matcher gives BOTH senses' rows to OEWN's top sense: the locked
    # sense lost every row it had -- once it would have been absorbed and
    # deleted, backup and all.
    le.plan_senses(work, uses, _label_every_use(uses, "S1"))
    assert locked_id not in work.deleted
    assert not any(locked_id in s.absorbed for s in work.plan)
    kept = next(s for s in work.plan if s.id == locked_id)
    assert kept.locked and kept.lost_rows and kept.row_ids == []
    assert (kept.definition_en, kept.meaning_uz, kept.cefr, kept.licence) == (
        "test sense: kept", "saqlangan", "B2", "cald")
    assert (kept.oewn_synset_id, kept.oewn_rank, kept.source_id) == ("s-5", 5, "oewn")


def test_enrichment_never_deletes_an_unused_deep_locked_sense():
    deep_id = uuid.uuid4()
    oewn = [{"synset": "s-1", "rank": 1, "count": 5, "definition": "an oewn gloss"},
            {"synset": "s-9", "rank": 9, "count": 0, "definition": "a deep gloss"}]
    deep = le.Sense(id=deep_id, definition_en="test sense: deep", meaning_uz="chuqur", cefr="C1",
                    licence="cald", oewn_synset_id="s-9", oewn_rank=9, source_id="oewn",
                    locked=True)
    plain = le.Sense(id=uuid.uuid4(), definition_en="a deep gloss", oewn_synset_id="s-8",
                     oewn_rank=8, source_id="oewn", licence=le.OEWN_LICENCE)
    work = _work([deep, plain], [], oewn)
    le.plan_senses(work, [], None)
    assert plain.id in work.deleted  # the ordinary unused deep sense still goes
    assert deep_id not in work.deleted
    assert any(s.id == deep_id and s.oewn_synset_id == "s-9" for s in work.plan)


def test_enrichment_does_not_relabel_a_locked_sense_onto_another_synset():
    locked_id = uuid.uuid4()
    oewn = [{"synset": "s-1", "rank": 1, "count": 5, "definition": "an oewn gloss"}]
    locked = le.Sense(id=locked_id, definition_en="test sense: mine", meaning_uz="meniki",
                      cefr="B1", licence="cald", source_id="model", locked=True)
    work = _work([locked], [_row(locked_id, "m1")], oewn)
    uses = le.build_uses(work.rows)
    le.plan_senses(work, uses, _label_every_use(uses, "S1"))
    planned = next(s for s in work.plan if s.id == locked_id)
    assert (planned.oewn_synset_id, planned.oewn_rank, planned.oewn_count, planned.source_id) == (
        None, None, None, "model")
    assert planned.definition_en == "test sense: mine"
    # OEWN's own top sense is still added -- as a sense of its own.
    assert [s.oewn_synset_id for s in work.plan if s.id is None] == ["s-1"]


async def test_apply_work_keeps_a_reviewed_cald_senses_state(tmp_path):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    try:
        await lc.map_new_lexemes([ids["lexeme"]], gemini=FakeModel(), out_dir=out, judge=JUDGE)
        await _approve(ids, "light")
        async with async_session_factory() as session:
            light = await session.get(LexemeSense, ids["light"])
            light.review_reasons = ["ngsl_conflict"]  # the audit trail of an old flag
            session.add(light)
            await session.commit()
        before = (await _state(ids))["senses"][ids["light"]]
        assert before["needs_review"] is False
        oewn = {(lemma, "n"): [{"synset": f"t-{lemma}-1", "rank": 1, "count": 4,
                                "definition": "an oewn gloss that would replace it"}]}
        await le.enrich(async_session_factory, EnrichModel(), [ids["lexeme"]], oewn)
        after = (await _state(ids))["senses"][ids["light"]]
        assert after == before  # text, level, reasons, needs_review, labels: all untouched
        async with async_session_factory() as session:
            row = await session.get(LexemeSense, ids["light"])
            assert (row.oewn_synset_id, row.oewn_rank, row.source_id) == (
                f"t-{lemma}-1", 1, "oewn")
    finally:
        await _drop(ids)


async def test_a_locked_sense_that_lost_its_rows_is_flagged_unless_approved(tmp_path):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    try:
        await lc.map_new_lexemes([ids["lexeme"]], gemini=FakeModel(), out_dir=out, judge=JUDGE)
        # Both material rows sit on the CALD "light" sense; the matcher will
        # label them as OEWN's top sense, a different synset from the one
        # the locked sense has.
        async with async_session_factory() as session:
            light = await session.get(LexemeSense, ids["light"])
            light.oewn_synset_id = f"t-{lemma}-deep"
            light.oewn_rank = 9
            session.add(light)
            await session.commit()
        oewn = {(lemma, "n"): [{"synset": f"t-{lemma}-1", "rank": 1, "count": 4,
                                "definition": "an oewn gloss"}]}
        await le.enrich(async_session_factory, EnrichModel(), [ids["lexeme"]], oewn)
        async with async_session_factory() as session:
            senses = (await session.exec(select(LexemeSense).where(
                LexemeSense.lexeme_id == ids["lexeme"]))).all()
            light = next(s for s in senses if s.id == ids["light"])  # not deleted
            assert light.definition_source == "cald" and light.oewn_synset_id.endswith("-deep")
            assert "lemma_merge" in light.review_reasons and light.needs_review
    finally:
        await _drop(ids)


# --- 4. the other writers ---------------------------------------------------------------


async def _locked_lexeme(source: str = "cald") -> tuple[uuid.UUID, uuid.UUID, str]:
    lemma = _lemma()
    async with async_session_factory() as session:
        lexeme = Lexeme(lemma=lemma, pos="n", frequency_band="off-list", cefr="B2")
        session.add(lexeme)
        await session.flush()
        sense = LexemeSense(lexeme_id=lexeme.id, sense_rank=1, definition_en="test sense: x",
                            meaning_uz="eski", meaning_uz_alt="eski2", cefr="B2",
                            definition_source=source, licence="cald", provisional=False,
                            review_reasons=["judge_different"], needs_review=True)
        session.add(sense)
        await session.commit()
        return lexeme.id, sense.id, lemma


async def _forget(*lemmas: str) -> None:
    async with async_session_factory() as session:
        for lexeme in (await session.exec(select(Lexeme).where(Lexeme.lemma.in_(lemmas)))).all():
            for sense in (await session.exec(select(LexemeSense).where(
                    LexemeSense.lexeme_id == lexeme.id))).all():
                await session.delete(sense)
            await session.flush()
            await session.delete(lexeme)
        await session.commit()


async def test_cleanup_refuses_to_delete_or_mark_a_lexeme_with_a_cald_sense(capsys):
    lexeme_id, sense_id, lemma = await _locked_lexeme("human")
    try:
        async with async_session_factory() as session:
            assert await cleanup.delete_lexeme(session, lexeme_id) is False
            lexeme = await session.get(Lexeme, lexeme_id)
            assert await cleanup.mark_proper(session, lexeme) is False
            await session.commit()
        async with async_session_factory() as session:
            lexeme = await session.get(Lexeme, lexeme_id)
            sense = await session.get(LexemeSense, sense_id)
            assert lexeme is not None and not lexeme.is_proper_noun and lexeme.cefr == "B2"
            assert sense is not None and sense.cefr == "B2"
        out = capsys.readouterr().out
        assert "not deleted, has a CALD/reviewed sense" in out
        assert "not marked proper, has a CALD/reviewed sense" in out
    finally:
        await _forget(lemma)


async def test_cleanup_retranslation_commands_skip_a_cald_sense(tmp_path, capsys, monkeypatch):
    lexeme_id, sense_id, lemma = await _locked_lexeme()
    trial = {str(sense_id): {
        "lemma": lemma, "pos": "n", "definition": "test sense: x", "old_uz": "boshqa",
        "old_alt": "boshqa2", "old_verdict": "different", "new_uz": "yangi",
        "new_alt": "yangi2", "new_verdict": "same"}}
    path = tmp_path / "trial.json"
    path.write_text(json.dumps(trial))
    try:
        await cleanup.retranslate_decide(path)  # would KEEP the new pair
        await cleanup.restore_retranslation(path, None)  # would put the old pair back
        async with async_session_factory() as session:
            sense = await session.get(LexemeSense, sense_id)
            assert (sense.meaning_uz, sense.meaning_uz_alt) == ("eski", "eski2")
            assert sense.review_reasons == ["judge_different"]
        assert capsys.readouterr().out.count("skipped, CALD/reviewed sense") == 2

        # The trial itself never selects it (no model is reached here).
        class _Gemini:
            def __init__(self, usage) -> None:
                self.usage = usage

            async def aclose(self) -> None:
                pass

        async def _no_translate(gemini, works) -> None:
            return None

        async def _no_judge(gemini, rows, log):
            return [(None, "") for _ in rows]

        monkeypatch.setattr(cleanup.le, "Gemini", _Gemini)
        monkeypatch.setattr(cleanup.le, "step_translate", _no_translate)
        monkeypatch.setattr(cleanup, "_judge_rows", _no_judge)
        out_path = tmp_path / "out.json"
        await cleanup.retranslate_trial(out_path, None)
        assert str(sense_id) not in json.loads(out_path.read_text())
        async with async_session_factory() as session:
            assert (await session.get(LexemeSense, sense_id)).meaning_uz_prev == ""
    finally:
        await _forget(lemma)


async def test_list_only_leaves_a_lexeme_with_a_cald_sense_alone(capsys, monkeypatch):
    lexeme_id, sense_id, lemma = await _locked_lexeme()

    class _Gemini:
        def __init__(self, usage) -> None:
            self.usage = usage

        async def ask(self, *args, **kwargs):
            return None

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(cleanup.le, "Gemini", _Gemini)
    monkeypatch.setattr(cleanup.le, "load_oewn", lambda: {})
    try:
        await cleanup.list_only(apply=False, out=None)
        out = capsys.readouterr().out
        assert "skipped, has a CALD/reviewed sense" in out
        assert lemma not in out.split("skipped, has a CALD/reviewed sense")[0]
    finally:
        await _forget(lemma)


def test_a_rebuild_finds_a_cald_sense_by_what_its_definition_was():
    view = wb.LexiconView()
    lexeme = wb.LexemeInfo(id=uuid.uuid4(), lemma="word", pos="n", is_phrase=False,
                           is_proper_noun=False, is_function_word=False, frequency_band=None)
    view.add_lexeme(lexeme)
    sense = wb.SenseInfo(id=uuid.uuid4(), lexeme_id=lexeme.id, sense_rank=1,
                         definition_en="test sense: dictionary words", oewn_synset_id=None,
                         cefr="B1", source_id="model",
                         definition_pre_cald="our own wording of it")
    view.add_sense(sense)
    ours = wb.Decision(type="model", pos="n", definition="Our own wording of it.")
    assert wb._held_sense(view, "word", ours) is sense  # no duplicate minted
    cald = wb.Decision(type="model", pos="n", definition="test sense: dictionary words")
    assert wb._held_sense(view, "word", cald) is sense
    other = wb.Decision(type="model", pos="n", definition="something else")
    assert wb._held_sense(view, "word", other) is None


# --- 7. a row linked after the apply takes the sense's CALD level -------------------------


def _material_row(lemma: str, meaning: str, level: str) -> MaterialVocabulary:
    return MaterialVocabulary(
        material_id=uuid.uuid4(), part_id=uuid.uuid4(), lemma=lemma, surface=lemma, pos="n",
        meaning_en=meaning, meaning_uz="u", example="An example.", cefr_level=level)


async def test_a_row_linked_after_the_apply_takes_the_cald_level(tmp_path):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    try:
        await lc.map_new_lexemes([ids["lexeme"]], gemini=FakeModel(), out_dir=out, judge=JUDGE)
        async with async_session_factory() as session:
            # Our wording of the sense (what a material says), not CALD's.
            row = _material_row(lemma, "a faint flickering light", "C1")
            await lexicon_service.link_row(session, row)
            assert row.sense_id == ids["light"]  # found by its pre-CALD definition
            assert (row.cefr_level, row.cefr_level_pre_cald) == ("B2", "C1")
            # A sense that kept OUR level: the row keeps its own.
            plain = _material_row(lemma, "a slight sign of hope", "A2")
            await lexicon_service.link_row(session, plain)
            assert plain.sense_id == ids["hope"]
            assert (plain.cefr_level, plain.cefr_level_pre_cald) == ("A2", None)
            # Already at the sense's level: nothing to back up.
            same = _material_row(lemma, "a faint flickering light", "B2")
            await lexicon_service.link_row(session, same)
            assert (same.cefr_level, same.cefr_level_pre_cald) == ("B2", None)
            await session.rollback()
    finally:
        await _drop(ids)


# --- restore --all and the --confirm-db guard --------------------------------------------


async def test_confirm_db_guards_apply_and_restore(tmp_path, capsys):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    try:
        await lc.map_new_lexemes([ids["lexeme"]], gemini=FakeModel(), out_dir=out, judge=JUDGE)
        applied = await _state(ids)
        database = cald_cli._database_name()
        # The wrong name, or none: nothing is written.
        with pytest.raises(SystemExit):
            await cald_cli.cmd_restore(None, "some_other_db")
        with pytest.raises(SystemExit):
            await cald_cli.cmd_restore(None, None)
        with pytest.raises(SystemExit):
            await cald_cli.cmd_apply("some_other_db", JUDGE, out)
        assert await _state(ids) == applied
        # Apply with no name is a dry run (it prints, writes nothing).
        await cald_cli.cmd_apply(None, JUDGE, out)
        assert "nothing written" in capsys.readouterr().out
        assert await _state(ids) == applied
        # The right name: `restore --all` undoes every applied sense.
        await cald_cli.cmd_restore(None, database)
        restored = await _state(ids)
        assert not any(s["applied"] for s in restored["senses"].values())
        assert restored["senses"][ids["light"]]["definition_en"] == "a faint flickering light"
    finally:
        await _drop(ids)
