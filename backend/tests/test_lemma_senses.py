"""Lookup shows every sense (`app.services.lemma_senses`): order, labels,
`used_here`, POS grouping, the word page's `saved`, exclusions.

`arrange` is pure and tested on in-memory rows; the query and the two
endpoints are tested against the real DB. Lemmas are unique per test.
"""

import uuid

import pytest
from sqlalchemy import event
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense
from app.models.vocabulary import MaterialVocabulary, SavedWord
from app.services import lemma_senses
from app.services.lemma_senses import arrange, label_for, senses_for
from tests.test_vocabulary import (
    PASSAGE,
    _cleanup,
    _client,
    _headers,
    _make_passage,
    _make_user,
)


def _lx(pos: str = "n", **kw) -> Lexeme:
    return Lexeme(lemma="w", pos=pos, **kw)


def _sn(lexeme: Lexeme, name: str, *, rank: int | None = None, count: int | None = None,
        sense_rank: int = 1, uz: str = "x") -> LexemeSense:
    return LexemeSense(
        lexeme_id=lexeme.id, definition_en=name, meaning_uz=uz, sense_rank=sense_rank,
        oewn_rank=rank, oewn_count=count,
    )


def _names(views) -> list[str]:
    return [v.definition_en for v in views]


def test_labels_are_relative_to_the_top_count_and_null_without_data() -> None:
    assert label_for(25, 25) == "most common"
    assert label_for(7, 25) == "common"      # 28% >= 25%
    assert label_for(6, 25) == "less common"  # 24% < 25%
    assert label_for(25 // 4, 25) == "less common"
    assert label_for(0, 25) == "less common"
    assert label_for(None, 25) is None        # a model sense: no label
    assert label_for(0, 0) is None            # nothing tagged: nothing to compare
    assert label_for(5, None) is None


def test_senses_follow_sense_rank_and_labels_still_come_from_counts() -> None:
    # `sense_rank` carries the easiest-first rule (`lexicon.sense_order_key`);
    # the display order is that rank, whatever the SemCor counts say.
    n = _lx()
    a = _sn(n, "ours-first", sense_rank=1)
    b = _sn(n, "semcor-2", rank=2, count=10, sense_rank=2)
    c = _sn(n, "semcor-1", rank=1, count=20, sense_rank=3)
    d = _sn(n, "ours-second", sense_rank=4)
    views = arrange([(n, x) for x in (d, c, b, a)], anchor_lexeme_id=n.id, anchor_sense_id=None)
    assert _names(views) == ["ours-first", "semcor-2", "semcor-1", "ours-second"]
    assert [v.label for v in views] == [None, "common", "most common", None]


def test_within_a_pos_group_senses_order_by_sense_rank_not_count() -> None:
    n = _lx()
    month = _sn(n, "month", rank=3, count=9, sense_rank=2)
    walk = _sn(n, "walk", rank=1, count=0, sense_rank=1)
    demo = _sn(n, "demo", rank=2, count=0, sense_rank=3)
    ours = _sn(n, "ours", sense_rank=4)
    views = arrange([(n, x) for x in (walk, demo, ours, month)],
                    anchor_lexeme_id=n.id, anchor_sense_id=None)
    assert _names(views) == ["walk", "month", "demo", "ours"]
    assert [v.label for v in views] == ["less common", "most common", "less common", None]


def test_used_here_goes_first_overall_and_the_rest_keep_order() -> None:
    n = _lx()
    top = _sn(n, "top", rank=1, count=20)
    rare = _sn(n, "rare", rank=3, count=1)
    mid = _sn(n, "mid", rank=2, count=9)
    views = arrange([(n, x) for x in (top, rare, mid)],
                    anchor_lexeme_id=n.id, anchor_sense_id=rare.id)
    assert _names(views) == ["rare", "top", "mid"]
    assert [v.anchor for v in views] == [True, False, False]
    # The frequency label is still computed; the client shows `used here` instead.
    assert views[0].label == "less common"


def test_no_anchor_sense_means_no_mark_and_plain_order() -> None:
    n = _lx()
    a, b = _sn(n, "a", rank=1, count=3), _sn(n, "b", rank=2, count=3)
    views = arrange([(n, b), (n, a)], anchor_lexeme_id=n.id, anchor_sense_id=uuid.uuid4())
    assert _names(views) == ["a", "b"]
    assert not any(v.anchor for v in views)


def test_the_tapped_pos_group_comes_first_then_the_others() -> None:
    noun, verb = _lx("n"), _lx("v")
    n1 = _sn(noun, "noun-1", rank=1, count=2)
    v1 = _sn(verb, "verb-1", rank=1, count=50)
    n2 = _sn(noun, "noun-2", rank=2, count=1)
    rows = [(noun, n1), (verb, v1), (noun, n2)]
    # Tapped a noun: noun group first even though the verb is far commoner.
    views = arrange(rows, anchor_lexeme_id=noun.id, anchor_sense_id=None)
    assert _names(views) == ["noun-1", "noun-2", "verb-1"]
    assert [v.pos for v in views] == ["n", "n", "v"]
    # Labels compare against the WORD's top count across POS.
    assert [v.label for v in views] == ["less common", "less common", "most common"]
    # Tapped the verb: verb group first.
    assert _names(arrange(rows, anchor_lexeme_id=verb.id, anchor_sense_id=None))[0] == "verb-1"
    # used_here in the other group still beats the group order.
    forced = arrange(rows, anchor_lexeme_id=noun.id, anchor_sense_id=v1.id)
    assert _names(forced) == ["verb-1", "noun-1", "noun-2"]


def test_a_blank_sense_is_not_listed() -> None:
    n = _lx()
    blank = _sn(n, "", uz="")
    assert arrange([(n, blank)], anchor_lexeme_id=n.id, anchor_sense_id=None) == []


async def _seed(lemma: str) -> dict:
    """noun (sense_rank order): a (20) b (6) c (ours); verb: d (rank1,3);
    a proper-noun lexeme and a function-word lexeme under the same lemma."""
    async with async_session_factory() as session:
        noun = Lexeme(lemma=lemma, pos="n")
        verb = Lexeme(lemma=lemma, pos="v")
        adj = Lexeme(lemma=lemma, pos="adj", is_proper_noun=True)
        adv = Lexeme(lemma=lemma, pos="adv", is_function_word=True)
        session.add_all([noun, verb, adj, adv])
        await session.flush()
        senses = {
            "a": LexemeSense(lexeme_id=noun.id, definition_en="a", meaning_uz="A", sense_rank=1,
                             oewn_rank=1, oewn_count=20, cefr="B1"),
            "b": LexemeSense(lexeme_id=noun.id, definition_en="b", meaning_uz="B", sense_rank=2,
                             oewn_rank=2, oewn_count=6),
            "c": LexemeSense(lexeme_id=noun.id, definition_en="c", meaning_uz="C", sense_rank=3),
            "d": LexemeSense(lexeme_id=verb.id, definition_en="d", meaning_uz="D", sense_rank=1,
                             oewn_rank=1, oewn_count=3),
            "p": LexemeSense(lexeme_id=adj.id, definition_en="p", meaning_uz="P"),
            "f": LexemeSense(lexeme_id=adv.id, definition_en="f", meaning_uz="F"),
        }
        session.add_all(senses.values())
        await session.commit()
        return {"noun": noun.id, "verb": verb.id, "senses": {k: v.id for k, v in senses.items()}}


async def _drop(lemma: str) -> None:
    async with async_session_factory() as session:
        for lx in (await session.exec(select(Lexeme).where(Lexeme.lemma == lemma))).all():
            for s in (await session.exec(
                    select(LexemeSense).where(LexemeSense.lexeme_id == lx.id))).all():
                await session.delete(s)
            await session.flush()
            await session.delete(lx)
        await session.commit()


def _lemma() -> str:
    return "lemmasense" + "".join(chr(97 + int(c, 16)) for c in uuid.uuid4().hex[:8])


@pytest.mark.asyncio
async def test_query_orders_labels_and_drops_proper_noun_and_function_word_senses() -> None:
    lemma = _lemma()
    ids = await _seed(lemma)
    try:
        async with async_session_factory() as session:
            (views,) = await senses_for(session, [(ids["noun"], None)])
        # Excluded lexemes' senses (p, f) never appear; labels use top 20.
        assert _names(views) == ["a", "b", "c", "d"]
        assert [v.label for v in views] == ["most common", "common", None, "less common"]
        assert [v.pos for v in views] == ["n", "n", "n", "v"]
        assert views[0].cefr == "B1"
    finally:
        await _drop(lemma)


@pytest.mark.asyncio
async def test_one_query_serves_many_entries() -> None:
    lemma = _lemma()
    ids = await _seed(lemma)
    try:
        async with async_session_factory() as session:
            statements: list[str] = []
            engine = async_session_factory.kw["bind"].sync_engine

            def record(conn, cursor, statement, *rest) -> None:
                statements.append(statement)

            event.listen(engine, "before_cursor_execute", record)
            try:
                out = await senses_for(session, [
                    (ids["noun"], ids["senses"]["b"]), (ids["verb"], None), (None, None),
                ])
            finally:
                event.remove(engine, "before_cursor_execute", record)
        assert len(statements) == 1
        assert _names(out[0])[0] == "b" and out[0][0].anchor
        assert _names(out[1])[0] == "d"
        assert out[2] == []
    finally:
        await _drop(lemma)


@pytest.mark.asyncio
async def test_lookup_response_carries_senses_with_used_here_first() -> None:
    lemma = _lemma()
    ids = await _seed(lemma)
    email = f"lemma-senses-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    try:
        text = PASSAGE["paragraphs"][0]["text"]
        at = text.find("vogue")
        async with async_session_factory() as session:
            row = (await session.exec(select(MaterialVocabulary).where(
                MaterialVocabulary.material_id == material.id,
                MaterialVocabulary.surface == "vogue"))).one()
            row.lemma, row.lexeme_id, row.sense_id = lemma, ids["noun"], ids["senses"]["b"]
            await session.commit()
        async with _client() as client:
            resp = await client.post(
                f"/api/materials/{material.id}/lookups",
                json={"word": "vogue", "paragraph_index": 0, "offset": at},
                headers=_headers(user),
            )
        senses = resp.json()["word"]["senses"]
        assert [s["definition_en"] for s in senses] == ["b", "a", "c", "d"]
        assert [s["used_here"] for s in senses] == [True, False, False, False]
        assert [s["label"] for s in senses] == ["common", "most common", None, "less common"]
        assert set(senses[0]) == {
            "sense_id", "pos", "definition_en", "meaning_uz", "cefr", "label", "used_here"}
    finally:
        await _cleanup(material.id, email)
        await _drop(lemma)


@pytest.mark.asyncio
async def test_word_detail_lists_every_sense_with_the_saved_one_first() -> None:
    lemma = _lemma()
    ids = await _seed(lemma)
    email = f"lemma-senses-detail-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    try:
        async with async_session_factory() as session:
            word = SavedWord(user_id=user.id, lemma=lemma, pos="n",
                             lexeme_sense_id=ids["senses"]["c"])
            session.add(word)
            await session.commit()
            word_id = word.id
        async with _client() as client:
            resp = await client.get(f"/api/vocabulary/words/{word_id}", headers=_headers(user))
        assert resp.status_code == 200
        senses = resp.json()["word"]["senses"]
        assert [s["definition_en"] for s in senses] == ["c", "a", "b", "d"]
        assert [s["saved"] for s in senses] == [True, False, False, False]
        assert "used_here" not in senses[0]
        assert [s["label"] for s in senses] == [None, "most common", "common", "less common"]
    finally:
        await _cleanup(uuid.uuid4(), email)
        await _drop(lemma)
