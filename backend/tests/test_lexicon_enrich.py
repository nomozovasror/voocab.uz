"""Lexicon P2 (`app.services.lexicon_enrich`): the parts that are DECISIONS
rather than model output -- how answers become merges and relinks, how
senses are ranked, when a sense needs review -- plus one end-to-end run
against the database with a scripted model, run twice to show a re-run
reuses every sense instead of rebuilding them.

Nothing here calls Gemini.
"""

import re
import uuid

from sqlmodel import select

from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense, TranslationReport
from app.models.material import Material
from app.models.part import Part
from app.models.user import User
from app.models.vocabulary import MaterialVocabulary, SavedWord, SavedWordContext
from app.services import lexicon_enrich as le

OEWN = [
    {"synset": "t-1", "rank": 1, "definition": "sloping land beside a body of water"},
    {"synset": "t-2", "rank": 2, "definition": "a financial institution"},
    {"synset": "t-3", "rank": 3, "definition": "an arrangement of objects in a row"},
]


def _row(sense_id, example, here="h", core="c", uz="uz", core_uz="cuz", level="B2"):
    return le.Row(id=uuid.uuid4(), sense_id=sense_id, meaning_en=here, meaning_uz=uz,
                  core_en=core, core_uz=core_uz, example=example, cefr_level=level)


def _work(senses, rows, oewn=OEWN, band="core"):
    return le.LexemeWork(id=uuid.uuid4(), lemma="bank", pos="n", is_phrase=False,
                         frequency_band=band, oewn=oewn, senses=senses, rows=rows)


# --- plan_senses --------------------------------------------------------------


def test_two_provisional_senses_on_one_synset_merge_and_rows_follow() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    rows = [_row(a, "money in the bank", here="money place", uz="bank"),
            _row(a, "cash at the bank", here="cash place", uz="bank2"),
            _row(b, "a bank loan", here="lender", uz="bank3", core="lender", core_uz="bank3")]
    work = _work([le.Sense(id=a, definition_en="A", provisional=True, review_reasons=["lemma_merge"]),
                  le.Sense(id=b, definition_en="B", provisional=True)], rows)
    uses = le.build_uses(rows)
    answer = {"uses": {u.id: "S2" for u in uses}, "senses": {"S2": {"uz": f"{uses[2].id}b"}}}
    le.plan_senses(work, uses, answer)

    merged = [s for s in work.plan if s.oewn_synset_id == "t-2"]
    assert len(merged) == 1
    sense = merged[0]
    assert sense.id == a  # the sense holding most of the rows survives
    assert set(sense.row_ids) == {r.id for r in rows}
    assert sense.absorbed == [b] and b in work.deleted
    assert sense.definition_en == "a financial institution"
    assert sense.source_id == "oewn" and sense.licence == "cc-by-4.0"
    assert sense.meaning_uz == "bank3" and not sense.translate  # copied, not translated
    assert sense.meaning_uz_material == "bank3" and not sense.normalise
    assert "lemma_merge" in sense.review_reasons
    # OEWN rank 1 added because it was missing; nothing deeper (top 1 only).
    added = [s for s in work.plan if s.id is None]
    assert [s.oewn_synset_id for s in added] == ["t-1"] and added[0].translate


def test_one_provisional_sense_holding_two_meanings_is_split() -> None:
    a = uuid.uuid4()
    rows = [_row(a, "the river bank", uz="qirg'oq"), _row(a, "the bank lent", here="x", uz="bank"),
            _row(a, "banks of the Nile", here="y", uz="sohil")]
    work = _work([le.Sense(id=a, definition_en="money or river", provisional=True)], rows)
    uses = le.build_uses(rows)
    labels = {uses[0].id: "S1", uses[1].id: "S2", uses[2].id: "S1"}
    le.plan_senses(work, uses, {"uses": labels, "senses": {}})

    by_synset = {s.oewn_synset_id: s for s in work.plan}
    assert by_synset["t-1"].id == a  # the bigger group keeps the old sense
    assert by_synset["t-2"].id is None
    assert not work.deleted
    assert by_synset["t-2"].translate  # no Uzbek chosen -> two translators


def test_unanswered_and_invalid_labels_leave_rows_where_they_were() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    rows = [_row(a, "one", here="one"), _row(b, "two", here="two")]
    work = _work([le.Sense(id=a, definition_en="A", meaning_uz="a-uz", provisional=True),
                  le.Sense(id=b, definition_en="B", meaning_uz="b-uz", provisional=True)], rows)
    uses = le.build_uses(rows)
    le.plan_senses(work, uses, {"uses": {uses[0].id: "S9"}})  # S9 is not offered

    kept = {s.id: s for s in work.plan if s.row_ids}
    assert set(kept) == {a, b} and not work.deleted
    assert kept[a].definition_en == "A" and kept[a].meaning_uz == "a-uz"
    assert all(not s.provisional for s in work.plan)


def test_a_rerun_moving_rows_off_a_deep_oewn_sense_absorbs_it() -> None:
    deep, top = uuid.uuid4(), uuid.uuid4()
    rows = [_row(deep, "a bank of oars")]
    work = _work([le.Sense(id=top, oewn_synset_id="t-1", oewn_rank=1, meaning_uz="qirg'oq"),
                  le.Sense(id=deep, oewn_synset_id="t-3", oewn_rank=3, meaning_uz="qator")], rows)
    uses = le.build_uses(rows)
    le.plan_senses(work, uses, {"uses": {uses[0].id: "S2"}, "senses": {}})

    assert deep in work.deleted  # absorbed, not left behind with no rows
    assert top in {s.id for s in work.plan}  # a top-2 OEWN sense stays without rows
    moved = next(s for s in work.plan if s.oewn_synset_id == "t-2")
    assert moved.absorbed == [deep] and moved.row_ids == [rows[0].id]


def test_an_english_id_is_never_taken_as_uzbek() -> None:
    a = uuid.uuid4()
    rows = [_row(a, "x", here="The land", uz="qirg'oq")]
    work = _work([le.Sense(id=a, provisional=True)], rows)
    uses = le.build_uses(rows)
    le.plan_senses(work, uses, {"uses": {uses[0].id: "X1"},
                                "senses": {"X1": {"uz": f"{uses[0].id}a", "def": f"{uses[0].id}b"}}})
    sense = next(s for s in work.plan if s.row_ids)
    assert sense.meaning_uz == "" and sense.translate
    assert sense.definition_en != "qirg'oq"


def test_a_one_sentence_paraphrase_is_not_copied_as_the_meaning() -> None:
    a = uuid.uuid4()
    rows = [_row(a, "fifty rowers in each bank", here="a tier of oars", uz="eshkaklar qatori",
                 core="a money place", core_uz="bank")]
    work = _work([le.Sense(id=a, provisional=True)], rows)
    uses = le.build_uses(rows)
    le.plan_senses(work, uses, {"uses": {uses[0].id: "S3"},
                                "senses": {"S3": {"uz": f"{uses[0].id}b"}}})
    sense = next(s for s in work.plan if s.oewn_synset_id == "t-3")
    assert sense.meaning_uz == "" and sense.translate  # refused -> two translators
    # ...but where the passage used the word in its usual sense, it is the meaning.
    rows = [_row(a, "the river bank", here="river side", uz="qirg'oq",
                 core="river side", core_uz="qirg'oq")]
    work = _work([le.Sense(id=a, provisional=True)], rows)
    uses = le.build_uses(rows)
    le.plan_senses(work, uses, {"uses": {uses[0].id: "S1"},
                                "senses": {"S1": {"uz": f"{uses[0].id}b"}}})
    assert next(s for s in work.plan if s.oewn_synset_id == "t-1").meaning_uz == "qirg'oq"


def test_usual_uzbek_is_copied_only_onto_the_sense_it_describes() -> None:
    a = uuid.uuid4()
    rows = [_row(a, "subjects in the trial", here="a person studied", uz="tekshiriluvchi",
                 core="a topic or a citizen", core_uz="mavzu yoki fuqaro")]
    uses = le.build_uses(rows)
    for usual, expected in (("mixed", ""), ("S1", "mavzu yoki fuqaro")):
        work = _work([le.Sense(id=a, provisional=True)], rows)
        le.plan_senses(work, uses, {"uses": {uses[0].id: "S1"}, "usual": {uses[0].id: usual},
                                    "senses": {"S1": {"uz": f"{uses[0].id}d"}}})
        assert next(s for s in work.plan if s.oewn_synset_id == "t-1").meaning_uz == expected


def test_a_lexeme_with_nothing_at_all_is_a_gap() -> None:
    work = _work([], [], oewn=[])
    le.plan_senses(work, [], None)
    assert work.plan == [] and work.needs_gap


def test_a_flat_reply_with_a_dropped_quote_is_repaired() -> None:
    broken = '{\n  "uz": {\n    "k1": "tasvir obyekti",\n    "k2": majbur qilmoq",\n    "k3": fan'
    assert le.parse_json_object(broken) is None
    assert le.repair_flat_map(broken) == {"uz": {"k1": "tasvir obyekti", "k2": "majbur qilmoq",
                                                 "k3": "fan"}}
    assert le.repair_flat_map('{"words": [{"id": "w1"}]}') is None
    assert le.parse_json_object('[{"verdicts": {"k1": "same"}}]') == {"verdicts": {"k1": "same"}}


# --- rank_senses --------------------------------------------------------------


def _s(rank=None, rows=0, definition="d"):
    return le.Sense(id=None, oewn_rank=rank, row_ids=[uuid.uuid4() for _ in range(rows)],
                    definition_en=definition)


def test_material_senses_first_by_rows_then_oewn_order() -> None:
    senses = [_s(None, 1, "m1"), _s(3, 2), _s(1, 0), _s(None, 2, "m2"), _s(2, 0), _s(4, 5)]
    ordered = le.rank_senses(senses)
    assert [(s.oewn_rank, len(s.row_ids)) for s in ordered] == [
        (4, 5), (3, 2), (None, 2), (None, 1), (1, 0), (2, 0)]
    assert [s.sense_rank for s in ordered] == [1, 2, 3, 4, 5, 6]


def test_a_deep_oewn_sense_nobody_uses_is_deleted_and_a_list_only_word_gets_one() -> None:
    top, deep = uuid.uuid4(), uuid.uuid4()
    work = _work([le.Sense(id=top, oewn_synset_id="t-1", oewn_rank=1, meaning_uz="qirg'oq"),
                  le.Sense(id=deep, oewn_synset_id="t-2", oewn_rank=2, meaning_uz="bank")], [])
    le.plan_senses(work, [], None)
    assert [s.id for s in work.plan] == [top]
    assert work.deleted == {deep: None}
    fresh = _work([], [])
    le.plan_senses(fresh, [], None)
    assert [s.oewn_synset_id for s in fresh.plan] == ["t-1"]


# --- review_reasons -----------------------------------------------------------


def test_review_reasons() -> None:
    rr = le.review_reasons
    assert rr(cefr="C1", frequency_band="core", material_levels=[], carried=[], judge=None) == [
        "ngsl_conflict"]
    assert rr(cefr="B2", frequency_band="core", material_levels=[], carried=[], judge=None) == []
    assert rr(cefr="A2", frequency_band="off-list", material_levels=[], carried=[], judge=None) == [
        "ngsl_conflict"]
    assert rr(cefr="A2", frequency_band="common", material_levels=[], carried=[], judge=None) == []
    # >= 2 bands from the majority material level (ties toward the lower).
    assert rr(cefr="C2", frequency_band="wider", material_levels=["B1", "B1", "C1"],
              carried=[], judge=None) == ["material_level_gap"]
    # ...but never below B1: the seed only assigned B1-C1.
    assert rr(cefr="A2", frequency_band="wider", material_levels=["B2", "B2", "C1"],
              carried=[], judge=None) == []
    # ngsl_conflict is about the rank-1 sense only.
    assert rr(cefr="C1", frequency_band="core", material_levels=[], carried=[], judge=None,
              rank=2) == []
    assert rr(cefr="B1", frequency_band="wider", material_levels=["B2", "C1"],
              carried=[], judge=None) == []
    assert rr(cefr="B2", frequency_band="wider", material_levels=[], carried=["lemma_merge"],
              judge="different") == ["lemma_merge", "judge_different"]
    assert rr(cefr="B2", frequency_band="wider", material_levels=[], carried=[],
              judge="garbage") == ["judge_unsure"]
    # Not translated this run: the earlier verdict stands; stale computed ones do not.
    assert rr(cefr="B2", frequency_band="wider", material_levels=[],
              carried=["judge_unsure", "ngsl_conflict"], judge=None) == ["judge_unsure"]
    assert rr(cefr="B2", frequency_band="wider", material_levels=[],
              carried=["judge_unsure"], judge="same") == []


# --- pos_mismatch -------------------------------------------------------------


def test_pos_mismatch_is_flagged_not_moved_and_a_rerun_answer_replaces_it() -> None:
    a = uuid.uuid4()
    rows = [_row(a, "the subject of the talk", here="a topic", uz="mavzu")]
    work = _work([le.Sense(id=a, provisional=True)], rows)
    work.pos = "v"
    uses = le.build_uses(rows)
    le.plan_senses(work, uses, {"uses": {uses[0].id: "X1"},
                                "senses": {"X1": {"uz": f"{uses[0].id}b", "pos": "n"}}})
    sense = next(s for s in work.plan if s.row_ids)
    assert sense.id == a and sense.review_reasons == ["pos_mismatch"]
    assert sense.row_ids == [rows[0].id]  # still on this lexeme
    # A phrase defined as one of its words.
    work = _work([le.Sense(id=a, provisional=True)], rows)
    le.plan_senses(work, uses, {"uses": {uses[0].id: "X1"},
                                "senses": {"X1": {"pos": "n", "wrong_word": True}}})
    assert "pos_mismatch" in next(s for s in work.plan if s.row_ids).review_reasons
    # Re-run: the matcher now says it fits -> the flag goes; no answer -> it stays.
    for info, expected in (({"pos": "n"}, []), (None, ["pos_mismatch"])):
        work = _work([le.Sense(id=a, review_reasons=["pos_mismatch"])], rows)
        senses = {"X1": info} if info else {}
        le.plan_senses(work, uses, {"uses": {uses[0].id: "X1"}, "senses": senses})
        assert next(s for s in work.plan if s.row_ids).review_reasons == expected
    assert not le.pos_mismatch("phr", {"pos": "n"}) and not le.pos_mismatch("n", {"pos": "phr"})


# --- Uzbek style ----------------------------------------------------------------


def test_what_needs_normalising() -> None:
    assert le.looks_like_gloss("qirg'oq, sohil") and le.looks_like_gloss("to'plamoq")
    for text in ("Bahor fasli.", "Mavzu", "pul saqlanadigan muassasa (bank)",
                 "bir necha kishining birgalikda ishlashi uchun mo'ljallangan joy"):
        assert not le.looks_like_gloss(text)


def test_tidying_a_copy_never_touches_its_words() -> None:
    assert le.tidy_copy("Bahor fasli.") == "bahor fasli"
    assert le.tidy_copy("AQSH prezidenti.") == "AQSH prezidenti"
    sense = le.Sense(id=None)
    le.set_copied_uz(sense, "Mutaxassis")
    assert (sense.meaning_uz, sense.meaning_uz_material, sense.normalise) == (
        "mutaxassis", "Mutaxassis", False)


class StyleGemini:
    def __init__(self, short, verdict):
        self.short, self.verdict, self.calls = short, verdict, []

    async def ask(self, model, prompt, *, step, max_tokens=0, repair_flat=False):
        self.calls.append((step, model))
        keys = re.findall(r"^(k\d+):", prompt, re.M)
        if step == "style":
            return {"uz": {k: self.short for k in keys}}
        return {"verdicts": {k: self.verdict for k in keys}}


async def test_a_sentence_copy_is_normalised_only_when_the_meaning_holds() -> None:
    for verdict, expected in (("same", "bahor"), ("different", "bahor fasli")):
        sense = le.Sense(id=None, definition_en="the season of growth")
        le.set_copied_uz(sense, "Bahor fasli.")
        assert sense.normalise
        work = _work([], [])
        work.plan = [sense]
        gemini = StyleGemini("bahor", verdict)
        await le.step_normalise(gemini, [work])
        assert [c[0] for c in gemini.calls] == ["style", "style-check"]
        assert gemini.calls[0][1] != gemini.calls[1][1]  # checked by another model
        assert sense.meaning_uz == expected and sense.meaning_uz_material == "Bahor fasli."
    # A re-run choosing the same material text keeps the normalised form.
    sense = le.Sense(id=None, meaning_uz="bahor", meaning_uz_material="Bahor fasli.")
    le.set_copied_uz(sense, "Bahor fasli.")
    assert sense.meaning_uz == "bahor" and not sense.normalise


# --- End to end, with a scripted model ---------------------------------------


class ScriptedGemini:
    """Answers each step the way the prompt's content says it should:
    'river' uses are S1, 'money' uses S2."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def ask(self, model, prompt, *, step, max_tokens=0, repair_flat=False):
        self.calls.append(step)
        if step == "match":
            uses, senses = {}, {}
            for use_id, example in re.findall(r"^\s+(u\d+): \"(.*)\"$", prompt, re.M):
                label = "S1" if "river" in example else "S2"
                uses[use_id] = label
                senses.setdefault(label, {"pos": "n"})
                if label == "S2":
                    senses["S2"]["uz"] = f"{use_id}b"
            return {"words": [{"id": "w1", "uses": uses, "senses": senses}]}
        keys = re.findall(r"^(k\d+):", prompt, re.M)
        if step == "cefr":
            return {"levels": {k: ("C1" if "sloping" in line else "A1")
                               for k, line in re.findall(r"^(k\d+):(.*)$", prompt, re.M)}}
        if step == "translate":
            word = "qirg'oq" if model == le.MODEL_MAIN else "sohil"
            return {"uz": {k: word for k in keys}}
        if step == "judge":
            return {"verdicts": {k: {"verdict": "different", "better": "b"} for k in keys}}
        return None


async def test_enrich_writes_merges_relinks_and_a_rerun_reuses_everything() -> None:
    tag = uuid.uuid4().hex[:8]
    async with async_session_factory() as session:
        user = User(email=f"lexicon-{tag}@test.local", display_name="lexicon test")
        session.add(user)
        await session.flush()
        material = Material(author_id=user.id, type="reading", title=f"lex {tag}",
                            visibility="private")
        session.add(material)
        await session.flush()
        part = Part(material_id=material.id, order_index=0, title="P",
                    passage={"paragraphs": []}, first_number=1)
        session.add(part)
        lexeme = Lexeme(lemma=f"bank{tag}", pos="n", frequency_band="core",
                        frequency_source="ngsl")
        session.add(lexeme)
        await session.flush()
        a = LexemeSense(lexeme_id=lexeme.id, sense_rank=1, definition_en="money or river",
                        meaning_uz="pul yoki qirg'oq", cefr="B2", review_reasons=["lemma_merge"],
                        needs_review=True)
        b = LexemeSense(lexeme_id=lexeme.id, sense_rank=2, definition_en="a money place",
                        meaning_uz="bank", cefr="B2")
        session.add_all([a, b])
        await session.flush()
        specs = [(a, "the river bank flooded", "qirg'oq"),
                 (a, "money in the bank", "bank muassasasi"),
                 (b, "the bank lends money", "bank")]
        for i, (sense, example, uz) in enumerate(specs):
            session.add(MaterialVocabulary(
                material_id=material.id, part_id=part.id, lemma=f"bank{tag}{i}",
                surface="bank", pos="n", meaning_en=f"meaning {i}", meaning_uz=uz,
                # Ordinary uses: the usual meaning IS the contextual one.
                meaning_core_en=f"meaning {i}", meaning_core_uz=uz,
                example=example, cefr_level="C1", lexeme_id=lexeme.id, sense_id=sense.id,
            ))
        await session.commit()
        ids = dict(lexeme=lexeme.id, a=a.id, b=b.id, material=material.id, part=part.id,
                   user=user.id)

    oewn = {(f"bank{tag}", "n"): OEWN}
    try:
        gemini = ScriptedGemini()
        await le.enrich(async_session_factory, gemini, [ids["lexeme"]], oewn)
        assert gemini.calls.count("translate") == 2 and "judge" in gemini.calls

        async with async_session_factory() as session:
            senses = (await session.exec(select(LexemeSense).where(
                LexemeSense.lexeme_id == ids["lexeme"]))).all()
            rows = (await session.exec(select(MaterialVocabulary).where(
                MaterialVocabulary.lexeme_id == ids["lexeme"]))).all()
            lexeme = await session.get(Lexeme, ids["lexeme"])
        by_synset = {s.oewn_synset_id: s for s in senses}
        assert set(by_synset) == {"t-1", "t-2"}  # b merged away, nothing else added
        assert ids["b"] not in {s.id for s in senses}
        money, river = by_synset["t-2"], by_synset["t-1"]
        assert money.id in (ids["a"], ids["b"]) or river.id in (ids["a"], ids["b"])
        assert {r.sense_id for r in rows if "river" in r.example} == {river.id}
        assert {r.sense_id for r in rows if "money" in r.example} == {money.id}
        assert money.meaning_uz in ("bank muassasasi", "bank") and money.meaning_uz_alt == ""
        assert river.meaning_uz == "qirg'oq" and river.meaning_uz_alt == "sohil"
        assert money.meaning_uz_material == money.meaning_uz and river.meaning_uz_material == ""
        # Two material rows against one: the financial sense leads.
        assert money.sense_rank == 1 and river.sense_rank == 2
        assert lexeme.cefr == "A1" and lexeme.enriched_at is not None
        # C1 on a core word, but not rank 1: no ngsl_conflict.
        assert set(river.review_reasons) == {"judge_different", "lemma_merge"}
        # A1 against C1 rows: below B1, so no gap. lemma_merge is the
        # lexeme's (P1 put it on sense a only here): every sense carries it.
        assert money.review_reasons == ["lemma_merge"]
        assert "lemma_merge" in river.review_reasons
        assert all(s.needs_review == bool(s.review_reasons) for s in senses)
        assert not any(s.provisional for s in senses)
        assert all(s.cefr and s.source_id == "oewn" and s.licence == "cc-by-4.0" for s in senses)

        # Re-run: same senses (ids), same links, nothing re-translated.
        before = {s.id: (s.oewn_synset_id, s.meaning_uz, tuple(s.review_reasons)) for s in senses}
        links = {r.id: r.sense_id for r in rows}
        gemini = ScriptedGemini()
        await le.enrich(async_session_factory, gemini, [ids["lexeme"]], oewn)
        assert "translate" not in gemini.calls
        async with async_session_factory() as session:
            senses = (await session.exec(select(LexemeSense).where(
                LexemeSense.lexeme_id == ids["lexeme"]))).all()
            rows = (await session.exec(select(MaterialVocabulary).where(
                MaterialVocabulary.lexeme_id == ids["lexeme"]))).all()
        assert {s.id: (s.oewn_synset_id, s.meaning_uz, tuple(s.review_reasons))
                for s in senses} == before
        assert {r.id: r.sense_id for r in rows} == links
    finally:
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


async def test_a_merged_sense_repoints_the_saved_words_that_pointed_at_it() -> None:
    """`saved_words.lexeme_sense_id` is NOT NULL (P4): `_absorb`'s own merge
    of two senses into one must not leave a saved word pointing at the row
    about to be deleted, the same obligation it already meets for
    `material_vocabulary.sense_id` and `translation_reports.lexeme_sense_id`.

    Two cases in one test: a plain word (nobody else's) just moves to the
    surviving sense; a learner who had SEPARATELY saved a word for BOTH
    senses collides on `uq_saved_user_lexeme_sense` and the two merge into
    one, contexts combined, the material they shared not duplicated.
    """
    tag = uuid.uuid4().hex[:8]
    async with async_session_factory() as session:
        user_plain = User(email=f"repoint-plain-{tag}@test.local", display_name="p")
        user_collide = User(email=f"repoint-collide-{tag}@test.local", display_name="c")
        session.add_all([user_plain, user_collide])
        await session.flush()
        material_shared = Material(author_id=user_plain.id, type="reading",
                                   title=f"repoint shared {tag}", visibility="private")
        material_only_old = Material(author_id=user_plain.id, type="reading",
                                     title=f"repoint old {tag}", visibility="private")
        session.add_all([material_shared, material_only_old])
        await session.flush()

        lexeme = Lexeme(lemma=f"repoint{tag}", pos="n")
        session.add(lexeme)
        await session.flush()
        old_sense = LexemeSense(lexeme_id=lexeme.id, sense_rank=2,
                                definition_en="old", meaning_uz="eski")
        new_sense = LexemeSense(lexeme_id=lexeme.id, sense_rank=1,
                                definition_en="new", meaning_uz="yangi")
        session.add_all([old_sense, new_sense])
        await session.flush()

        plain_word = SavedWord(
            user_id=user_plain.id, lemma=lexeme.lemma, lexeme_sense_id=old_sense.id
        )
        session.add(plain_word)
        await session.flush()
        session.add(SavedWordContext(
            saved_word_id=plain_word.id, material_id=material_shared.id,
            meaning_en="m", meaning_uz="u",
        ))

        collide_old = SavedWord(
            user_id=user_collide.id, lemma=lexeme.lemma, lexeme_sense_id=old_sense.id
        )
        collide_new = SavedWord(
            user_id=user_collide.id, lemma=lexeme.lemma, lexeme_sense_id=new_sense.id
        )
        session.add_all([collide_old, collide_new])
        await session.flush()
        session.add(SavedWordContext(
            saved_word_id=collide_old.id, material_id=material_shared.id,
            meaning_en="m", meaning_uz="u",
        ))
        session.add(SavedWordContext(
            saved_word_id=collide_old.id, material_id=material_only_old.id,
            meaning_en="m", meaning_uz="u",
        ))
        session.add(SavedWordContext(
            saved_word_id=collide_new.id, material_id=material_shared.id,
            meaning_en="m", meaning_uz="u",
        ))
        await session.commit()

        ids = dict(
            lexeme=lexeme.id, old=old_sense.id, new=new_sense.id,
            plain_word=plain_word.id, collide_old=collide_old.id,
            collide_new=collide_new.id, user_plain=user_plain.id,
            user_collide=user_collide.id, material_shared=material_shared.id,
            material_only_old=material_only_old.id,
        )

    try:
        async with async_session_factory() as session:
            await le._repoint_saved_words(session, ids["old"], ids["new"])
            await session.commit()

        async with async_session_factory() as session:
            plain = await session.get(SavedWord, ids["plain_word"])
            assert plain is not None
            assert plain.lexeme_sense_id == ids["new"]

            # The collision: `collide_old` is gone, absorbed into
            # `collide_new`, which now holds both materials.
            assert await session.get(SavedWord, ids["collide_old"]) is None
            survivor = await session.get(SavedWord, ids["collide_new"])
            assert survivor is not None
            assert survivor.lexeme_sense_id == ids["new"]
            contexts = (
                await session.exec(
                    select(SavedWordContext.material_id).where(
                        SavedWordContext.saved_word_id == survivor.id
                    )
                )
            ).all()
            assert set(contexts) == {ids["material_shared"], ids["material_only_old"]}
    finally:
        async with async_session_factory() as session:
            for word_id in (ids["plain_word"], ids["collide_old"], ids["collide_new"]):
                for ctx in (
                    await session.exec(
                        select(SavedWordContext).where(
                            SavedWordContext.saved_word_id == word_id
                        )
                    )
                ).all():
                    await session.delete(ctx)
            await session.flush()
            for word_id in (ids["plain_word"], ids["collide_old"], ids["collide_new"]):
                word = await session.get(SavedWord, word_id)
                if word is not None:
                    await session.delete(word)
            await session.flush()
            for sense_id in (ids["old"], ids["new"]):
                sense = await session.get(LexemeSense, sense_id)
                if sense is not None:
                    await session.delete(sense)
            await session.flush()
            lexeme = await session.get(Lexeme, ids["lexeme"])
            if lexeme is not None:
                await session.delete(lexeme)
            for material_id in (ids["material_shared"], ids["material_only_old"]):
                material = await session.get(Material, material_id)
                if material is not None:
                    await session.delete(material)
            await session.flush()
            for user_id in (ids["user_plain"], ids["user_collide"]):
                user = await session.get(User, user_id)
                if user is not None:
                    await session.delete(user)
            await session.commit()


async def test_a_merged_sense_repoints_translation_reports_and_merges_open_collisions() -> None:
    """`translation_reports` has a partial unique index -- one OPEN report
    per `(user_id, lexeme_sense_id)` -- so a blind bulk repoint of
    `lexeme_sense_id` onto the survivor, as a merge used to do, can violate
    it the moment one learner has an open report on BOTH senses being
    merged. `_repoint_translation_reports` must handle that collision the
    way `_repoint_saved_words` handles its own: one report survives, the
    other's note is folded in and it is marked resolved rather than left as
    a second open row.

    Three reports in one test: a plain one (nobody else's business) just
    moves to the surviving sense; an already-resolved one moves too, since
    it cannot collide with anything; the OPEN collision is the one that
    would have raised `IntegrityError` before this fix.
    """
    tag = uuid.uuid4().hex[:8]
    async with async_session_factory() as session:
        user_plain = User(email=f"report-plain-{tag}@test.local", display_name="p")
        user_collide = User(email=f"report-collide-{tag}@test.local", display_name="c")
        session.add_all([user_plain, user_collide])
        await session.flush()

        lexeme = Lexeme(lemma=f"reportword{tag}", pos="n")
        session.add(lexeme)
        await session.flush()
        old_sense = LexemeSense(lexeme_id=lexeme.id, sense_rank=2,
                                definition_en="old", meaning_uz="eski")
        new_sense = LexemeSense(lexeme_id=lexeme.id, sense_rank=1,
                                definition_en="new", meaning_uz="yangi")
        session.add_all([old_sense, new_sense])
        await session.flush()

        plain_report = TranslationReport(
            user_id=user_plain.id, lexeme_sense_id=old_sense.id,
            source="word_page", note="plain report", status="open",
        )
        already_resolved = TranslationReport(
            user_id=user_collide.id, lexeme_sense_id=old_sense.id,
            source="word_page", note="already handled", status="resolved",
        )
        collide_old = TranslationReport(
            user_id=user_collide.id, lexeme_sense_id=old_sense.id,
            source="word_page", note="wrong on the old sense", status="open",
        )
        collide_new = TranslationReport(
            user_id=user_collide.id, lexeme_sense_id=new_sense.id,
            source="practice_reveal", note="wrong on the new sense too",
            status="open",
        )
        session.add_all([plain_report, already_resolved, collide_old, collide_new])
        await session.commit()

        ids = dict(
            lexeme=lexeme.id, old=old_sense.id, new=new_sense.id,
            plain_report=plain_report.id, already_resolved=already_resolved.id,
            collide_old=collide_old.id, collide_new=collide_new.id,
            user_plain=user_plain.id, user_collide=user_collide.id,
        )

    try:
        async with async_session_factory() as session:
            await le._repoint_translation_reports(session, ids["old"], ids["new"])
            await session.commit()

        async with async_session_factory() as session:
            plain = await session.get(TranslationReport, ids["plain_report"])
            assert plain is not None
            assert plain.lexeme_sense_id == ids["new"]
            assert plain.status == "open"

            resolved = await session.get(TranslationReport, ids["already_resolved"])
            assert resolved is not None
            assert resolved.lexeme_sense_id == ids["new"]
            assert resolved.status == "resolved"

            # The collision: `collide_old` is resolved AND still repointed
            # to the survivor sense (not left referencing `old`, which is
            # about to be deleted), and never ends up a SECOND open row
            # against `new` beside `collide_new`.
            merged_away = await session.get(TranslationReport, ids["collide_old"])
            assert merged_away is not None
            assert merged_away.status == "resolved"
            assert merged_away.lexeme_sense_id == ids["new"]

            survivor = await session.get(TranslationReport, ids["collide_new"])
            assert survivor is not None
            assert survivor.status == "open"
            assert survivor.lexeme_sense_id == ids["new"]
            assert "wrong on the new sense too" in survivor.note
            assert "wrong on the old sense" in survivor.note

            open_rows = (
                await session.exec(
                    select(TranslationReport).where(
                        TranslationReport.user_id == ids["user_collide"],
                        TranslationReport.lexeme_sense_id == ids["new"],
                        TranslationReport.status == "open",
                    )
                )
            ).all()
            assert len(open_rows) == 1  # the index this fix exists to satisfy
    finally:
        async with async_session_factory() as session:
            for report_id in (
                ids["plain_report"], ids["already_resolved"],
                ids["collide_old"], ids["collide_new"],
            ):
                report = await session.get(TranslationReport, report_id)
                if report is not None:
                    await session.delete(report)
            await session.flush()
            for sense_id in (ids["old"], ids["new"]):
                sense = await session.get(LexemeSense, sense_id)
                if sense is not None:
                    await session.delete(sense)
            await session.flush()
            lexeme = await session.get(Lexeme, ids["lexeme"])
            if lexeme is not None:
                await session.delete(lexeme)
            await session.flush()
            for user_id in (ids["user_plain"], ids["user_collide"]):
                user = await session.get(User, user_id)
                if user is not None:
                    await session.delete(user)
            await session.commit()
