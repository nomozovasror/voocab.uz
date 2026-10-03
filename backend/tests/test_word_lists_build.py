"""`app.services.word_lists_build` -- the parts that are DECISIONS rather
than model output: list reading, exclusions, the order chain, Core's primary
lexeme, candidate building and answer parsing, and one database run of the
whole build (Core resolved, a domain answer replayed from the log, a skip),
run twice to show the second run changes nothing.

Nothing here calls Gemini. The database run uses its own two `word_lists`
rows and its own source lists, so it never rewrites a real list's entries.
"""

import json
import re
import uuid
from collections import Counter

import pytest
from sqlalchemy import update as sa_update
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense
from app.models.word_list import WordList, WordListEntry
from app.services import word_lists_build as wb
from app.services.word_lists_build import Candidate, LexemeInfo, RankInput, SourceEntry


def _lx(pos: str, *, rows: int = 0, proper: bool = False, function: bool = False,
        lemma: str = "word") -> LexemeInfo:
    return LexemeInfo(id=uuid.uuid4(), lemma=lemma, pos=pos, is_phrase=False,
                      is_proper_noun=proper, is_function_word=function,
                      frequency_band=None, material_rows=rows)


# --- Reading the lists ---------------------------------------------------------


def test_read_list_keeps_word_which_is_an_ngsl_lemma_not_a_header() -> None:
    core = wb.read_list("core")
    assert len(core) == 2809
    assert SourceEntry("word", 217) in core
    assert core[0] == SourceEntry("the", 1)


def test_read_list_nawl_is_the_ranked_957_and_moel_is_unranked_and_deduplicated() -> None:
    nawl = wb.read_list("academic")
    assert len(nawl) == 957 and all(e.list_rank for e in nawl)
    moel = wb.read_list("medical")
    assert len(moel) == 656  # "appetite" appears twice in the workbook
    assert all(e.list_rank is None for e in moel)


def test_read_list_toeic_is_latin1() -> None:
    lemmas = {e.lemma for e in wb.read_list("toeic")}
    assert {"résumé", "café", "ice cream"} <= lemmas


# --- Exclusions ---------------------------------------------------------------


def test_function_words_and_single_letters_are_excluded() -> None:
    assert wb.exclusion_reason("the", []) == "function_word"
    assert wb.exclusion_reason("x", []) == "single_letter"
    assert wb.exclusion_reason("say", []) is None


def test_a_proper_noun_is_excluded_only_when_every_lexeme_is_one() -> None:
    assert wb.exclusion_reason("alan", [_lx("n", proper=True)]) == "proper_noun"
    # `bath` the city beside `bath` the word: the word stays.
    assert wb.exclusion_reason("bath", [_lx("n", proper=True), _lx("n")]) is None
    assert wb.exclusion_reason("unknown", []) is None


# --- Order --------------------------------------------------------------------


def test_list_rank_orders_and_is_renumbered_after_exclusions() -> None:
    ordered = wb.order_entries([RankInput("c", list_rank=40), RankInput("a", list_rank=7),
                                RankInput("b", list_rank=12)])
    assert ordered == [("a", 1, "list"), ("b", 2, "list"), ("c", 3, "list")]


def test_chain_semcor_then_ngsl_then_cefr_with_unrated_last() -> None:
    ordered = wb.order_entries([
        RankInput("zz-unrated"),
        RankInput("aa-c1", cefr="C1"),
        RankInput("mm-a2", cefr="A2"),
        RankInput("ngsl-late", ngsl_rank=2500, cefr="A1"),
        RankInput("ngsl-early", ngsl_rank=900),
        RankInput("rare-tagged", semcor=2),
        RankInput("often-tagged", semcor=40, cefr="C2"),
    ])
    assert [lemma for lemma, _, _ in ordered] == [
        "often-tagged", "rare-tagged", "ngsl-early", "ngsl-late", "mm-a2", "aa-c1", "zz-unrated",
    ]
    assert [source for _, _, source in ordered] == [
        "semcor", "semcor", "ngsl", "ngsl", "cefr", "cefr", "cefr",
    ]
    assert [rank for _, rank, _ in ordered] == list(range(1, 8))


def test_order_is_never_alphabetical_inside_a_band() -> None:
    # Same CEFR: more material rows first, then a single word before a
    # phrase, then the shorter -- the lemma only separates exact ties.
    ordered = wb.order_entries([
        RankInput("abdomen", cefr="B2"),
        RankInput("zinc", cefr="B2", material_rows=3),
        RankInput("acid reflux", cefr="B2"),
        RankInput("ache", cefr="B2"),
    ])
    assert [lemma for lemma, _, _ in ordered] == ["zinc", "ache", "abdomen", "acid reflux"]


def test_list_ranked_entries_come_before_chained_ones() -> None:
    ordered = wb.order_entries([RankInput("chained", semcor=500), RankInput("ranked", list_rank=99)])
    assert ordered[0] == ("ranked", 1, "list")
    assert ordered[1] == ("chained", 2, "semcor")


# --- Core: the primary lexeme -------------------------------------------------


def test_primary_lexeme_is_the_most_semcor_tagged_pos() -> None:
    noun, verb = _lx("n", rows=9), _lx("v")
    chosen = wb.primary_lexeme([noun, verb], {"n": 5, "v": 12}, lambda _id: True)
    assert chosen is verb


def test_primary_lexeme_tie_goes_to_most_material_rows_then_pos_order() -> None:
    noun, verb = _lx("n", rows=1), _lx("v", rows=4)
    assert wb.primary_lexeme([noun, verb], {}, lambda _id: True) is verb
    noun, verb = _lx("n"), _lx("v")
    assert wb.primary_lexeme([verb, noun], {}, lambda _id: True) is noun


def test_primary_lexeme_skips_flagged_and_senseless_lexemes() -> None:
    name, empty, word = _lx("n", proper=True), _lx("v"), _lx("adj")
    chosen = wb.primary_lexeme([name, empty, word], {"n": 99, "v": 50},
                               lambda lexeme_id: lexeme_id != empty.id)
    assert chosen is word
    assert wb.primary_lexeme([name], {"n": 1}, lambda _id: True) is None


# --- Domain choice: candidates and answers ------------------------------------


def _view_with(lemma: str, pos: str, senses: list[tuple[str, str | None]]) -> wb.LexiconView:
    view = wb.LexiconView()
    lexeme = _lx(pos, lemma=lemma)
    view.add_lexeme(lexeme)
    for rank, (definition, synset) in enumerate(senses, 1):
        view.add_sense(wb.SenseInfo(id=uuid.uuid4(), lexeme_id=lexeme.id, sense_rank=rank,
                                    definition_en=definition, oewn_synset_id=synset,
                                    cefr="B1", source_id="oewn" if synset else "model"))
    return view


OEWN = {
    ("discharge", "n"): [{"synset": "s-n1", "rank": 1, "definition": "the sudden giving off of energy", "count": 13},
                         {"synset": "s-n2", "rank": 2, "definition": "a substance that is emitted", "count": 1}],
    ("discharge", "v"): [{"synset": "s-v1", "rank": 1, "definition": "complete or carry out", "count": 3}],
}


def test_candidates_span_every_pos_and_join_held_senses() -> None:
    view = _view_with("discharge", "n", [("the sudden giving off of energy", "s-n1"),
                                         ("a release of a patient from hospital", None)])
    cands = wb.build_candidates("discharge", OEWN, ["n", "v"], view)
    assert [c.cid for c in cands] == ["c1", "c2", "c3", "c4"]
    assert [(c.pos, c.synset) for c in cands] == [("n", "s-n1"), ("n", "s-n2"),
                                                  ("n", None), ("v", "s-v1")]
    held = [c for c in cands if c.sense_id]
    assert [c.definition for c in held] == ["the sudden giving off of energy",
                                            "a release of a patient from hospital"]
    text = wb.render_item("w1", "discharge", cands)
    assert "c1 (n) the sudden giving off of energy *" in text
    assert "c2 (n) a substance that is emitted\n" in text


def test_parse_choice_shapes() -> None:
    held = uuid.uuid4()
    cands = [Candidate("c1", "n", "a held oewn sense", "s-1", 1, held),
             Candidate("c2", "v", "an unheld oewn sense", "s-2", 4, None),
             Candidate("c3", "n", "our own sense", None, None, uuid.uuid4())]
    oewn_held = wb.parse_choice("c1", cands)
    assert oewn_held.type == "oewn" and oewn_held.synset == "s-1" and oewn_held.sense_id == held
    unheld = wb.parse_choice({"choice": "C2"}, cands)
    assert unheld.type == "oewn" and unheld.pos == "v" and unheld.oewn_rank == 4
    assert wb.parse_choice("c3", cands).type == "sense"
    model = wb.parse_choice({"choice": "none", "pos": "n", "def": "the release of a patient."},
                            cands)
    assert model.type == "model" and model.definition == "the release of a patient"
    assert wb.parse_choice({"choice": "skip", "why": "name"}, cands).type == "skip"
    for bad in ("c9", {"choice": "none", "pos": "prefix", "def": "d"}, {"choice": "none", "pos": "n"},
                None, 3, {"choice": ""}):
        assert wb.parse_choice(bad, cands) is None


def test_decision_round_trips_through_the_log(tmp_path) -> None:
    path = tmp_path / "decisions.jsonl"
    log = wb.DecisionLog(path)
    decision = wb.Decision(type="oewn", pos="n", synset="s-2", oewn_rank=2,
                           definition="a substance", sense_id=uuid.uuid4())
    log.put_choice("medical", "discharge", decision, "m")
    log.put_sense("discharge|n|oewn:s-2", {"cefr": "B2", "meaning_uz": "ajralma"})
    again = wb.DecisionLog(path)
    assert again.choices[("medical", "discharge")] == decision
    assert again.senses["discharge|n|oewn:s-2"]["meaning_uz"] == "ajralma"


# --- The 31K frequency table -----------------------------------------------------


def test_read_sfi31k_keeps_the_higher_of_a_doubled_lemma() -> None:
    sfi = wb.read_sfi31k()
    assert len(sfi) == 31239  # 31 240 rows, `criteria` twice
    assert sfi["criteria"] == 55.669788304799049
    assert sfi["the"] > sfi["abdomen"] > 0
    assert "i" in sfi and "achilles tendon" not in sfi  # single lemmas only


def test_sfi31k_orders_an_unranked_list_before_the_chain() -> None:
    ordered = wb.order_entries([
        RankInput("tagged-phrase", semcor=500, cefr="A1"),
        RankInput("rare-word", sfi31k=30.5),
        RankInput("common-word", sfi31k=61.2, cefr="C2"),
        RankInput("unrated"),
    ])
    assert ordered == [("common-word", 1, "sfi31k"), ("rare-word", 2, "sfi31k"),
                       ("tagged-phrase", 3, "semcor"), ("unrated", 4, "cefr")]


# --- Core: the most SemCor-tagged synset ---------------------------------------


def _core_view(lemma: str, lexemes: dict[str, list[tuple[str, str | None]]],
               flagged: tuple[str, ...] = ()) -> wb.LexiconView:
    view = wb.LexiconView()
    for pos, senses in lexemes.items():
        lexeme = _lx(pos, lemma=lemma, proper=pos in flagged)
        view.add_lexeme(lexeme)
        for rank, (definition, synset) in enumerate(senses, 1):
            view.add_sense(wb.SenseInfo(id=uuid.uuid4(), lexeme_id=lexeme.id, sense_rank=rank,
                                        definition_en=definition, oewn_synset_id=synset,
                                        cefr="B1", source_id="oewn" if synset else "model"))
    return view


CORE_OEWN = {
    ("good", "n"): [{"synset": "g-n1", "rank": 1, "definition": "benefit", "count": 26}],
    ("good", "adj"): [{"synset": "g-a1", "rank": 1, "definition": "having desirable qualities",
                       "count": 256}],
    ("tie", "n"): [{"synset": "t-n1", "rank": 1, "definition": "a neckwear", "count": 0}],
    ("tie", "v"): [{"synset": "t-v1", "rank": 1, "definition": "fasten", "count": 0}],
}


def _by_pos():
    return wb.semcor_by_pos(CORE_OEWN)


def test_core_takes_the_most_tagged_synset_across_pos_even_without_its_lexeme() -> None:
    view = _core_view("good", {"n": [("goods for sale", None)]})
    decision, how, candidates = wb.core_decision(
        "good", CORE_OEWN, {"good": ["n", "adj"]}, view, _by_pos())
    assert how == "semcor-top" and not candidates
    assert (decision.type, decision.pos, decision.synset, decision.sense_id) == (
        "oewn", "adj", "g-a1", None)


def test_core_joins_the_held_sense_when_the_lexicon_has_the_synset() -> None:
    view = _core_view("good", {"adj": [("a material sense", None), ("having", "g-a1")]})
    decision, _, _ = wb.core_decision("good", CORE_OEWN, {"good": ["n", "adj"]}, view,
                                      _by_pos())
    held = view.senses_of[view.by_lemma["good"][0].id][1]
    assert decision.sense_id == held.id


def test_core_asks_the_model_only_when_semcor_cannot_choose() -> None:
    view = _core_view("tie", {"v": [("fasten", "t-v1")]})
    decision, how, candidates = wb.core_decision(
        "tie", CORE_OEWN, {"tie": ["n", "v"]}, view, wb.semcor_by_pos(CORE_OEWN))
    assert decision is None and how == ""
    assert [(c.pos, c.synset, bool(c.sense_id)) for c in candidates] == [
        ("n", "t-n1", False), ("v", "t-v1", True)]
    picked, used = wb.core_pick(candidates, wb.Decision(type="oewn", pos="v", synset="t-v1",
                                                        oewn_rank=1, definition="fasten"),
                                "tie", view)
    assert used and picked.synset == "t-v1"
    fallback, used = wb.core_pick(candidates, wb.Decision(type="skip"), "tie", view)
    assert not used and fallback.synset == "t-n1"  # POS_PRIORITY tie order


def test_core_falls_back_to_rank1_when_oewn_lacks_the_lemma_or_the_pos_is_a_name() -> None:
    view = _core_view("whereas", {"conj": [("while on the contrary", None)]})
    decision, how, _ = wb.core_decision("whereas", CORE_OEWN, {}, view, {})
    assert how == "rank1-fallback" and decision.type == "sense"
    assert decision.sense_id == view.senses_of[view.by_lemma["whereas"][0].id][0].id
    named = _core_view("good", {"adj": [("a name", None)], "n": [("benefit", "g-n1")]},
                       flagged=("adj",))
    decision, how, _ = wb.core_decision("good", CORE_OEWN, {"good": ["n", "adj"]}, named,
                                        _by_pos())
    assert how == "rank1-fallback" and decision.definition == "benefit"


def test_core_full_menu_answer_must_be_a_teachable_sense() -> None:
    view = _core_view("till", {"prep": [("up to the time of", None)], "n": [("a name", None)]},
                      flagged=("n",))
    ours = view.senses_of[view.by_lemma["till"][0].id][0]
    named = view.senses_of[view.by_lemma["till"][1].id][0]
    usable = wb.core_full_answer_usable
    assert usable(wb.Decision(type="sense", pos="prep", sense_id=ours.id), "till", view)
    assert not usable(wb.Decision(type="sense", pos="n", sense_id=named.id), "till", view)
    assert usable(wb.Decision(type="model", pos="conj", definition="until"), "till", view)
    assert usable(wb.Decision(type="oewn", pos="v", synset="s", oewn_rank=1), "till", view)
    # A new sense in the pos a name holds would break `(lemma, pos)`.
    assert not usable(wb.Decision(type="oewn", pos="n", synset="s", oewn_rank=1), "till", view)
    assert not usable(wb.Decision(type="skip", why="name"), "till", view)
    assert not usable(None, "till", view)


# --- One build against the database --------------------------------------------


async def _make(lemma: str, pos: str, senses: list[dict], **kwargs) -> Lexeme:
    async with async_session_factory() as session:
        lexeme = Lexeme(lemma=lemma, pos=pos, **kwargs)
        session.add(lexeme)
        await session.flush()
        for rank, fields in enumerate(senses, 1):
            session.add(LexemeSense(lexeme_id=lexeme.id, sense_rank=rank, provisional=False,
                                    **fields))
        await session.commit()
        await session.refresh(lexeme)
        return lexeme


async def _entries(list_id: uuid.UUID) -> list[WordListEntry]:
    async with async_session_factory() as session:
        return list((await session.exec(
            select(WordListEntry).where(WordListEntry.list_id == list_id)
            .order_by(WordListEntry.rank))).all())


async def _cleanup(list_ids: list[uuid.UUID], lemmas: list[str]) -> None:
    async with async_session_factory() as session:
        for list_id in list_ids:
            word_list = await session.get(WordList, list_id)
            if word_list is not None:
                await session.delete(word_list)
        await session.flush()
        lexemes = (await session.exec(select(Lexeme).where(Lexeme.lemma.in_(lemmas)))).all()
        for lexeme in lexemes:
            for sense in (await session.exec(
                    select(LexemeSense).where(LexemeSense.lexeme_id == lexeme.id))).all():
                await session.delete(sense)
        await session.flush()
        for lexeme in lexemes:
            await session.delete(lexeme)
        await session.commit()


@pytest.mark.asyncio
async def test_build_resolves_core_replays_a_domain_answer_and_is_idempotent(tmp_path) -> None:
    tag = uuid.uuid4().hex[:8]
    word, name, chained, domain, skipped, goodish = (f"wlt{tag}{x}" for x in "abcdef")
    lemmas = [word, name, chained, domain, skipped, goodish]

    # `word`: SemCor's most-tagged synset is a verb sense the lexicon holds
    # at rank 2 -- Core takes THAT, not the verb's rank-1 sense, and not the
    # noun the lexicon created first.
    noun = await _make(word, "n", [{"definition_en": "a noun sense", "cefr": "A2"}])
    verb = await _make(word, "v", [
        {"definition_en": "the verb's first sense", "cefr": "B1"},
        {"definition_en": "y", "cefr": "C1", "oewn_synset_id": f"{tag}-w2", "source_id": "oewn"}])
    await _make(name, "n", [{"definition_en": "a person"}], is_proper_noun=True)
    # `chained`: OEWN does not know it -- the old rule (rank 1) stands.
    await _make(chained, "n", [{"definition_en": "something", "cefr": "B2"}])
    await _make(domain, "n", [{"definition_en": "the everyday sense", "cefr": "A2",
                               "oewn_synset_id": f"{tag}-n1", "source_id": "oewn"}])
    # `goodish`: the lexicon only has the noun ("goods"); SemCor says the
    # adjective -- a new lexeme and sense, graded/translated from the log.
    goods = await _make(goodish, "n", [{"definition_en": "articles of commerce", "cefr": "B1"}])
    oewn = {
        (word, "n"): [{"synset": f"{tag}-w1", "rank": 1, "definition": "x", "count": 2}],
        (word, "v"): [{"synset": f"{tag}-w2", "rank": 1, "definition": "y", "count": 30}],
        (domain, "n"): [{"synset": f"{tag}-n1", "rank": 1, "definition": "the everyday sense",
                         "count": 4}],
        (domain, "adj"): [{"synset": f"{tag}-a1", "rank": 1, "definition": "the domain sense",
                           "count": 0}],
        (goodish, "n"): [{"synset": f"{tag}-g1", "rank": 1, "definition": "articles of commerce",
                          "count": 1}],
        (goodish, "adj"): [{"synset": f"{tag}-g2", "rank": 1, "definition": "having good qualities",
                            "count": 40}],
    }

    async with async_session_factory() as session:
        core_list = WordList(key=f"c{tag}", title="test core")
        domain_list = WordList(key=f"b{tag}", title="test business")
        session.add_all([core_list, domain_list])
        await session.commit()
        await session.refresh(core_list)
        await session.refresh(domain_list)
    sources = {
        "core": [SourceEntry("the", 1), SourceEntry(name, 2), SourceEntry(chained, 9),
                 SourceEntry(word, 5), SourceEntry(goodish, 7)],
        "business": [SourceEntry(domain, 3), SourceEntry(skipped, 1)],
    }

    # The model's answers, as a dry run would have logged them: the domain
    # lemma means its adjective sense (no lexeme in that pos yet); the other
    # is a name.
    path = tmp_path / "decisions.jsonl"
    log = wb.DecisionLog(path)
    pick = wb.Decision(type="oewn", pos="adj", synset=f"{tag}-a1", oewn_rank=1,
                       definition="the domain sense")
    log.put_choice("business", domain, pick, "test")
    log.put_choice("business", skipped, wb.Decision(type="skip", why="name"), "test")
    log.put_sense(wb.new_sense_key(domain, pick), {
        "definition_en": "the domain sense", "cefr": "B2", "meaning_uz": "soha ma'nosi",
        "meaning_uz_alt": "soha", "judge": "same"})
    # Core's own new sense: only its grade/translation are model output (the
    # choice is SemCor's), so only that is in the log beforehand.
    adj = wb.Decision(type="oewn", pos="adj", synset=f"{tag}-g2", oewn_rank=1,
                      definition="having good qualities")
    log.put_sense(wb.new_sense_key(goodish, adj), {
        "definition_en": "having good qualities", "cefr": "A1", "meaning_uz": "yaxshi",
        "meaning_uz_alt": "yaxshi, a'lo", "judge": "same"})

    options = wb.BuildOptions(lists=("core", "business"), no_model=True, unit=10)
    word_lists = {"core": core_list, "business": domain_list}
    try:
        report, rank_sources = await wb.build(async_session_factory, None, options,
                                              wb.DecisionLog(path), oewn,
                                              sources=sources, word_lists=word_lists, sfi31k={})
        core = await _entries(core_list.id)
        assert [(e.lemma, e.rank, e.rank_source) for e in core] == [
            (word, 1, "list"), (goodish, 2, "list"), (chained, 3, "list")]
        verb_senses = await _reload_senses(verb.id)
        assert core[0].lexeme_id == verb.id and core[0].sense_id == verb_senses[1].id
        assert core[0].lexeme_id != noun.id
        async with async_session_factory() as session:
            good_sense = await session.get(LexemeSense, core[1].sense_id)
            good_lexeme = await session.get(Lexeme, core[1].lexeme_id)
        assert (good_lexeme.lemma, good_lexeme.pos) == (goodish, "adj")
        assert good_lexeme.id != goods.id and good_lexeme.enriched_at is not None
        assert (good_sense.oewn_synset_id, good_sense.meaning_uz, good_sense.cefr) == (
            f"{tag}-g2", "yaxshi", "A1")
        chained_rank1 = (await _reload_senses(core[2].lexeme_id))[0]
        assert core[2].sense_id == chained_rank1.id
        assert dict(report.excluded["core"]) == {"function_word": 1, "proper_noun": 1}
        assert report.core_how == {"semcor-top": 2, "rank1-fallback": 1}
        logged = wb.DecisionLog(path)
        assert logged.deciders[("core", word)] == "semcor-top"
        assert logged.deciders[("core", chained)] == "rank1-fallback"
        assert logged.choices[("core", goodish)].synset == f"{tag}-g2"

        business = await _entries(domain_list.id)
        assert [e.lemma for e in business] == [domain]
        entry = business[0]
        async with async_session_factory() as session:
            sense = await session.get(LexemeSense, entry.sense_id)
            lexeme = await session.get(Lexeme, entry.lexeme_id)
        assert (lexeme.lemma, lexeme.pos) == (domain, "adj")
        assert lexeme.enriched_at is not None and lexeme.cefr == "B2"
        assert sense.source_id == "oewn" and sense.licence == "cc-by-4.0"
        assert sense.oewn_synset_id == f"{tag}-a1" and sense.oewn_rank == 1
        assert (sense.meaning_uz, sense.meaning_uz_alt, sense.cefr) == ("soha ma'nosi", "soha", "B2")
        assert not sense.provisional and sense.review_reasons == []
        assert report.new_senses == {"oewn": 2} and report.new_lexemes == 2
        assert report.new_by_list == {"core": 1, "business": 1}
        assert report.excluded["business"]["skip:name"] == 1
        assert rank_sources["business"] == {"list": 1}

        # Second run: nothing to decide, nothing created, nothing moved.
        before = {(e.lemma, e.id, e.sense_id, e.rank) for e in core + business}
        report2, _ = await wb.build(async_session_factory, None, options,
                                    wb.DecisionLog(path), oewn,
                                    sources=sources, word_lists=word_lists, sfi31k={})
        after = {(e.lemma, e.id, e.sense_id, e.rank)
                 for e in await _entries(core_list.id) + await _entries(domain_list.id)}
        assert after == before
        assert not report2.new_senses and report2.new_lexemes == 0
        assert report2.asked_choices == 0 and report2.replayed_choices == 0
        async with async_session_factory() as session:
            count = len((await session.exec(select(Lexeme).where(Lexeme.lemma == domain))).all())
        assert count == 2

        # A lemma leaving the list leaves the list.
        sources["core"] = [SourceEntry(word, 5)]
        await wb.build(async_session_factory, None, wb.BuildOptions(lists=("core",), no_model=True),
                       wb.DecisionLog(None), oewn, sources=sources, word_lists=word_lists,
                       sfi31k={})
        assert [e.lemma for e in await _entries(core_list.id)] == [word]
    finally:
        await _cleanup([core_list.id, domain_list.id], lemmas)


async def _reload_senses(lexeme_id: uuid.UUID) -> list[LexemeSense]:
    async with async_session_factory() as session:
        return list((await session.exec(
            select(LexemeSense).where(LexemeSense.lexeme_id == lexeme_id)
            .order_by(LexemeSense.sense_rank))).all())


@pytest.mark.asyncio
async def test_without_a_model_an_unlogged_domain_entry_stays_unresolved(tmp_path) -> None:
    tag = uuid.uuid4().hex[:8]
    lemma = f"wlt{tag}z"
    await _make(lemma, "n", [{"definition_en": "a sense", "cefr": "B1"}])
    async with async_session_factory() as session:
        domain_list = WordList(key=f"m{tag}", title="test medical")
        session.add(domain_list)
        await session.commit()
        await session.refresh(domain_list)
    try:
        report, rank_sources = await wb.build(
            async_session_factory, None, wb.BuildOptions(lists=("medical",), no_model=True),
            wb.DecisionLog(tmp_path / "empty.jsonl"), {},
            sources={"medical": [SourceEntry(lemma, None)]},
            word_lists={"medical": domain_list}, sfi31k={})
        entries = await _entries(domain_list.id)
        assert [(e.lemma, e.sense_id, e.rank_source) for e in entries] == [(lemma, None, "cefr")]
        assert report.unresolved["medical"] == [lemma]
        assert not (tmp_path / "empty.jsonl").exists()  # nothing was asked, nothing logged
        assert json.dumps(dict(rank_sources["medical"])) == '{"cefr": 1}'
    finally:
        await _cleanup([domain_list.id], [lemma])


@pytest.mark.asyncio
async def test_a_failed_commit_leaves_no_phantom_sense_for_later_units(
    tmp_path, monkeypatch
) -> None:
    tag = uuid.uuid4().hex[:8]
    domain = f"wlf{tag}"
    oewn = {(domain, "adj"): [{"synset": f"{tag}-a1", "rank": 1, "definition": "the sense",
                               "count": 0}]}
    async with async_session_factory() as session:
        first = WordList(key=f"b{tag}", title="test business")
        second = WordList(key=f"a{tag}", title="test academic")
        session.add_all([first, second])
        await session.commit()
        await session.refresh(first)
        await session.refresh(second)
    pick = wb.Decision(type="oewn", pos="adj", synset=f"{tag}-a1", oewn_rank=1,
                       definition="the sense")
    log = wb.DecisionLog(tmp_path / "decisions.jsonl")
    for key in ("business", "academic"):
        log.put_choice(key, domain, pick, "test")
    log.put_sense(wb.new_sense_key(domain, pick), {
        "definition_en": "the sense", "cefr": "B2", "meaning_uz": "ma'no",
        "meaning_uz_alt": "m", "judge": "same"})

    real_write = wb.write_new_sense
    failed: list[int] = []

    async def failing_write(session, view, item, report):
        info = await real_write(session, view, item, report)
        if not failed:
            failed.append(1)
            real_commit = session.commit

            async def boom():
                raise RuntimeError("commit failed")

            session.commit = boom  # type: ignore[method-assign]
        return info

    monkeypatch.setattr(wb, "write_new_sense", failing_write)
    options = wb.BuildOptions(lists=("business", "academic"), no_model=True, unit=1,
                              concurrency=1)
    try:
        report, _ = await wb.build(
            async_session_factory, None, options, log, oewn,
            sources={"business": [SourceEntry(domain, 1)], "academic": [SourceEntry(domain, 1)]},
            word_lists={"business": first, "academic": second})
        assert len(report.failures) == 1
        entries = await _entries(first.id) + await _entries(second.id)
        resolved = [e for e in entries if e.sense_id is not None]
        assert len(resolved) == 1
        async with async_session_factory() as session:
            sense = await session.get(LexemeSense, resolved[0].sense_id)
            lexemes = (await session.exec(select(Lexeme).where(Lexeme.lemma == domain))).all()
        assert sense is not None and len(lexemes) == 1
    finally:
        await _cleanup([first.id, second.id], [domain])


class _ScriptedChooser:
    """Stands in for Gemini on the chooser prompt only: answers each headword
    by ``first[lemma]`` the first time it is asked and ``second[lemma]`` the
    next, given the menu it was shown as ``[(cid, pos, definition, held)]``."""

    def __init__(self, first: dict, second: dict) -> None:
        self.first, self.second = first, second
        self.asked: Counter = Counter()
        self.calls = 0

    async def ask(self, model, prompt, *, step, max_tokens=0, **_):
        self.calls += 1
        blocks: list[tuple[str, str, list]] = []
        for line in prompt.splitlines():
            head = re.match(r"^(w\d+)  (.+)$", line)
            cand = re.match(r"^  (c\d+) \((\w+)\) (.*?)( \*)?$", line)
            if head:
                blocks.append((head.group(1), head.group(2), []))
            elif cand and blocks:
                blocks[-1][2].append((cand.group(1), cand.group(2), cand.group(3),
                                      bool(cand.group(4))))
        choices = {}
        for word_id, lemma, menu in blocks:
            policy = self.first if self.asked[lemma] == 0 else self.second
            self.asked[lemma] += 1
            choices[word_id] = policy[lemma](menu)
        return {"choices": choices}


@pytest.mark.asyncio
async def test_core_asks_the_full_menu_when_the_model_declines_the_top_senses(tmp_path) -> None:
    tag = uuid.uuid4().hex[:8]
    conj, tie, picked = (f"wlc{tag}{x}" for x in "abc")
    # All three: SemCor cannot choose between n and v (no counts).
    oewn = {}
    for lemma in (conj, tie, picked):
        oewn[(lemma, "n")] = [{"synset": f"{lemma}-n", "rank": 1, "definition": "a noun thing",
                               "count": 0}]
        oewn[(lemma, "v")] = [{"synset": f"{lemma}-v", "rank": 1, "definition": "do a verb thing",
                               "count": 0}]
    # `conj` (think `till`): its everyday meaning is neither top sense, but
    # ours -- the full menu finds it. `tie`: declines both menus, so the tie
    # order (n first) -- held, so nothing new is written. `picked`: the
    # model takes the verb's top sense from the first menu.
    until = await _make(conj, "prep", [{"definition_en": "up to the time of", "cefr": "A2"}])
    tie_n = await _make(tie, "n", [{"definition_en": "a noun thing", "cefr": "B1",
                                    "oewn_synset_id": f"{tie}-n", "source_id": "oewn"}])
    picked_v = await _make(picked, "v", [{"definition_en": "do a verb thing", "cefr": "B1",
                                          "oewn_synset_id": f"{picked}-v", "source_id": "oewn"}])
    none = lambda menu: {"choice": "none", "pos": "conj", "def": "until"}  # noqa: E731
    chooser = _ScriptedChooser(
        first={conj: none, tie: none,
               picked: lambda menu: next(c for c, pos, *_ in menu if pos == "v")},
        second={conj: lambda menu: next(c for c, _, d, held in menu
                                        if held and d == "up to the time of"),
                tie: lambda menu: {"choice": "skip", "why": "not a word"}},
    )
    async with async_session_factory() as session:
        core_list = WordList(key=f"k{tag}", title="test core")
        session.add(core_list)
        await session.commit()
        await session.refresh(core_list)
    path = tmp_path / "decisions.jsonl"
    sources = {"core": [SourceEntry(conj, 1), SourceEntry(tie, 2), SourceEntry(picked, 3)]}
    try:
        report, _ = await wb.build(
            async_session_factory, chooser, wb.BuildOptions(lists=("core",), model="fake"),
            wb.DecisionLog(path), oewn, sources=sources, word_lists={"core": core_list},
            sfi31k={})
        entries = {e.lemma: e for e in await _entries(core_list.id)}
        assert entries[conj].sense_id == (await _reload_senses(until.id))[0].id
        assert entries[tie].sense_id == (await _reload_senses(tie_n.id))[0].id
        assert entries[picked].sense_id == (await _reload_senses(picked_v.id))[0].id
        assert chooser.calls == 2  # one first menu for all three, one full menu for two
        assert report.asked_choices == 5 and not report.new_senses
        logged = wb.DecisionLog(path)
        assert logged.deciders[("core", conj)] == "fake:all-senses"
        assert logged.deciders[("core", tie)] == "tie-order"
        assert logged.deciders[("core", picked)] == "fake"

        # Replayed: the log answers everything, the model is not asked.
        async with async_session_factory() as session:
            await session.execute(sa_update(WordListEntry).where(
                WordListEntry.list_id == core_list.id).values(lexeme_id=None, sense_id=None))
            await session.commit()
        again = _ScriptedChooser(first={}, second={})
        report2, _ = await wb.build(
            async_session_factory, again, wb.BuildOptions(lists=("core",), model="fake"),
            wb.DecisionLog(path), oewn, sources=sources, word_lists={"core": core_list},
            sfi31k={})
        assert again.calls == 0 and report2.replayed_choices == 3
        assert {e.lemma: e.sense_id for e in await _entries(core_list.id)} == {
            lemma: e.sense_id for lemma, e in entries.items()}
    finally:
        await _cleanup([core_list.id], [conj, tie, picked])
