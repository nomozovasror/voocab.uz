"""The AI-assisted lexicon review (`app.services.lexicon_ai_review`,
`scripts/lexicon_ai_review.py`): export shape and stratification, decision
validation, apply (approve / fix / human, dry run, one transaction,
idempotence), the CALD lock, exact undo, material fixes, and the system
account that cannot log in.

Every sense, sentence and Uzbek word is INVENTED -- no dictionary text in this
repository. Real DB; each test makes its own uniquely named lexemes and
removes them, so it can run beside whatever else the database holds.
"""

import json
import uuid
from collections import Counter

import httpx
import pytest
from sqlalchemy import text
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token, create_refresh_token
from app.main import app
from app.models.auth_identity import AuthIdentity
from app.models.lexicon import Lexeme, LexemeSense, LexiconAiReview, TranslationReport
from app.models.material import Material
from app.models.part import Part
from app.models.user import REVIEW_BOT_EMAIL, User, is_system_account
from app.models.vocabulary import MaterialVocabulary
from app.services import lexicon_ai_review as air
from app.services import lexicon_cald as lc
from app.services import lexicon_review
from app.services.lexicon_cald import readonly_connection
from scripts import lexicon_ai_review as cli
from tests.test_cald_apply import JUDGE, FakeModel, _build_index, _drop, _lemma, _seed, _state
from tests.test_cald_locks import _apply_all


# --- fixtures --------------------------------------------------------------------------------


def _word() -> str:
    return "airev" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:8])


async def _world() -> dict:
    """A noun lexeme with three flagged senses, a verb lexeme of the same lemma,
    and four material rows (one written as an inflected form)."""
    lemma = _word()
    async with async_session_factory() as session:
        user = User(email=f"airev-{lemma}@test.local", display_name="airev owner")
        session.add(user)
        await session.flush()
        material = Material(author_id=user.id, type="reading", title=f"airev {lemma}",
                            visibility="private")
        session.add(material)
        await session.flush()
        part = Part(material_id=material.id, order_index=0, title="P",
                    passage={"paragraphs": []}, first_number=1)
        session.add(part)
        noun = Lexeme(lemma=lemma, pos="n", frequency_band="core", frequency_source="ngsl",
                      cefr="C1")
        verb = Lexeme(lemma=lemma, pos="v", frequency_band="core", frequency_source="ngsl",
                      cefr="B1")
        session.add_all([noun, verb])
        await session.flush()
        s1 = LexemeSense(lexeme_id=noun.id, sense_rank=1, definition_en="a small invented thing",
                         meaning_uz="kichik narsa", meaning_uz_alt="mayda narsa", cefr="C1",
                         review_reasons=["ngsl_conflict", "judge_unsure"], needs_review=True,
                         provisional=False, definition_source="oewn")
        s2 = LexemeSense(lexeme_id=noun.id, sense_rank=2, definition_en="an invented group",
                         meaning_uz="guruh", cefr="C1", review_reasons=["lemma_merge"],
                         needs_review=True, provisional=False)
        s3 = LexemeSense(lexeme_id=noun.id, sense_rank=3, definition_en="an unflagged meaning",
                         meaning_uz="boshqa", cefr="C1", provisional=False)
        v1 = LexemeSense(lexeme_id=verb.id, sense_rank=1, definition_en="to invent a thing",
                         meaning_uz="o'ylab topmoq", cefr="B1", review_reasons=["pos_mismatch"],
                         needs_review=True, provisional=False)
        session.add_all([s1, s2, s3, v1])
        await session.flush()

        def row(suffix: str, sense: LexemeSense, lexeme: Lexeme, lemma_written: str, pos: str):
            return MaterialVocabulary(
                material_id=material.id, part_id=part.id, lemma=lemma_written + suffix,
                surface=lemma_written, pos=pos, meaning_en="m", meaning_uz="u",
                meaning_core_en="m", meaning_core_uz="u", example=f"An invented {lemma} here.",
                cefr_level="B2", lexeme_id=lexeme.id, sense_id=sense.id)

        r1 = row("", s1, noun, lemma, "n")
        r2 = row("s", s1, noun, lemma, "n")  # written "<lemma>s", lemma "<lemma>s": a merged form
        r3 = row("3", s2, noun, lemma, "n")
        r4 = row("4", s1, noun, lemma, "v")  # a verb use filed under the noun
        session.add_all([r1, r2, r3, r4])
        await session.commit()
        return {"lemma": lemma, "user": user.id, "material": material.id, "part": part.id,
                "noun": noun.id, "verb": verb.id, "s1": s1.id, "s2": s2.id, "s3": s3.id,
                "v1": v1.id, "rows": [r1.id, r2.id, r3.id, r4.id]}


async def _gone(ids: dict) -> None:
    async with async_session_factory() as session:
        for row in (await session.exec(select(MaterialVocabulary).where(
                MaterialVocabulary.material_id == ids["material"]))).all():
            await session.delete(row)
        await session.flush()
        for lexeme_id in (ids["noun"], ids["verb"]):
            for report in (await session.exec(select(TranslationReport).where(
                    TranslationReport.lexeme_sense_id.in_(
                        select(LexemeSense.id).where(LexemeSense.lexeme_id == lexeme_id))))).all():
                await session.delete(report)
            await session.flush()
            for sense in (await session.exec(select(LexemeSense).where(
                    LexemeSense.lexeme_id == lexeme_id))).all():
                await session.delete(sense)
            await session.flush()
            lexeme = await session.get(Lexeme, lexeme_id)
            if lexeme is not None:
                await session.delete(lexeme)
                await session.flush()
        for model, key in ((Part, "part"), (Material, "material"), (User, "user")):
            obj = await session.get(model, ids[key])
            if obj is not None:
                await session.delete(obj)
                await session.flush()
        await session.commit()


async def _full(ids: dict) -> dict:
    """Every column of the world's senses, lexemes and rows (but `updated_at`)."""
    async with async_session_factory() as session:
        out = {}
        for key in ("noun", "verb"):
            out[key] = (await session.get(Lexeme, ids[key])).model_dump(exclude={"updated_at"})
        for key in ("s1", "s2", "s3", "v1"):
            out[key] = (await session.get(LexemeSense, ids[key])).model_dump(
                exclude={"updated_at", "sense_rank"})  # the rank follows the level (rerank_lexemes)
        for i, row_id in enumerate(ids["rows"]):
            out[f"row{i}"] = (await session.get(MaterialVocabulary, row_id)).model_dump()
        return out


def _loose(full: dict) -> dict:
    """`_full` without the lexemes' level: after an undo it is the EASIEST
    sense's (`lexicon.rerank_lexemes` re-orders when a level changes), which
    need not be what a hand-built world had."""
    return {k: ({**v, "cefr": None} if k in ("noun", "verb") else v) for k, v in full.items()}


def _d(sense_id, action="approve", confidence="high", note="looks right", **extra) -> dict:
    return {"sense_id": str(sense_id), "action": action, "confidence": confidence,
            "note": note, **extra}


async def _run(decisions: list, *, write: bool = True, material: bool = False) -> list[air.Result]:
    raw = list(enumerate(decisions, start=1))
    async with async_session_factory() as session:
        results = await air.process(session, raw, write=write, allow_material_fixes=material)
        if write:
            await session.commit()
        else:
            await session.rollback()
    return results


async def _undo(ids: list | None, *, write: bool = True) -> list[air.Result]:
    async with async_session_factory() as session:
        results = await air.undo(session, sense_ids=ids, write=write)
        if write:
            await session.commit()
        else:
            await session.rollback()
    return results


async def _bot() -> User | None:
    async with async_session_factory() as session:
        return await air.get_account(session)


async def _forget_account() -> None:
    """Remove the system account (its approvals fall back to NULL, as the FK
    says) so a test can watch it being created -- or not."""
    async with async_session_factory() as session:
        await session.exec(text("delete from users where email = :e").bindparams(e=REVIEW_BOT_EMAIL))
        await session.commit()


# --- decision validation (no database) ---------------------------------------------------------


def test_uzbek_must_be_short_latin_script_equivalents():
    assert air.clean_uzbek("  Yopishtirmoq,  yopishmoq ", allow_empty=False) == (
        "Yopishtirmoq, yopishmoq", None)
    # Typographic apostrophes become the plain one the data uses.
    assert air.clean_uzbek("o‘zbek, g’isht, qoʻng‘iroq", allow_empty=False)[0] == (
        "o'zbek, g'isht, qo'ng'iroq")
    assert air.clean_uzbek("kuchli (jismonan), baquvvat", allow_empty=False)[1] is None
    assert air.clean_uzbek("", allow_empty=True) == ("", None)
    for bad, why in (
        ("", "empty"), ("ўзбек", "Cyrillic"), ("a, b, c, d, e", "5 equivalents"),
        ("a,, b", "empty item"), ("x" * 41, "too long"),
        ("what is this?", "punctuation"), (None, "not a string"), ("hello 你好", "other script"),
    ):
        assert air.clean_uzbek(bad, allow_empty=False)[1] is not None, why


def test_a_decision_is_checked_before_it_touches_anything():
    sid = str(uuid.uuid4())
    ok = {"sense_id": sid, "action": "fix", "cefr": "B1", "meaning_uz": "narsa",
          "confidence": "high", "note": "n"}
    decision, error = air.parse_decision(ok)
    assert error is None and (decision.cefr, decision.meaning_uz) == ("B1", "narsa")

    def bad(**change) -> str:
        raw = {**ok, **change}
        for key in [k for k, v in change.items() if v is ...]:
            del raw[key]
        decision, error = air.parse_decision(raw)
        assert decision is None and error
        return error

    assert "uuid" in bad(sense_id="nope")
    assert "action" in bad(action="delete")
    assert "confidence" in bad(confidence="certain")
    assert "cefr" in bad(cefr="B3")
    assert "unknown key" in bad(definition_en="rewrite")  # a definition can never ride along
    assert "unknown key" in bad(meaning_uz_alts="x")  # a typo is not a silent no-op
    assert "meaning_uz" in bad(meaning_uz="ўзбек")
    assert "low confidence" in bad(confidence="low")
    assert "no change" in bad(cefr=..., meaning_uz=...)  # a fix that fixes nothing
    # approve and human carry no changes; human needs a note.
    assert "carries no changes" in bad(action="approve")
    assert "note" in bad(action="human", cefr=..., meaning_uz=..., note="")
    assert air.parse_decision(_d(sid, "human", "low", "rows mix two meanings"))[1] is None
    assert air.parse_decision(_d(sid, "approve", "medium", ""))[1] is None
    assert air.parse_decision("nonsense")[0] is None
    fix = {"kind": "relink_sense", "row_id": sid, "to_sense_id": sid}
    assert "keys" in bad(material_fixes=[{**fix, "extra": 1}])
    assert "kind" in bad(material_fixes=[{**fix, "kind": "delete_row"}])
    assert "list" in bad(material_fixes=[])


def test_a_pilot_sample_gives_every_reason_a_fair_share():
    assert air.allocate({"a": 1000, "b": 3, "c": 20}, 30) == {"a": 14, "b": 3, "c": 13}
    assert air.allocate({"a": 2, "b": 1}, 10) == {"a": 2, "b": 1}  # fewer than asked for
    rows = ([{"id": uuid.uuid4(), "review_reasons": ["cald_cefr_far"]} for _ in range(200)]
            + [{"id": uuid.uuid4(), "review_reasons": ["cald_cefr_far", "pos_mismatch"]}
               for _ in range(5)]
            + [{"id": uuid.uuid4(), "review_reasons": ["judge_different"]} for _ in range(6)])
    chosen = air.stratified_sample(rows, 20, seed=7)
    by = Counter(air.primary_reason(r["review_reasons"]) for r in chosen)
    assert len(chosen) == 20 == len({r["id"] for r in chosen})
    # pos_mismatch outranks cald_cefr_far for a sense carrying both.
    assert by == {"judge_different": 6, "pos_mismatch": 5, "cald_cefr_far": 9}
    assert [r["id"] for r in air.stratified_sample(rows, 20, seed=7)] == [r["id"] for r in chosen]
    assert {r["id"] for r in air.stratified_sample(rows, 20, seed=8)} != {r["id"] for r in chosen}


# --- export -----------------------------------------------------------------------------------


async def test_an_export_record_has_what_a_reviewer_needs(tmp_path):
    ids = await _world()
    try:
        async with readonly_connection() as conn:
            manifest = await air.export(conn, tmp_path, database="testdb", batch_size=10_000,
                                        tag="t")
        assert manifest["senses"] == sum(b["senses"] for b in manifest["batches"])
        records = {}
        for batch in manifest["batches"]:
            for line in (tmp_path / batch["file"]).read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                records[record["sense_id"]] = record
        assert str(ids["s3"]) not in records  # unflagged: not exported
        s1, s2, v1 = (records[str(ids[k])] for k in ("s1", "s2", "v1"))

        assert (s1["lemma"], s1["pos"], s1["cefr"], s1["cefr_source"]) == (ids["lemma"], "n", "C1", "ours")
        assert s1["definition_en"] == "a small invented thing" and s1["definition_source"] == "oewn"
        assert (s1["meaning_uz"], s1["meaning_uz_alt"]) == ("kichik narsa", "mayda narsa")
        assert s1["frequency"]["band"] == "core" and "ngsl_rank" in s1["frequency"]
        assert set(s1["review_reasons"]) == {"ngsl_conflict", "judge_unsure"}
        assert s1["reason_details"]["ngsl_conflict"]["ours"] == "C1"
        assert "judge_unsure" in s1["reason_details"]
        # the lexeme's OTHER senses: definition, cefr, pos -- not this one
        assert {o["sense_id"] for o in s1["other_senses"]} == {str(ids["s2"]), str(ids["s3"])}
        assert all(set(o) == {"sense_id", "rank", "pos", "cefr", "definition"}
                   for o in s1["other_senses"])
        # usages: sentence, the row's pos and level, the row's own meanings; capped at 3
        assert s1["usage_count"] == 3 and len(s1["usages"]) == 3
        usage = s1["usages"][0]
        assert usage["sentence"].startswith("An invented") and usage["row_cefr"] == "B2"
        assert {"row_id", "row_pos", "meaning_en", "meaning_uz"} <= set(usage)
        assert {u["row_pos"] for u in s1["usages"]} == {"n", "v"}

        # lemma_merge: which forms were merged, and whether they have a lexeme of their own
        merge = records[str(ids["s2"])]["reason_details"]["lemma_merge"]
        assert merge["headword"] == ids["lemma"]
        forms = {f["form"]: f for f in merge["merged_forms_seen_in_material_rows"]}
        assert set(forms) == {ids["lemma"] + suffix for suffix in ("s", "3", "4")}
        assert forms[ids["lemma"] + "3"]["rows_in_this_sense"] == 1  # r3 is in s2
        assert forms[ids["lemma"] + "s"]["rows_in_this_sense"] == 0
        assert forms[ids["lemma"] + "s"]["has_own_lexeme"] is False
        assert s2["same_lemma_other_lexemes"][0]["pos"] == "v"

        # pos_mismatch: both pos values, and the other lexeme's senses to relink to
        detail = v1["reason_details"]["pos_mismatch"]
        assert detail["lexeme_pos"] == "v" and detail["pos_of_all_material_rows_of_lexeme"] == {}
        assert v1["same_lemma_other_lexemes"][0]["pos"] == "n"
        assert {s["sense_id"] for s in v1["same_lemma_other_lexemes"][0]["senses"]} == {
            str(ids["s1"]), str(ids["s2"]), str(ids["s3"])}
        # the instruction sheet and manifest sit beside the batches
        assert (tmp_path / "REVIEW_RUBRIC.md").read_text().startswith("# Lexicon review rubric")
        assert json.loads((tmp_path / "t_manifest.json").read_text())["database"] == "testdb"
    finally:
        await _gone(ids)


async def test_export_batches_filters_samples_and_excludes(tmp_path):
    ids = await _world()
    more = await _world()
    try:
        async with readonly_connection() as conn:
            only = await air.export(conn, tmp_path / "a", database="d", reason="lemma_merge",
                                    batch_size=1)
            assert set(only["by_primary_reason"]) == {"lemma_merge"}
            assert all(b["senses"] == 1 for b in only["batches"])
            assert [b["file"] for b in only["batches"]][:2] == ["batch_001.jsonl", "batch_002.jsonl"]
            assert only["senses"] >= 2

            sample = await air.export(conn, tmp_path / "b", database="d", sample=4, seed=3,
                                      tag="pilot")
            assert sample["senses"] == min(4, sample["flagged_available"])
            again = await air.export(conn, tmp_path / "c", database="d", sample=4, seed=3,
                                     tag="pilot")
            assert (tmp_path / "b/pilot_001.jsonl").read_text() == (
                tmp_path / "c/pilot_001.jsonl").read_text()  # reproducible

            # Exclude by file: a decisions file, a batch, a plain list all work.
            exclude_file = tmp_path / "ids.txt"
            exclude_file.write_text(f"{ids['s1']}\n{ids['s2']}\nnot-an-id\n")
            # A batch line names OTHER senses of the lexeme: only its own sense_id counts.
            batch_line = tmp_path / "line.jsonl"
            batch_line.write_text(json.dumps({"sense_id": str(ids["v1"]), "other_senses": [
                {"sense_id": str(ids["s3"])}], "lexeme_id": str(ids["noun"])}) + "\n")
            assert air.parse_exclude_file(batch_line) == {ids["v1"]}
            rest = await air.export(
                conn, tmp_path / "d", database="d", exclude=air.parse_exclude_file(exclude_file))
            sense_ids = {json.loads(line)["sense_id"] for b in rest["batches"]
                         for line in (tmp_path / "d" / b["file"]).read_text().splitlines()}
            assert str(ids["s1"]) not in sense_ids and str(ids["s2"]) not in sense_ids
            assert str(ids["v1"]) in sense_ids
        with pytest.raises(ValueError):
            async with readonly_connection() as conn:
                await air.export(conn, tmp_path / "e", database="d", reason="made_up")
    finally:
        await _gone(ids)
        await _gone(more)


async def test_an_export_works_on_a_database_before_the_migration(tmp_path, monkeypatch):
    """The pilot was exported from a database the migration had not reached."""
    async def not_yet(conn) -> bool:
        return False

    monkeypatch.setattr(air, "_has_review_note", not_yet)
    ids = await _world()
    try:
        async with readonly_connection() as conn:
            flagged = await air._fetch_flagged(conn, "lemma_merge")
        assert any(r["id"] == ids["s2"] and r["review_note"] == "" for r in flagged)
    finally:
        await _gone(ids)


# --- apply ------------------------------------------------------------------------------------


async def test_a_dry_run_writes_nothing_and_creates_no_account():
    ids = await _world()
    await _forget_account()
    try:
        before = await _full(ids)
        results = await _run([_d(ids["s1"]), _d(ids["s2"], "fix", cefr="B1"),
                              _d(ids["v1"], "human", "low", "rows disagree")], write=False)
        assert [r.outcome for r in results] == ["would apply"] * 3
        assert await _full(ids) == before
        assert await _bot() is None
        async with async_session_factory() as session:
            assert not (await session.exec(select(LexiconAiReview).where(
                LexiconAiReview.sense_id.in_([ids["s1"], ids["s2"], ids["v1"]])))).all()
    finally:
        await _gone(ids)


async def test_approve_fix_and_human_do_what_studio_does_and_leave_what_they_must():
    ids = await _world()
    try:
        before = await _full(ids)
        results = await _run([
            _d(ids["s1"], "fix", "medium", "concrete word, lower level", cefr="A2",
               meaning_uz="mayda narsa, buyum", meaning_uz_alt=""),
            _d(ids["s2"], "approve"),
            _d(ids["v1"], "human", "low", "rows use it as a noun, I cannot tell"),
        ])
        assert [(r.outcome, r.action) for r in results] == [
            ("applied", "fix"), ("applied", "approve"), ("applied", "human")]
        bot = await _bot()
        assert bot is not None
        after = await _full(ids)

        s1 = after["s1"]  # the rank-1 sense: fixed and approved; the lexeme's level follows
        assert (s1["cefr"], s1["meaning_uz"], s1["meaning_uz_alt"]) == ("A2", "mayda narsa, buyum", "")
        assert s1["needs_review"] is False and s1["approved_by"] == bot.id
        assert s1["approved_at"] is not None
        assert s1["review_reasons"] == before["s1"]["review_reasons"]  # history kept
        assert s1["definition_en"] == before["s1"]["definition_en"]  # never a definition
        assert s1["definition_source"] == before["s1"]["definition_source"]
        assert after["noun"]["cefr"] == "A2"
        assert after["s2"]["needs_review"] is False and after["s2"]["approved_by"] == bot.id
        assert after["s2"]["cefr"] == before["s2"]["cefr"] and after["s2"]["meaning_uz"] == "guruh"
        assert after["s3"] == before["s3"]  # untouched

        v1 = after["v1"]  # left for a person, with the note where Studio shows it
        assert v1["needs_review"] is True and v1["approved_at"] is None and v1["approved_by"] is None
        assert v1["review_note"] == "Claude review (low): rows use it as a noun, I cannot tell"
        assert {k: v for k, v in v1.items() if k != "review_note"} == {
            k: v for k, v in before["v1"].items() if k != "review_note"}
        assert all(after[f"row{i}"] == before[f"row{i}"] for i in range(4))

        async with async_session_factory() as session:
            logs = (await session.exec(select(LexiconAiReview).where(
                LexiconAiReview.sense_id.in_([ids["s1"], ids["s2"], ids["v1"]])))).all()
            assert Counter(log.action for log in logs) == {"fix": 1, "approve": 1, "human": 1}
            fix_log = next(log for log in logs if log.action == "fix")
            assert fix_log.before["cefr"] == "C1" and fix_log.after["cefr"] == "A2"
            assert fix_log.before["lexeme_cefr"] == "C1" and fix_log.undone_at is None
            assert len({log.run_id for log in logs}) == 1
    finally:
        await _gone(ids)


async def test_a_second_run_changes_nothing():
    ids = await _world()
    try:
        decisions = [_d(ids["s1"], "fix", cefr="B1"), _d(ids["s2"]),
                     _d(ids["v1"], "human", "medium", "check the pos")]
        await _run(decisions)
        once = await _full(ids)
        results = await _run(decisions)
        assert [r.outcome for r in results] == ["already decided", "already decided", "unchanged"]
        assert await _full(ids) == once
        async with async_session_factory() as session:
            n = len((await session.exec(select(LexiconAiReview).where(
                LexiconAiReview.sense_id.in_([ids["s1"], ids["s2"], ids["v1"]])))).all())
        assert n == 3
        # A different note on a still-flagged sense replaces the first.
        results = await _run([_d(ids["v1"], "human", "medium", "a different worry")])
        assert results[0].outcome == "applied"
        async with async_session_factory() as session:
            assert (await session.get(LexemeSense, ids["v1"])).review_note.endswith("a different worry")
    finally:
        await _gone(ids)


async def test_what_cannot_be_trusted_is_rejected_and_the_rest_still_applies():
    ids = await _world()
    try:
        # A person approved s2; a learner reported v1.
        async with async_session_factory() as session:
            s2 = await session.get(LexemeSense, ids["s2"])
            await lexicon_review.approve(session, s2, admin_id=ids["user"])
            session.add(TranslationReport(user_id=ids["user"], lexeme_sense_id=ids["v1"],
                                          note="wrong"))
            await session.commit()
        results = await _run([
            _d(ids["s3"]),                                           # not flagged
            _d(ids["s2"]),                                           # already approved
            _d(ids["v1"], "approve"),                                # open learner report
            _d(uuid.uuid4()),                                        # unknown
            _d(ids["s1"], "fix", cefr="C3"),                         # bad value
            _d(ids["s1"], "fix", meaning_uz="ўзбек"),                # Cyrillic
            _d(ids["s1"], "fix", cefr="B1", material_fixes=[
                {"kind": "relink_sense", "row_id": str(ids["rows"][0]),
                 "to_sense_id": str(ids["s2"])}]),                   # material fixes are off
            _d(ids["s1"], "fix", cefr="B2"),                         # fine
            _d(ids["s1"], "approve"),                                # duplicate of the above
        ])
        outcomes = [(r.outcome) for r in results]
        assert outcomes == ["already decided", "already decided", "rejected", "rejected",
                            "rejected", "rejected", "rejected", "applied", "rejected"]
        assert "open learner report" in results[2].detail
        assert "off" in results[6].detail and "duplicate" in results[8].detail
        # Rejected against the sense's current values (a second pass: the first
        # decision in a file is the one that counts).
        again = await _run([_d(ids["v1"], "fix", cefr="B1")])  # v1 is already B1 and reported
        assert again[0].outcome == "rejected"
        unchanged = await _run([_d(ids["s3"], "fix", cefr="B1")])
        assert unchanged[0].outcome == "already decided"
        async with async_session_factory() as session:
            assert (await session.get(LexemeSense, ids["s1"])).cefr == "B2"
            assert (await session.get(LexemeSense, ids["v1"])).needs_review is True
        # A fix that changes nothing, and an alternative equal to the main one.
        other = await _world()
        try:
            noop = await _run([_d(other["s1"], "fix", cefr="C1")])
            assert noop[0].outcome == "rejected" and "changes nothing" in noop[0].detail
            same = await _run([_d(other["s1"], "fix", meaning_uz="narsa", meaning_uz_alt="Narsa")])
            assert same[0].outcome == "rejected" and "equals" in same[0].detail
        finally:
            await _gone(other)
        # The reported one can still be left for a person, and the report stays open.
        results = await _run([_d(ids["v1"], "human", "high", "learner says the Uzbek is wrong")])
        assert results[0].outcome == "applied"
        async with async_session_factory() as session:
            report = (await session.exec(select(TranslationReport).where(
                TranslationReport.lexeme_sense_id == ids["v1"]))).one()
            assert report.status == "open"
        # Unparseable lines are reported, not dropped.
        raw = [(1, ValueError("not JSON: nope")), (2, ["not", "an", "object"])]
        async with async_session_factory() as session:
            results = await air.process(session, raw, write=False)
        assert [r.outcome for r in results] == ["rejected", "rejected"]
    finally:
        await _gone(ids)


async def test_a_run_is_one_transaction(monkeypatch):
    ids = await _world()
    await _forget_account()
    try:
        before = await _full(ids)
        real = lexicon_review.fix_and_approve

        async def breaks(session, sense, **kw):
            await real(session, sense, **kw)
            raise RuntimeError("boom")

        monkeypatch.setattr(lexicon_review, "fix_and_approve", breaks)
        with pytest.raises(RuntimeError):
            async with async_session_factory() as session:
                try:
                    await air.process(
                        session,
                        [(1, _d(ids["s2"])), (2, _d(ids["s1"], "fix", cefr="A1"))],
                        write=True)
                    await session.commit()
                except BaseException:
                    await session.rollback()
                    raise
        assert await _full(ids) == before
        assert await _bot() is None  # the account was part of the same transaction
    finally:
        await _gone(ids)


async def test_the_cli_refuses_a_database_name_that_is_not_the_one_it_points_at(tmp_path):
    ids = await _world()
    try:
        decisions = tmp_path / "d.jsonl"
        decisions.write_text(json.dumps(_d(ids["s2"])) + "\n")
        args = cli.argparse.Namespace(decisions=decisions, confirm_db="not_this_database",
                                      allow_material_fixes=False, out=tmp_path)
        with pytest.raises(SystemExit):
            await cli.cmd_apply(args)
        with pytest.raises(SystemExit):
            await cli.cmd_undo(cli.argparse.Namespace(all=True, ids=None,
                                                      confirm_db="not_this_database"))
        async with async_session_factory() as session:
            assert (await session.get(LexemeSense, ids["s2"])).needs_review is True
        # Dry run through the CLI: read only, nothing written, nothing reported.
        await cli.cmd_apply(cli.argparse.Namespace(decisions=decisions, confirm_db=None,
                                                   allow_material_fixes=False, out=tmp_path))
        assert not list(tmp_path.glob("apply_*"))
        async with async_session_factory() as session:
            assert (await session.get(LexemeSense, ids["s2"])).needs_review is True
        # The real thing, then its report.
        await cli.cmd_apply(cli.argparse.Namespace(
            decisions=decisions, confirm_db=cli.database_name(), allow_material_fixes=False,
            out=tmp_path))
        assert len(list(tmp_path.glob("apply_*.jsonl"))) == 1
    finally:
        await _gone(ids)


# --- the lock ---------------------------------------------------------------------------------


async def test_a_claude_decision_locks_the_sense_against_cald_apply_and_restore(tmp_path):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)  # `light` is flagged judge_unsure
    try:
        results = await _run([_d(ids["light"], "fix", meaning_uz="mening tarjimam", meaning_uz_alt="")])
        assert results[0].outcome == "applied"
        before = (await _state(ids))["senses"][ids["light"]]
        async with async_session_factory() as session:
            assert (await session.get(LexemeSense, ids["light"])).approved_at is not None

        counts = await _apply_all(out, ids)
        assert counts["locked by review"] == 1  # exactly as a human approval
        assert (await _state(ids))["senses"][ids["light"]] == before
        await lc.map_new_lexemes([ids["lexeme"]], gemini=FakeModel(), out_dir=out, judge=JUDGE)
        assert (await _state(ids))["senses"][ids["light"]] == before
        async with async_session_factory() as session:
            await lc.restore_senses(session, [ids["light"]])
            await session.commit()
        assert (await _state(ids))["senses"][ids["light"]] == before
    finally:
        await _drop(ids)


# --- undo -------------------------------------------------------------------------------------


async def test_undo_puts_every_value_back_exactly():
    ids = await _world()
    try:
        before = await _full(ids)
        await _run([
            _d(ids["s1"], "fix", cefr="A2", meaning_uz="kichkina narsa", meaning_uz_alt=""),
            _d(ids["s2"]),
            _d(ids["v1"], "human", "low", "unsure"),
        ])
        assert await _full(ids) != before
        # A dry run says what it would do and does nothing.
        dry = await _undo(None, write=False)
        assert {r.outcome for r in dry if r.sense_id in {str(ids['s1']), str(ids['s2'])}} == {
            "would undo"}
        assert await _full(ids) != before
        results = await _undo([ids["s1"], ids["s2"], ids["v1"]])
        assert [r.outcome for r in results] == ["undone"] * 3
        assert _loose(await _full(ids)) == _loose(before)
        async with async_session_factory() as session:
            logs = (await session.exec(select(LexiconAiReview).where(
                LexiconAiReview.sense_id.in_([ids["s1"], ids["s2"], ids["v1"]])))).all()
            assert len(logs) == 3 and all(log.undone_at for log in logs)  # history kept
        assert await _undo([ids["s1"]]) == []  # nothing active any more
        # ...and it can be decided again.
        again = await _run([_d(ids["s2"])])
        assert again[0].outcome == "applied"
    finally:
        await _gone(ids)


async def test_undo_leaves_alone_what_a_person_changed_since():
    ids = await _world()
    try:
        await _run([_d(ids["s1"], "fix", cefr="A2"), _d(ids["s2"]),
                    _d(ids["v1"], "human", "high", "look")])
        async with async_session_factory() as session:
            s1 = await session.get(LexemeSense, ids["s1"])
            await lexicon_review.fix_and_approve(  # a person re-fixes s1
                session, s1, admin_id=ids["user"], meaning_uz="odam yozgan", definition_en=None,
                cefr=None)
            v1 = await session.get(LexemeSense, ids["v1"])
            v1.review_note = "someone edited the note"
            session.add(v1)
            await session.commit()
        after = await _full(ids)
        results = {r.sense_id: r for r in await _undo(None) if r.sense_id in {
            str(ids["s1"]), str(ids["s2"]), str(ids["v1"])}}
        assert results[str(ids["s1"])].outcome == "skipped"
        assert "approved by the review account" in results[str(ids["s1"])].detail
        assert results[str(ids["v1"])].outcome == "skipped"
        assert "changed since" in results[str(ids["v1"])].detail
        assert results[str(ids["s2"])].outcome == "undone"
        now = await _full(ids)
        assert now["s1"] == after["s1"] and now["v1"] == after["v1"]
        assert now["s2"]["needs_review"] is True and now["s2"]["approved_by"] is None
    finally:
        await _gone(ids)


# --- material fixes ---------------------------------------------------------------------------


async def test_material_fixes_move_a_pointer_and_undo_moves_it_back():
    ids = await _world()
    try:
        before = await _full(ids)
        sentence_row, verb_row = ids["rows"][0], ids["rows"][3]
        decision = _d(ids["s1"], "fix", cefr="B1", material_fixes=[
            {"kind": "relink_sense", "row_id": str(sentence_row), "to_sense_id": str(ids["s3"])},
            {"kind": "relink_lexeme", "row_id": str(verb_row), "to_sense_id": str(ids["v1"])},
        ])
        assert (await _run([decision]))[0].outcome == "rejected"  # off by default
        results = await _run([decision], material=True)
        assert results[0].outcome == "applied"
        after = await _full(ids)
        assert after["row0"]["sense_id"] == ids["s3"] and after["row0"]["lexeme_id"] == ids["noun"]
        assert (after["row3"]["lexeme_id"], after["row3"]["sense_id"], after["row3"]["pos"]) == (
            ids["verb"], ids["v1"], "v")
        assert after["row1"] == before["row1"] and after["row2"] == before["row2"]
        async with async_session_factory() as session:
            log = (await session.exec(select(LexiconAiReview).where(
                LexiconAiReview.sense_id == ids["s1"]))).one()
            assert [f["kind"] for f in log.material_fixes] == ["relink_sense", "relink_lexeme"]
            assert log.material_fixes[0]["before"]["sense_id"] == str(ids["s1"])

        # a row moved by someone else since blocks the whole undo
        async with async_session_factory() as session:
            row = await session.get(MaterialVocabulary, sentence_row)
            row.sense_id = ids["s2"]
            session.add(row)
            await session.commit()
        blocked = await _undo([ids["s1"]])
        assert blocked[0].outcome == "skipped" and "material rows changed" in blocked[0].detail
        async with async_session_factory() as session:
            row = await session.get(MaterialVocabulary, sentence_row)
            row.sense_id = ids["s3"]
            session.add(row)
            await session.commit()
        assert (await _undo([ids["s1"]]))[0].outcome == "undone"
        assert await _full(ids) == before
    finally:
        await _gone(ids)


async def test_a_material_fix_can_only_do_the_two_safe_things():
    ids = await _world()
    other = await _world()
    try:
        row, rows = str(ids["rows"][0]), ids["rows"]

        def fix(kind, to, row_id=None):
            return _d(ids["s1"], "fix", cefr="B1", material_fixes=[
                {"kind": kind, "row_id": str(row_id or row), "to_sense_id": str(to)}])

        for decision, why in (
            (fix("relink_sense", ids["v1"]), "stays inside the lexeme"),
            (fix("relink_sense", other["s1"]), "stays inside the lexeme"),
            (fix("relink_lexeme", ids["s2"]), "ANOTHER lexeme"),
            (fix("relink_lexeme", other["s1"]), "same lemma"),  # a different word altogether
            (fix("relink_sense", ids["s2"], row_id=rows[2]), "not linked to this sense"),
            (fix("relink_sense", ids["s1"]), "the sense itself"),
            (fix("relink_sense", uuid.uuid4()), "does not exist"),
            (fix("relink_sense", ids["s2"], row_id=uuid.uuid4()), "does not exist"),
        ):
            result = (await _run([decision], material=True))[0]
            assert result.outcome == "rejected" and why in result.detail, (why, result)
        # The sense was never touched, nor any row.
        async with async_session_factory() as session:
            assert (await session.get(LexemeSense, ids["s1"])).needs_review is True
            assert (await session.get(MaterialVocabulary, ids["rows"][0])).sense_id == ids["s1"]
    finally:
        await _gone(ids)
        await _gone(other)


# --- status -----------------------------------------------------------------------------------


async def test_status_counts_by_reason_and_outcome():
    ids = await _world()
    try:
        async with async_session_factory() as session:
            start = await air.status(session)
        await _run([_d(ids["s1"], "fix", cefr="B1"), _d(ids["s2"]),
                    _d(ids["v1"], "human", "medium", "check")])
        async with async_session_factory() as session:
            mid = await air.status(session)
            listed = await air.list_outcome(session, "left for a human")
        delta = lambda a, b, reason, outcome: b[reason][outcome] - a[reason][outcome]  # noqa: E731
        assert delta(start, mid, "ngsl_conflict", "fixed") == 1
        assert delta(start, mid, "ngsl_conflict", "pending") == -1
        assert delta(start, mid, "lemma_merge", "approved") == 1
        assert delta(start, mid, "pos_mismatch", "left for a human") == 1
        assert delta(start, mid, "(any reason)", "pending") == -3  # the human one is "left"
        assert delta(start, mid, "(any reason)", "left for a human") == 1
        assert any(str(ids["v1"]) in line and "check" in line for line in listed)
        assert "pos_mismatch" in air.format_status(mid)
        await _undo([ids["s1"], ids["s2"], ids["v1"]])
        async with async_session_factory() as session:
            end = await air.status(session)
        assert end["(any reason)"] == start["(any reason)"]
    finally:
        await _gone(ids)


# --- the account ------------------------------------------------------------------------------


async def test_the_system_account_is_created_once_and_can_never_log_in():
    async with async_session_factory() as session:
        first = await air.ensure_account(session)
        await session.commit()
    async with async_session_factory() as session:
        second = await air.ensure_account(session)
        await session.commit()
        assert first.id == second.id  # idempotent
        assert (second.email, second.display_name) == (REVIEW_BOT_EMAIL, "Claude review")
        assert second.is_admin is False and second.hashed_password is None
        assert is_system_account(second)
        assert not (await session.exec(select(AuthIdentity).where(
            AuthIdentity.user_id == second.id))).all()
        count = len((await session.exec(select(User).where(User.email == REVIEW_BOT_EMAIL))).all())
        assert count == 1

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        # Even a token minted for it opens nothing: no session, no refresh, no admin.
        cookies = {"access_token": create_access_token(str(second.id))}
        assert (await client.get("/api/auth/me", cookies=cookies)).status_code == 401
        assert (await client.get("/api/admin/lexicon/review", cookies=cookies)).status_code == 401
        refresh = await client.post(
            "/api/auth/refresh", cookies={"refresh_token": create_refresh_token(str(second.id))})
        assert refresh.status_code == 401
        # A real user's token still works (the guard is not a blanket).
        async with async_session_factory() as session:
            person = User(email=f"airev-{uuid.uuid4().hex}@test.local", display_name="person")
            session.add(person)
            await session.commit()
        try:
            ok = await client.get("/api/auth/me",
                                  cookies={"access_token": create_access_token(str(person.id))})
            assert ok.status_code == 200
        finally:
            async with async_session_factory() as session:
                await session.delete(await session.get(User, person.id))
                await session.commit()


# --- Studio sees who approved and the note ------------------------------------------------------


async def test_the_review_api_names_the_approver_and_shows_the_note():
    ids = await _world()
    try:
        async with async_session_factory() as session:
            admin = User(email=f"airev-admin-{uuid.uuid4().hex}@test.local",
                         display_name="An Admin", is_admin=True)
            session.add(admin)
            await session.commit()
        await _run([_d(ids["v1"], "human", "high", "the pos looks wrong to me")])
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     base_url="http://test") as client:
            cookies = {"access_token": create_access_token(str(admin.id))}
            page = (await client.get("/api/admin/lexicon/review?reason=pos_mismatch&limit=200",
                                     cookies=cookies)).json()
            row = next(r for r in page["rows"] if r["sense_id"] == str(ids["v1"]))
            assert row["review_note"] == "Claude review (high): the pos looks wrong to me"
            assert row["approved_by_name"] is None
            done = (await client.post(f"/api/admin/lexicon/review/{ids['v1']}/approve",
                                      cookies=cookies)).json()
            assert done["approved_by_name"] == "An Admin"
    finally:
        await _gone(ids)
        async with async_session_factory() as session:
            await session.exec(text("delete from users where email like 'airev-admin-%'"))
            await session.commit()
