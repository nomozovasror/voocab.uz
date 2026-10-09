"""CALD phase 2a (`app.services.lexicon_cald`): the parts that write.

* the worker's hook end to end -- map, translate v2, the comparison judge
  and apply -- on seeded rows, with a fake model, then run again (nothing
  asked twice, nothing changed), then restored;
* apply is idempotent;
* the loose keep rule, as the plan applies it;
* `lexicon_enrich` never rewrites a CALD sense (the guard);
* the licences page never counts a CALD definition as OEWN's;
* the lookup lists identical definitions once (`lemma_senses.arrange`);
* a machine without the private index does nothing, and says so once.

Every dictionary entry here is INVENTED (no CALD text in this repository);
each test's lemmas carry a random tag so a shared test database is safe.
"""

import json
import logging
import re
import uuid

from sqlmodel import select

from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense
from app.models.material import Material
from app.models.part import Part
from app.models.user import User
from app.models.vocabulary import MaterialVocabulary
from app.services import lemma_senses
from app.services import lexicon_cald as lc
from app.services import lexicon_enrich as le
from app.services import lexicon_licences

JUDGE = "judge-x"


def _entries(lemma: str) -> dict:
    return {lemma: {"headword": lemma, "blocks": [
        {"pos": "noun", "guideword": "LIGHT",
         "pron": {"uk": {"ipa": "x", "audio": "media/audio/x.mp3"}},
         "senses": [{"level": "B2", "definition": "test sense: a weak shine"}]},
        {"pos": "noun", "guideword": "HOPE",
         "senses": [{"definition": "test sense: a small sign of hope"}]},
    ]}}


def _build_index(tmp_path, lemma: str):
    source = tmp_path / "src"
    (source / "data").mkdir(parents=True)
    (source / "data" / "entries.json").write_text(json.dumps(_entries(lemma)))
    out = tmp_path / "private"
    lc.build_index(source, out)
    return out


def _blocks(prompt: str) -> list[tuple[str, str]]:
    """``(key, the item's text)`` for each ``k<n>`` item of a batched prompt."""
    parts = re.split(r"^(k\d+)[: ]", prompt, flags=re.M)
    return [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


class FakeModel:
    """Answers the CALD prompts by what each item says: our "flickering"
    sense is LIGHT, our "hope" sense is HOPE, anything else none; the
    translators answer per guideword; the judge prefers the new pair for
    LIGHT and the old one for HOPE, whichever side (A/B) it stands on."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.usage = le.UsageLog()

    async def ask(self, model, prompt, *, step, max_tokens=0, repair_flat=False, parse=None):
        self.calls.append(step)
        blocks = _blocks(prompt.split("{items}")[0] if "{items}" in prompt else prompt)
        if step == "cald-map":
            answers = {}
            for key, text in blocks:
                ids = dict(re.findall(r"^\s+(c\d+) \[noun · (\w+)\]", text, re.M))
                by_gw = {gw: cid for cid, gw in ids.items()}
                ours = re.search(r'Our definition: "(.*)"', text).group(1)
                if "flickering" in ours:
                    answers[key] = {"choice": by_gw["LIGHT"], "confidence": "high", "reason": "t"}
                elif "hope" in ours:
                    answers[key] = {"choice": by_gw["HOPE"], "confidence": "medium", "reason": "t"}
                else:
                    answers[key] = {"choice": "none", "confidence": "high", "reason": "t"}
            return {"answers": answers}
        if step == "cald-translate-v2":
            word = "yangi nur" if model == le.MODEL_MAIN else "zaif nur"
            return {"items": {k: {"uz": word if "[LIGHT]" in t else "boshqa umid",
                                  "flag": "replaced", "reason": "t"} for k, t in blocks}}
        if step.startswith("cald-compare"):
            verdicts = {}
            for key, text in blocks:
                a = re.search(r"^\s+A: (.*)$", text, re.M).group(1)
                want = "yangi nur" if "[LIGHT]" in text else "umid uchquni"
                verdicts[key] = {"better": "a" if want in a else "b", "wrong_a": False,
                                 "wrong_b": False, "reason": "t"}
            return {"verdicts": verdicts}
        return None


async def _seed(lemma: str) -> dict:
    async with async_session_factory() as session:
        user = User(email=f"cald-{lemma}@test.local", display_name="cald test")
        session.add(user)
        await session.flush()
        material = Material(author_id=user.id, type="reading", title=f"cald {lemma}",
                            visibility="private")
        session.add(material)
        await session.flush()
        part = Part(material_id=material.id, order_index=0, title="P",
                    passage={"paragraphs": []}, first_number=1)
        session.add(part)
        lexeme = Lexeme(lemma=lemma, pos="n", frequency_band="wider", frequency_source="ngsl",
                        cefr="C1")
        session.add(lexeme)
        await session.flush()
        light = LexemeSense(lexeme_id=lexeme.id, sense_rank=1, definition_en="a faint flickering light",
                            meaning_uz="xira nur", meaning_uz_alt="", cefr="C1",
                            source_id="oewn", licence="cc-by-4.0", definition_source="oewn",
                            oewn_synset_id=f"t-{lemma}-1", oewn_rank=1, oewn_count=4,
                            review_reasons=["judge_unsure"], needs_review=True, provisional=False)
        hope = LexemeSense(lexeme_id=lexeme.id, sense_rank=2, definition_en="a slight sign of hope",
                           meaning_uz="umid uchquni", meaning_uz_alt="umid", cefr="B2",
                           provisional=False)
        other = LexemeSense(lexeme_id=lexeme.id, sense_rank=3, definition_en="an unrelated meaning",
                            meaning_uz="boshqa", cefr="B1", provisional=False)
        session.add_all([light, hope, other])
        await session.flush()
        rows = []
        for i, level in enumerate(("C1", "B2")):
            row = MaterialVocabulary(
                material_id=material.id, part_id=part.id, lemma=f"{lemma}{i}", surface=lemma,
                pos="n", meaning_en="m", meaning_uz="u", meaning_core_en="m", meaning_core_uz="u",
                example=f"A {lemma} of light flickered.", cefr_level=level,
                lexeme_id=lexeme.id, sense_id=light.id)
            session.add(row)
            rows.append(row)
        await session.commit()
        return {"user": user.id, "material": material.id, "part": part.id, "lexeme": lexeme.id,
                "light": light.id, "hope": hope.id, "other": other.id,
                "rows": [r.id for r in rows]}


async def _drop(ids: dict) -> None:
    async with async_session_factory() as session:
        for row in (await session.exec(select(MaterialVocabulary).where(
                MaterialVocabulary.material_id == ids["material"]))).all():
            await session.delete(row)
        await session.flush()
        for sense in (await session.exec(select(LexemeSense).where(
                LexemeSense.lexeme_id == ids["lexeme"]))).all():
            await session.delete(sense)
        await session.flush()
        for model, key in ((Lexeme, "lexeme"), (Part, "part"), (Material, "material"),
                           (User, "user")):
            obj = await session.get(model, ids[key])
            if obj is not None:
                await session.delete(obj)
                await session.flush()
        await session.commit()


async def _state(ids: dict) -> dict:
    async with async_session_factory() as session:
        senses = {s.id: s for s in (await session.exec(select(LexemeSense).where(
            LexemeSense.lexeme_id == ids["lexeme"]))).all()}
        rows = (await session.exec(select(MaterialVocabulary).where(
            MaterialVocabulary.id.in_(ids["rows"])))).all()
        lexeme = await session.get(Lexeme, ids["lexeme"])
    columns = ("definition_en", "meaning_uz", "meaning_uz_alt", "meaning_uz_material", "cefr",
               "cefr_source", "definition_source", "cald_ref", "licence", "review_reasons",
               "needs_review", "definition_en_pre_cald", "cefr_pre_cald", "meaning_uz_pre_cald",
               "meaning_uz_alt_pre_cald", "licence_pre_cald", "review_reasons_pre_cald")
    return {
        "senses": {sid: {c: getattr(s, c) for c in columns}
                   | {"applied": s.cald_applied_at is not None} for sid, s in senses.items()},
        "rows": sorted((r.cefr_level, r.cefr_level_pre_cald) for r in rows),
        "lexeme_cefr": lexeme.cefr,
    }


def _lemma() -> str:
    return "caldword" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:8])


async def test_the_hook_maps_translates_judges_applies_and_restore_puts_it_back(tmp_path,
                                                                               monkeypatch):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    try:
        before = await _state(ids)
        async with async_session_factory() as session:
            oewn_before = {r["key"]: r["count"] for r in await lexicon_licences.sources(session)}
        model = FakeModel()
        counts = await lc.map_new_lexemes([ids["lexeme"]], gemini=model, out_dir=out, judge=JUDGE)
        assert counts["newly applied"] == 2 and counts["plan:none"] == 1
        assert {"cald-map", "cald-translate-v2", f"cald-compare:{JUDGE}"} <= set(model.calls)

        after = await _state(ids)
        light, hope, other = (after["senses"][ids[k]] for k in ("light", "hope", "other"))
        index = lc.CaldIndex(lc.load_index_data(out))
        light_ref, hope_ref = index.match(lemma, "n").refs
        # LIGHT: CALD's definition and level; the judge preferred the new pair.
        assert light["definition_en"] == "test sense: a weak shine"
        assert (light["definition_source"], light["cald_ref"], light["licence"]) == (
            "cald", light_ref, "cald")
        assert (light["cefr"], light["cefr_source"]) == ("B2", "cald")
        assert (light["meaning_uz"], light["meaning_uz_alt"]) == ("yangi nur", "zaif nur")
        assert light["review_reasons"] == [] and not light["needs_review"]  # judge passed it
        assert (light["definition_en_pre_cald"], light["cefr_pre_cald"],
                light["meaning_uz_pre_cald"], light["licence_pre_cald"],
                light["review_reasons_pre_cald"]) == (
            "a faint flickering light", "C1", "xira nur", "cc-by-4.0", ["judge_unsure"])
        # HOPE: CALD has no level -- ours stays; the judge kept the old pair.
        assert hope["definition_en"] == "test sense: a small sign of hope"
        assert (hope["cefr"], hope["cefr_source"], hope["cald_ref"]) == ("B2", "ours", hope_ref)
        assert (hope["meaning_uz"], hope["meaning_uz_alt"]) == ("umid uchquni", "umid")
        # The third: the model said none -- untouched.
        assert other == before["senses"][ids["other"]]
        # The material rows of the levelled sense take CALD's level, keeping theirs.
        assert after["rows"] == [("B2", "B2"), ("B2", "C1")]
        # the rank-1 sense's: senses are re-ordered easiest first when a level
        # changes (`lexicon.rerank_lexemes`), so it is the easiest sense's
        assert after["lexeme_cefr"] == "B1"
        # The licences page: the CALD-defined OEWN sense is no longer OEWN's.
        async with async_session_factory() as session:
            oewn_after = {r["key"]: r["count"] for r in await lexicon_licences.sources(session)}
        assert oewn_after.get("oewn", 0) == oewn_before.get("oewn", 0) - 1
        assert "cald" not in oewn_after

        # Again: nothing is asked, nothing changes (applied senses are done,
        # the "none" answer is in the log).
        again = FakeModel()
        await lc.map_new_lexemes([ids["lexeme"]], gemini=again, out_dir=out, judge=JUDGE)
        assert again.calls == []
        assert await _state(ids) == after

        # apply is idempotent: the same plans re-applied write the same thing.
        log = lc.DecisionLog(out / lc.DECISIONS_FILE)
        items = await lc.load_items(index, lexeme_ids=[ids["lexeme"]])
        assert {i["definition_en"] for i in items if i["applied"]} == {
            "a faint flickering light", "a slight sign of hope"}  # the BEFORE view
        plans = lc.plan_items(items, index, log, JUDGE)
        async with async_session_factory() as session:
            counts = await lc.apply_plans(session, plans)
            await session.commit()
        assert counts["re-applied"] == 2 and not counts["newly applied"]
        assert await _state(ids) == after

        # restore: everything as it was.
        async with async_session_factory() as session:
            restored, lexemes = await lc.restore_senses(session, [ids["light"], ids["hope"]])
            await session.commit()
        assert restored["senses restored"] == 2 and restored["material rows restored"] == 2
        assert lexemes == {ids["lexeme"]}
        # (the lexeme's level is the easiest sense's, not what the hand-built world had)
        assert {**await _state(ids), "lexeme_cefr": None} == {**before, "lexeme_cefr": None}
    finally:
        await _drop(ids)


async def test_a_sense_that_changed_since_the_plan_is_not_applied(tmp_path):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    try:
        index = lc.CaldIndex(lc.load_index_data(out))
        log = lc.DecisionLog(out / lc.DECISIONS_FILE)
        items = await lc.load_items(index, lexeme_ids=[ids["lexeme"]])
        model = FakeModel()
        await lc.run_map(items, index, log, model)
        plans = lc.plan_items(items, index, log, JUDGE)
        async with async_session_factory() as session:
            sense = await session.get(LexemeSense, ids["light"])
            sense.definition_en = "re-enriched meanwhile"
            session.add(sense)
            await session.commit()
        async with async_session_factory() as session:
            counts = await lc.apply_plans(session, plans)
            await session.commit()
        assert counts["drifted"] == 1 and counts["newly applied"] == 1  # hope only
        async with async_session_factory() as session:
            assert (await session.get(LexemeSense, ids["light"])).definition_source == "oewn"
    finally:
        await _drop(ids)


class EnrichModel:
    """`lexicon_enrich.enrich`'s steps, answered so a re-run WOULD rewrite
    every sense: the material use is labelled S1 (an OEWN gloss), every
    sense graded A1, everything translated."""

    def __init__(self) -> None:
        self.prompts: list[tuple[str, str]] = []

    async def ask(self, model, prompt, *, step, max_tokens=0, repair_flat=False, parse=None):
        self.prompts.append((step, prompt))
        keys = re.findall(r"^(k\d+):", prompt, re.M)
        if step == "match":
            uses = {u: "S1" for u in re.findall(r"^\s+(u\d+): \"", prompt, re.M)}
            return {"words": [{"id": "w1", "uses": uses, "senses": {"S1": {"pos": "n"}}}]}
        if step == "cefr":
            return {"levels": {k: "A1" for k in keys}}
        if step == "translate":
            return {"uz": {k: "tarjima" for k in keys}}
        if step == "judge":
            return {"verdicts": {k: {"verdict": "same", "better": "b"} for k in keys}}
        return None


async def test_re_enrichment_never_rewrites_a_cald_sense(tmp_path):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    try:
        await lc.map_new_lexemes([ids["lexeme"]], gemini=FakeModel(), out_dir=out, judge=JUDGE)
        applied = await _state(ids)
        oewn = {(lemma, "n"): [{"synset": f"t-{lemma}-1", "rank": 1, "count": 4,
                                "definition": "an oewn gloss that would replace it"}]}
        model = EnrichModel()
        await le.enrich(async_session_factory, model, [ids["lexeme"]], oewn)
        after = await _state(ids)
        for key in ("light", "hope"):
            want, got = applied["senses"][ids[key]], after["senses"][ids[key]]
            for column in ("definition_en", "cefr", "meaning_uz", "meaning_uz_alt",
                           "definition_source", "licence", "cald_ref"):
                assert got[column] == want[column], (key, column)
        cefr_prompts = "\n".join(p for step, p in model.prompts if step == "cefr")
        assert "test sense" not in cefr_prompts  # a CALD sense is not regraded
        assert after["senses"][ids["other"]]["cefr"] == "A1"  # an ordinary sense is
        async with async_session_factory() as session:
            senses = (await session.exec(select(LexemeSense).where(
                LexemeSense.lexeme_id == ids["lexeme"]))).all()
        assert {ids["light"], ids["hope"]} <= {s.id for s in senses}  # never deleted
    finally:
        await _drop(ids)


def test_plan_senses_keeps_a_locked_sense_whatever_the_matcher_says():
    sense_id = uuid.uuid4()
    row = le.Row(id=uuid.uuid4(), sense_id=sense_id, meaning_en="h", meaning_uz="u",
                 core_en="c", core_uz="cu", example="an example", cefr_level="B2")
    work = le.LexemeWork(
        id=uuid.uuid4(), lemma="w", pos="n", is_phrase=False, frequency_band="core",
        oewn=[{"synset": "s-1", "rank": 1, "definition": "an oewn gloss"}],
        senses=[le.Sense(id=sense_id, definition_en="test sense: cald text", meaning_uz="cald uz",
                         meaning_uz_alt="alt", cefr="B2", licence="cald", locked=True,
                         review_reasons=["judge_unsure"])],
        rows=[row])
    uses = le.build_uses(work.rows)
    le.plan_senses(work, uses, {"uses": {uses[0].id: "S1"},
                                "senses": {"S1": {"uz": f"{uses[0].id}b"}}})
    planned = next(s for s in work.plan if s.id == sense_id)
    assert (planned.definition_en, planned.meaning_uz, planned.meaning_uz_alt, planned.cefr,
            planned.licence) == ("test sense: cald text", "cald uz", "alt", "B2", "cald")
    assert planned.locked and not planned.translate and not planned.normalise
    assert "judge_unsure" in planned.review_reasons
    # Its identity is kept too: the matcher's S1 label does not relabel it
    # (OEWN's top sense is added beside it instead).
    assert (planned.oewn_synset_id, planned.oewn_rank, planned.source_id) == (None, None, "model")
    assert [s.oewn_synset_id for s in work.plan if s.id is None] == ["s-1"]


# --- the keep rule, as the plan applies it (no database) ---------------------------


def _index():
    return lc.CaldIndex(lc.parse_entries(_entries("glow"), {}))


def _item(sense_id: str, uz: str, alt: str = "", definition: str = "our def") -> dict:
    return {"sense_id": sense_id, "lexeme_id": "L", "lemma": "glow", "pos": "n", "sense_rank": 1,
            "frequency_band": None, "definition_en": definition, "meaning_uz": uz,
            "meaning_uz_alt": alt, "cefr": "B1", "licence": "proprietary", "review_reasons": [],
            "source_id": "model", "approved": False, "applied": False, "current": {},
            "example": "", "refs": ["glow#0#0", "glow#1#0"]}


def _logged(log, index, item, *, main: str | None, alt: str | None = None, runs=None):
    cands = index.candidates(item["refs"])
    log.put("map", lc.map_key(item, cands), {"sense_id": item["sense_id"], "answered": True,
                                              "ref": "glow#0#0", "confidence": "high",
                                              "reason": "r"})
    entry = lc.v2_entry(item, "glow#0#0", index)
    for model, uz in ((le.MODEL_MAIN, main), (le.MODEL_ALT, alt)):
        if uz is not None:
            log.put("translate2", lc.translate2_key(entry, model), {
                "sense_id": item["sense_id"], "answered": True, "uz": uz, "flag": "adjusted"})
    if runs is not None:
        entry.update(new_uz=main or alt or "", new_alt=(alt or "") if main else "")
        log.put("compare", lc.compare_key(entry, JUDGE), {
            "sense_id": item["sense_id"], "judge_model": JUDGE, "per_run": runs,
            **lc.combine_comparison(runs)})


def _run(better, wrong_old=False, wrong_new=False):
    return {"better": better, "wrong_old": wrong_old, "wrong_new": wrong_new, "reason": ""}


def test_the_loose_keep_rule(tmp_path):
    index = _index()
    log = lc.DecisionLog(tmp_path / "d.jsonl")
    cases = {
        "both-new": (_item("s1", "eski"), dict(main="yangi", alt="yangi2",
                                               runs=[_run("new"), _run("equal")])),
        "one-run-old": (_item("s2", "eski"), dict(main="yangi", runs=[_run("old"), _run("new")])),
        "one-wrong": (_item("s3", "eski"), dict(main="yangi",
                                                runs=[_run("new", wrong_new=True), _run("new")])),
        "both-wrong": (_item("s4", "eski"), dict(main="yangi", runs=[
            _run("equal", True, True), _run("equal", True, True)])),
        "no-verdict": (_item("s5", "eski"), dict(main="yangi", runs=[None, None])),
        "identical": (_item("s6", "eski so'z", "boshqa"), dict(main="Eski so'z.", alt="boshqa")),
        "no-old": (_item("s7", ""), dict(main="yangi")),
        "untranslated": (_item("s8", "eski"), dict(main=None)),
        "one-translator": (_item("s9", "eski"), dict(main=None, alt="yangi",
                                                     runs=[_run("equal"), _run("new")])),
    }
    for item, kwargs in cases.values():
        _logged(log, index, item, **kwargs)
    plans = {name: p for name, p in zip(cases, lc.plan_items(
        [item for item, _ in cases.values()], index, log, JUDGE))}
    got = {name: (p.uz, p.uz_why) for name, p in plans.items()}
    assert got == {
        "both-new": ("new", "judge-new"), "one-run-old": ("old", "judge-old"),
        "one-wrong": ("old", "judge-old"), "both-wrong": ("old", "judge-old"),
        "no-verdict": ("old", "no-verdict"), "identical": ("old", "identical"),
        "no-old": ("new", "no-old"), "untranslated": ("old", "untranslated"),
        "one-translator": ("new", "judge-new"),
    }
    assert all(p.decision == "mapped" and p.definition == "test sense: a weak shine"
               and p.level == "B2" for p in plans.values())
    assert (plans["both-new"].new_uz, plans["both-new"].new_alt) == ("yangi", "yangi2")
    assert (plans["one-translator"].new_uz, plans["one-translator"].new_alt) == ("yangi", "")
    # What the review queue is told: passed -> same; every run called both wrong -> different.
    assert plans["both-new"].judge_verdict == "same"
    assert plans["both-wrong"].judge_verdict == "different"
    assert plans["one-run-old"].judge_verdict is None


def test_low_confidence_and_a_changed_question_are_not_applied(tmp_path):
    index = _index()
    log = lc.DecisionLog(tmp_path / "d.jsonl")
    low, stale = _item("s1", "eski"), _item("s2", "eski")
    for item, confidence in ((low, "low"), (stale, "high")):
        log.put("map", lc.map_key(item, index.candidates(item["refs"])), {
            "sense_id": item["sense_id"], "answered": True, "ref": "glow#0#0",
            "confidence": confidence, "reason": "r"})
    stale = dict(stale, definition_en="our definition, since rewritten")
    unmatched = dict(_item("s3", "eski"), refs=[])
    plans = lc.plan_items([low, stale, unmatched], index, log, JUDGE)
    assert [p.decision for p in plans] == ["none", "unanswered", "unmatched"]


def test_summary_counts_shifts_collisions_and_material_rows(tmp_path):
    index = _index()
    log = lc.DecisionLog(tmp_path / "d.jsonl")
    a, b = _item("s1", "eski"), _item("s2", "", definition="another of ours")
    for item in (a, b):
        _logged(log, index, item, main="yangi", runs=[_run("new"), _run("new")])
    summary = lc.summarise(lc.plan_items([a, b], index, log, JUDGE),
                           {"s1": ["C1", "B2"], "__pre__s1": [None, None]})
    assert summary["cefr_shift"] == {"+1": 2}  # B1 -> B2 for both
    assert summary["collision_counts"] == {"same lemma": {"cald_senses": 1, "our_senses": 2}}
    assert summary["material_rows"] == {"re-levelled": 1, "already that level": 1}
    assert summary["uz"] == {"new:judge-new": 1, "new:no-old": 1}


# --- the lookup shows an identical definition once -----------------------------------


def test_identical_definitions_are_listed_once_and_the_anchor_wins():
    noun, verb = Lexeme(lemma="w", pos="n"), Lexeme(lemma="w", pos="v")
    first = LexemeSense(lexeme_id=noun.id, definition_en="Test sense: one meaning.",
                        meaning_uz="bir", sense_rank=1, oewn_count=9)
    twin = LexemeSense(lexeme_id=noun.id, definition_en="test sense:  one meaning",
                       meaning_uz="ikki", sense_rank=2, oewn_count=3)
    other = LexemeSense(lexeme_id=verb.id, definition_en="test sense: another", meaning_uz="uch",
                        sense_rank=1)
    blank = LexemeSense(lexeme_id=verb.id, definition_en="", meaning_uz="faqat", sense_rank=2)
    blank2 = LexemeSense(lexeme_id=verb.id, definition_en="", meaning_uz="faqat2", sense_rank=3)
    rows = [(noun, first), (noun, twin), (verb, other), (verb, blank), (verb, blank2)]
    plain = lemma_senses.arrange(rows, anchor_lexeme_id=noun.id, anchor_sense_id=None)
    assert [v.meaning_uz for v in plain] == ["bir", "uch", "faqat", "faqat2"]
    anchored = lemma_senses.arrange(rows, anchor_lexeme_id=noun.id, anchor_sense_id=twin.id)
    assert [v.meaning_uz for v in anchored] == ["ikki", "uch", "faqat", "faqat2"]
    assert anchored[0].anchor


# --- no private index: nothing, said once --------------------------------------------


async def test_without_the_private_index_the_hook_does_nothing_and_says_so_once(tmp_path,
                                                                               caplog):
    model = FakeModel()
    with caplog.at_level(logging.INFO, logger="app.services.lexicon_cald"):
        for _ in range(3):
            assert await lc.map_new_lexemes([uuid.uuid4()], gemini=model,
                                            out_dir=tmp_path / "none") == {}
    assert model.calls == []
    assert sum("CALD index not present" in r.getMessage() for r in caplog.records) == 1


# --- re-verification of far-levelled mappings, and the CEFR cap --------------------


def _verdict(verdict):
    return {"verdict": verdict, "reason": "t"}


def test_combine_verify_follows_the_agreed_rule():
    same, diff, unsure = _verdict("same"), _verdict("different"), _verdict("unsure")
    assert lc.combine_verify([same, same])["keep"] is True
    assert lc.combine_verify([same, unsure])["keep"] is True  # unsure in ONE run only
    assert lc.combine_verify([same, diff]) | {"verdicts": None} == {
        "keep": False, "why": "different", "runs": 2, "verdicts": None}
    assert lc.combine_verify([diff, None])["keep"] is False  # different in either run
    assert lc.combine_verify([unsure, unsure])["why"] == "unsure"
    assert lc.combine_verify([unsure, unsure])["keep"] is False
    assert lc.combine_verify([same, None])["keep"] is None  # undecided: asked again
    assert lc.combine_verify([None, None])["keep"] is None


def test_verify_item_parse_and_the_swap():
    entry = {"id": "s1", "lemma": "nest", "pos": "n", "ref": "r", "ours": "our nest",
             "uz": "uya", "alt": "in", "example": "A bird's nest.",
             "cald": {"def": "test sense: a bird home", "gw": "HOME"}}
    plain, swapped = (lc.render_verify_item("k1", dict(entry, swap=s)) for s in (False, True))
    assert plain.index("(ours)") < plain.index("(Cambridge)")
    assert swapped.index("(Cambridge)") < swapped.index("(ours)")
    assert 'Our Uzbek: "uya / in"' in plain and "[HOME] test sense: a bird home" in plain
    assert lc.parse_verify_item({"verdict": "Different", "reason": "x"}, entry) == {
        "verdict": "different", "reason": "x"}
    assert lc.parse_verify_item("same", entry)["verdict"] == "same"
    assert lc.parse_verify_item({"verdict": "maybe"}, entry) is None


def _far_entries(lemma: str) -> dict:
    return {lemma: {"headword": lemma, "blocks": [
        {"pos": "noun", "guideword": "HOME",
         "senses": [{"level": "C2", "definition": "test sense: a home that birds build"}]},
        {"pos": "noun", "guideword": "FAIL",
         "senses": [{"level": "C2", "definition": "test sense: when a firm stops trading"}]},
        {"pos": "noun", "guideword": "NEAR",
         "senses": [{"level": "B2", "definition": "test sense: a near-level sense"}]},
    ]}}


def _far_item(sense_id, cefr, definition, refs):
    return dict(_item(sense_id, "eski", definition=definition), lemma="nest", cefr=cefr, refs=refs)


def test_the_cap_and_the_verify_decision_in_the_plan(tmp_path):
    index = lc.CaldIndex(lc.parse_entries(_far_entries("nest"), {}))
    log = lc.DecisionLog(tmp_path / "d.jsonl")
    refs = ["nest#0#0", "nest#1#0", "nest#2#0"]
    cases = {  # name: (our level, chosen ref, verify runs or None)
        "near": ("B1", "nest#2#0", None),          # +1: CALD's level taken
        "far-kept": ("A2", "nest#0#0", [_verdict("same"), _verdict("unsure")]),
        "far-dropped": ("A1", "nest#1#0", [_verdict("same"), _verdict("different")]),
        "far-unsure": ("B1", "nest#1#0", [_verdict("unsure"), _verdict("unsure")]),
        "far-unasked": ("A1", "nest#0#0", None),
        "no-level-of-ours": (None, "nest#0#0", None),  # nothing to compare: CALD's
    }
    items = {}
    for name, (cefr, ref, runs) in cases.items():
        item = _far_item(name, cefr, f"our {name} meaning", refs)
        items[name] = item
        log.put("map", lc.map_key(item, index.candidates(refs)), {
            "sense_id": name, "answered": True, "ref": ref, "confidence": "high", "reason": "r"})
        if runs is not None:
            log.put("verify", lc.verify_key(lc.verify_entry(item, ref, index), JUDGE), {
                "sense_id": name, "per_run": runs, **lc.combine_verify(runs)})
    plans = dict(zip(items, lc.plan_items(list(items.values()), index, log, JUDGE)))
    got = {n: (p.decision, p.level, p.cald_level, p.cefr_far) for n, p in plans.items()}
    assert got == {
        "near": ("mapped", "B2", "B2", False),
        "far-kept": ("mapped", None, "C2", True),      # mapped, but ours stays + flag
        "far-dropped": ("none", None, None, False),
        "far-unsure": ("none", None, None, False),
        "far-unasked": ("unverified", None, None, False),
        "no-level-of-ours": ("mapped", "C2", "C2", False),
    }
    assert plans["far-dropped"].reason.startswith("[re-verify: different]")
    # Only the far-levelled, still-undecided sense is a verify question; the
    # translation questions skip what re-verification dropped or has not decided.
    assert [e["id"] for e in lc.verify_todo(list(items.values()), index, log, JUDGE)] == [
        "far-unasked"]
    assert {e["id"] for e in lc.v2_entries(list(items.values()), index, log, JUDGE)} == {
        "near", "far-kept", "no-level-of-ours"}
    summary = lc.summarise(list(plans.values()), {"far-kept": ["A2"], "__pre__far-kept": [None],
                                                  "near": ["B1"], "__pre__near": [None]})
    assert summary["review_flags"] == {"cald_cefr_far": 1}
    assert summary["cefr_source"] == {"cald": 2, "ours (CALD 2+ bands away)": 1}
    assert summary["cefr_shift"] == {"+1": 1, "0": 1, "-->C2": 1}
    assert summary["material_rows"] == {"re-levelled": 1, "kept (sense keeps ours)": 1}
    assert summary["verify"] == {"kept (same)": 1, "dropped (different in a run)": 1,
                                 "dropped (unsure in both)": 1,
                                 "undecided (not asked yet)": 1}


class FarModel:
    """map: our "birds" sense -> HOME, our "collapse" sense -> FAIL; the
    re-verification says same for the birds sense and different for the
    other; translators and judge as plain as possible."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.usage = le.UsageLog()

    async def ask(self, model, prompt, *, step, max_tokens=0, repair_flat=False, parse=None):
        self.calls.append(step)
        blocks = _blocks(prompt)
        if step == "cald-map":
            answers = {}
            for key, text in blocks:
                by_gw = {gw: cid for cid, gw in
                         re.findall(r"^\s+(c\d+) \[noun · (\w+)\]", text, re.M)}
                ours = re.search(r'Our definition: "(.*)"', text).group(1)
                gw = "HOME" if "birds" in ours else "FAIL"
                answers[key] = {"choice": by_gw[gw], "confidence": "high", "reason": "t"}
            return {"answers": answers}
        if step.startswith("cald-verify"):
            return {"verdicts": {k: {"verdict": "same" if "birds" in t else "different",
                                     "reason": "t"} for k, t in blocks}}
        if step == "cald-translate-v2":
            return {"items": {k: {"uz": "qush uyasi", "flag": "adjusted", "reason": "t"}
                              for k, _ in blocks}}
        if step.startswith("cald-compare"):
            return {"verdicts": {k: {"better": "equal", "wrong_a": False, "wrong_b": False,
                                     "reason": "t"} for k, _ in blocks}}
        return None


async def test_far_levels_are_verified_capped_flagged_and_undone_when_dropped(tmp_path):
    lemma = _lemma()
    source = tmp_path / "src"
    (source / "data").mkdir(parents=True)
    (source / "data" / "entries.json").write_text(json.dumps(_far_entries(lemma)))
    out = tmp_path / "private"
    lc.build_index(source, out)
    ids = await _seed(lemma)
    try:
        async with async_session_factory() as session:
            for key, (definition, cefr) in (("light", ("a structure in which birds lay eggs", "A2")),
                                            ("hope", ("a sudden collapse", "A1"))):
                sense = await session.get(LexemeSense, ids[key])
                sense.definition_en, sense.cefr = definition, cefr
                session.add(sense)
            lexeme = await session.get(Lexeme, ids["lexeme"])
            lexeme.cefr = "A2"  # the rank-1 sense's, as everywhere else
            session.add(lexeme)
            await session.commit()
        before = await _state(ids)
        model = FarModel()
        counts = await lc.map_new_lexemes([ids["lexeme"]], gemini=model, out_dir=out, judge=JUDGE)
        assert model.calls.count(f"cald-verify:{JUDGE}") == 2  # one batch, two runs
        assert counts["newly applied"] == 1
        after = await _state(ids)
        birds, collapse = after["senses"][ids["light"]], after["senses"][ids["hope"]]
        # Kept by re-verification: CALD's definition, OUR level, both on the row, flagged.
        assert birds["definition_en"] == "test sense: a home that birds build"
        assert (birds["cefr"], birds["cefr_source"]) == ("A2", "ours")
        assert "cald_cefr_far" in birds["review_reasons"] and birds["needs_review"]
        assert after["rows"] == before["rows"]  # the sense kept ours: rows untouched
        async with async_session_factory() as session:
            assert (await session.get(LexemeSense, ids["light"])).cald_cefr == "C2"
        # Dropped by re-verification: nothing changed, and nothing translated for it.
        assert collapse == before["senses"][ids["hope"]]
        log = lc.DecisionLog(out / lc.DECISIONS_FILE)
        dropped = [r for (k, _), r in log.records.items()
                   if k == "verify" and r["sense_id"] == str(ids["hope"])]
        assert dropped and dropped[0]["keep"] is False and dropped[0]["why"] == "different"
        assert not [r for (k, _), r in log.records.items()
                    if k == "translate2" and r["sense_id"] == str(ids["hope"])]

        # A later decision dropping an APPLIED sense: apply puts it back.
        index = lc.CaldIndex(lc.load_index_data(out))
        items = await lc.load_items(index, lexeme_ids=[ids["lexeme"]], log=log)
        item = next(i for i in items if i["sense_id"] == str(ids["light"]))
        runs = [_verdict("different"), _verdict("same")]
        log.put("verify", lc.verify_key(lc.verify_entry(item, item["refs"][0], index), JUDGE), {
            "sense_id": item["sense_id"], "per_run": runs, **lc.combine_verify(runs)})
        async with async_session_factory() as session:
            counts = await lc.apply_plans(session, lc.plan_items(items, index, log, JUDGE))
            await session.commit()
        assert counts["restored (now none)"] == 1
        # everything but the lexeme's level, which is the easiest sense's now
        assert {**await _state(ids), "lexeme_cefr": None} == {**before, "lexeme_cefr": None}
    finally:
        await _drop(ids)


def test_a_label_lost_list_at_the_start_is_dropped_but_a_qualifier_is_kept() -> None:
    # Invented strings in the source's two shapes.
    assert lc.strip_label_lost_prefix("( zub, zubs) a small blue tool") == "a small blue tool"
    assert lc.strip_label_lost_prefix("( zub, /zʌb/ ) a small blue tool") == "a small blue tool"
    assert lc.strip_label_lost_prefix("(of a tool) small and blue") == "(of a tool) small and blue"
    assert lc.strip_label_lost_prefix("( only this)") == "( only this)"
