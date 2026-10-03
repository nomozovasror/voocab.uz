"""Word lists: a list is a source, not a store.

Each test builds its OWN lists (`t_<hex>` keys) so real list rows and entries
in the database it runs on never change what is asserted.
"""

import asyncio
import uuid

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func
from sqlmodel import select

from app import worker as worker_module
from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.lexicon import Lexeme, LexemeSense
from app.models.user import User
from app.models.vocabulary import (
    MaterialVocabulary,
    SavedWord,
    SavedWordContext,
    VocabularyReviewLog,
)
from app.models.word_list import UserWordList, WordList, WordListEntry
from app.services import lexicon_enrich as le
from app.services import practice as practice_service
from app.services import word_lists as word_lists_service
from app.services.word_lists_seed import seed_word_lists
from test_vocabulary_practice import (
    _cleanup,
    _make_material,
    _make_part,
    _make_saved_word,
    _make_user,
    _reload,
)

DEFINITION = "a long plain definition that has enough words in it"


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _headers(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token(str(user.id))}"}


class World:
    """Throwaway lists, entries and users; `close()` removes everything."""

    def __init__(self) -> None:
        self.tag = uuid.uuid4().hex[:8]
        self.list_ids: list[uuid.UUID] = []
        self.entry_senses: list[uuid.UUID] = []
        self.lexeme_ids: list[uuid.UUID] = []
        self.user_ids: list[uuid.UUID] = []
        self.material_ids: list[uuid.UUID] = []

    async def user(self, name: str) -> User:
        user = await _make_user(f"wl-{name}-{self.tag}@example.test")
        self.user_ids.append(user.id)
        return user

    async def word_list(self, name: str) -> WordList:
        async with async_session_factory() as session:
            word_list = WordList(
                key=f"t_{name}{self.tag}"[:16], title=f"Test {name}",
                description="why", attribution="credit",
            )
            session.add(word_list)
            await session.commit()
            await session.refresh(word_list)
        self.list_ids.append(word_list.id)
        return word_list

    async def entry(
        self, word_list: WordList, lemma: str, rank: int, *, sense_id=None,
        pos: str = "n", cefr: str | None = "B1",
    ) -> WordListEntry:
        lemma = f"{lemma}{self.tag}"
        async with async_session_factory() as session:
            if sense_id is None:
                lexeme = Lexeme(lemma=lemma, pos=pos)
                session.add(lexeme)
                await session.flush()
                sense = LexemeSense(
                    lexeme_id=lexeme.id, sense_rank=1, definition_en=DEFINITION,
                    meaning_uz="tarjima", cefr=cefr,
                )
                session.add(sense)
                await session.flush()
                sense_id, lexeme_id = sense.id, lexeme.id
                self.lexeme_ids.append(lexeme.id)
            else:
                lexeme_id = (await session.get(LexemeSense, sense_id)).lexeme_id
            entry = WordListEntry(
                list_id=word_list.id, lemma=lemma, rank=rank, lexeme_id=lexeme_id,
                sense_id=sense_id,
            )
            session.add(entry)
            await session.commit()
            await session.refresh(entry)
        return entry

    async def start(self, user: User, word_list: WordList) -> None:
        async with async_session_factory() as session:
            await word_lists_service.start(session, user.id, word_list.key)

    async def close(self) -> None:
        async with async_session_factory() as session:
            await session.exec(
                delete(UserWordList).where(UserWordList.list_id.in_(self.list_ids))
            )
            await session.commit()
        async with async_session_factory() as session:
            # Saved words may point at a list (SET NULL) -- cleaned below.
            await session.exec(
                delete(WordListEntry).where(WordListEntry.list_id.in_(self.list_ids))
            )
            await session.commit()
        await _cleanup(user_ids=self.user_ids, material_ids=self.material_ids)
        async with async_session_factory() as session:
            for lexeme_id in self.lexeme_ids:
                await session.exec(
                    delete(SavedWord).where(
                        SavedWord.lexeme_sense_id.in_(
                            select(LexemeSense.id).where(
                                LexemeSense.lexeme_id == lexeme_id
                            )
                        )
                    )
                )
                await session.exec(
                    delete(LexemeSense).where(LexemeSense.lexeme_id == lexeme_id)
                )
                await session.exec(delete(Lexeme).where(Lexeme.id == lexeme_id))
            await session.exec(delete(WordList).where(WordList.id.in_(self.list_ids)))
            await session.commit()


async def _session_items(user: User) -> list[dict]:
    async with async_session_factory() as session:
        return await practice_service.build_session(session, user, tz=None)


async def _answer(user: User, item_or_ids: dict, given: str = "wrong", **extra) -> dict:
    """Answer an item the way the client does: word_id or list_entry_id."""
    item = item_or_ids
    body = dict(
        direction=item["direction"], exercise_type=item["exercise_type"],
        given=given, elapsed_ms=1000, context_id=None,
    )
    if "word_id" not in extra and "list_entry_id" not in extra:
        if item["word_id"] is not None:
            extra["word_id"] = item["word_id"]
        else:
            extra["list_entry_id"] = item["list_entry_id"]
    body.update(extra)
    async with async_session_factory() as session:
        result = await practice_service.record_answer(session, user, **body)
    assert result is not None
    return result


async def _words(user: User) -> list[SavedWord]:
    async with async_session_factory() as session:
        return list(
            (await session.exec(select(SavedWord).where(SavedWord.user_id == user.id))).all()
        )


# --- Decision 2: subscribing is not adding ------------------------------------


@pytest.mark.asyncio
async def test_starting_a_list_creates_no_saved_word_and_a_shown_card_creates_none():
    world = World()
    try:
        user = await world.user("a")
        word_list = await world.word_list("biz")
        for rank, lemma in enumerate(["alpha", "beta", "gamma"], start=1):
            await world.entry(word_list, lemma, rank)
        async with _client() as client:
            started = await client.post(
                f"/api/vocabulary/lists/{word_list.key}/start", headers=_headers(user)
            )
        assert started.json() == {"active": True, "pending_saved": 0}
        assert await _words(user) == []

        items = await _session_items(user)
        assert [i["list_entry_id"] is not None for i in items] == [True] * 3
        assert all(i["word_id"] is None for i in items)
        assert await _words(user) == []  # shown, not answered
    finally:
        await world.close()


@pytest.mark.asyncio
async def test_first_answer_creates_the_word_with_its_origin_list():
    world = World()
    try:
        user = await world.user("b")
        word_list = await world.word_list("biz")
        entry = await world.entry(word_list, "alpha", 1)
        await world.start(user, word_list)
        item = (await _session_items(user))[0]

        result = await _answer(user, item)
        (word,) = await _words(user)
        assert result["word"]["word_id"] == word.id
        assert word.origin_list_id == word_list.id
        assert word.lexeme_sense_id == entry.sense_id
        assert word.reps == 1 and word.status == "learning"
        async with async_session_factory() as session:
            contexts = (
                await session.exec(
                    select(func.count(SavedWordContext.id)).where(
                        SavedWordContext.saved_word_id == word.id
                    )
                )
            ).one()
        assert contexts == 0
    finally:
        await world.close()


@pytest.mark.asyncio
async def test_known_check_pass_makes_it_known_and_fail_keeps_it_in_rotation():
    world = World()
    try:
        user = await world.user("c")
        word_list = await world.word_list("biz")
        e1 = await world.entry(word_list, "alpha", 1)
        e2 = await world.entry(word_list, "beta", 2)
        await world.start(user, word_list)
        async with async_session_factory() as session:
            check = await practice_service.build_known_check_item(
                session, user, list_entry_id=e1.id
            )
        assert check["list_entry_id"] == e1.id and check["word_id"] is None
        assert await _words(user) == []  # asking creates nothing

        # The answer to a recall gap on a sentence-less word is its lemma.
        passed = await _answer(
            user, check, given=e1.lemma, claim_known=True, list_entry_id=e1.id
        )
        assert passed["known"] is True and passed["status"] == "known"

        failed = await _answer(
            user, check, given="nope", claim_known=True, list_entry_id=e2.id
        )
        assert failed["known"] is False and failed["status"] == "learning"
        assert len(await _words(user)) == 2
    finally:
        await world.close()


@pytest.mark.asyncio
async def test_stopping_keeps_owned_words_and_stops_new_ones():
    world = World()
    try:
        user = await world.user("d")
        word_list = await world.word_list("biz")
        for rank, lemma in enumerate(["alpha", "beta", "gamma"], start=1):
            await world.entry(word_list, lemma, rank)
        await world.start(user, word_list)
        await _answer(user, (await _session_items(user))[0])
        async with _client() as client:
            stopped = await client.post(
                f"/api/vocabulary/lists/{word_list.key}/stop", headers=_headers(user)
            )
            detail = await client.get(
                f"/api/vocabulary/lists/{word_list.key}", headers=_headers(user)
            )
        assert stopped.json() == {"active": False}
        assert detail.json()["started"] is True and detail.json()["active"] is False
        assert detail.json()["owned"] == 1
        assert len(await _words(user)) == 1
        assert [i for i in await _session_items(user) if i["list_entry_id"]] == []
    finally:
        await world.close()


# --- Server-side validation ---------------------------------------------------


@pytest.mark.asyncio
async def test_a_list_answer_is_validated_and_a_refused_one_creates_nothing():
    world = World()
    try:
        user = await world.user("e")
        word_list = await world.word_list("biz")
        entry = await world.entry(word_list, "alpha", 1)
        base = dict(
            direction="passive", exercise_type="recall", given="x", elapsed_ms=1,
            context_id=None,
        )

        async def attempt(**kw):
            async with async_session_factory() as session:
                return await practice_service.record_answer(
                    session, user, **{**base, **kw}
                )

        with pytest.raises(HTTPException) as e403:  # not subscribed
            await attempt(list_entry_id=entry.id)
        assert e403.value.status_code == 403
        with pytest.raises(HTTPException) as e404:
            await attempt(list_entry_id=uuid.uuid4())
        assert e404.value.status_code == 404

        await world.start(user, word_list)
        async with async_session_factory() as session:
            await word_lists_service.stop(session, user.id, word_list.key)
        with pytest.raises(HTTPException) as e403b:  # stopped list
            await attempt(list_entry_id=entry.id)
        assert e403b.value.status_code == 403
        await world.start(user, word_list)

        with pytest.raises(HTTPException) as e422:  # not the ladder's exercise
            await attempt(list_entry_id=entry.id, exercise_type="produce")
        assert e422.value.status_code == 422
        assert await _words(user) == []

        await attempt(list_entry_id=entry.id, exercise_type="recall")
        with pytest.raises(HTTPException) as e409:  # now owned
            await attempt(list_entry_id=entry.id)
        assert e409.value.status_code == 409
        assert len(await _words(user)) == 1

        async with _client() as client:  # exactly one of the two ids
            response = await client.post(
                "/api/vocabulary/practice/answers", headers=_headers(user),
                json={**base, "word_id": str(uuid.uuid4()),
                      "list_entry_id": str(entry.id)},
            )
        assert response.status_code == 422
    finally:
        await world.close()


@pytest.mark.asyncio
async def test_requeue_after_the_first_list_answer_uses_the_word_id():
    world = World()
    try:
        user = await world.user("f")
        word_list = await world.word_list("biz")
        await world.entry(word_list, "alpha", 1)
        await world.start(user, word_list)
        item = (await _session_items(user))[0]
        first = await _answer(user, item, given="wrong")
        assert first["returns_this_session"] is True
        async with async_session_factory() as session:
            second = await practice_service.record_answer(
                session, user, word_id=first["word"]["word_id"], context_id=None,
                direction=item["direction"], exercise_type=item["exercise_type"],
                given="wrong", elapsed_ms=10, requeued=True,
            )
        assert second is not None
        (word,) = await _words(user)
        assert word.reps == 2
    finally:
        await world.close()


# --- Decisions 5 and 8: planning, dedup, progress ------------------------------


@pytest.mark.asyncio
async def test_saved_new_words_come_first_then_lists_round_robin():
    world = World()
    try:
        user = await world.user("g")
        first = await world.word_list("one")
        second = await world.word_list("two")
        for rank, lemma in enumerate(["a1", "a2", "a3", "a4"], start=1):
            await world.entry(first, lemma, rank)
        for rank, lemma in enumerate(["b1", "b2"], start=1):
            await world.entry(second, lemma, rank)
        await _make_saved_word(user.id, f"own{world.tag}")
        await world.start(user, first)
        await world.start(user, second)

        items = await _session_items(user)
        lemmas = [i["lemma"].removesuffix(world.tag) for i in items]
        assert lemmas == ["own", "a1", "b1", "a2", "b2", "a3", "a4"]
        assert items[0]["word_id"] is not None and items[0]["list_entry_id"] is None

        async with async_session_factory() as session:
            picked = await word_lists_service.next_candidates(session, user.id, 4)
        assert [p.lexeme.lemma.removesuffix(world.tag) for p in picked] == [
            "a1", "b1", "a2", "b2",
        ]
    finally:
        await world.close()


@pytest.mark.asyncio
async def test_a_sense_is_offered_once_and_never_if_owned():
    world = World()
    try:
        user = await world.user("h")
        first = await world.word_list("one")
        second = await world.word_list("two")
        shared = await world.entry(first, "shared", 1)
        # The same sense in a second list (lemma suffix differs only by list).
        async with async_session_factory() as session:
            session.add(WordListEntry(
                list_id=second.id, lemma=shared.lemma, rank=1,
                lexeme_id=shared.lexeme_id, sense_id=shared.sense_id,
            ))
            await session.commit()
        owned = await world.entry(first, "owned", 2)
        await world.entry(first, "fresh", 3)
        # Owned through a material save, not through this list.
        await _make_saved_word(user.id, owned.lemma, lexeme_sense_id=owned.sense_id)
        await world.start(user, first)
        await world.start(user, second)

        async with async_session_factory() as session:
            picked = await word_lists_service.next_candidates(session, user.id, 10)
        assert [p.lexeme.lemma.removesuffix(world.tag) for p in picked] == [
            "shared", "fresh",
        ]
        async with _client() as client:
            lists = (await client.get("/api/vocabulary/lists", headers=_headers(user))).json()
        mine = {row["key"]: row for row in lists if row["key"].startswith("t_")}
        assert mine[first.key]["word_count"] == 3 and mine[first.key]["owned"] == 1
    finally:
        await world.close()


@pytest.mark.asyncio
async def test_summary_counts_include_list_candidates():
    world = World()
    try:
        user = await world.user("i")
        word_list = await world.word_list("one")
        for rank, lemma in enumerate(["a1", "a2", "a3"], start=1):
            await world.entry(word_list, lemma, rank)
        async with async_session_factory() as session:
            before = await practice_service.summary(session, user, tz=None)
        await world.start(user, word_list)
        async with async_session_factory() as session:
            after = await practice_service.summary(session, user, tz=None)
        assert after["new_available"] == before["new_available"] + 3
        assert after["planned_new"] == before["planned_new"] + 3
    finally:
        await world.close()


@pytest.mark.asyncio
async def test_users_without_lists_see_no_list_items():
    world = World()
    try:
        user = await world.user("j")
        word_list = await world.word_list("one")
        await world.entry(word_list, "a1", 1)  # exists, but never started
        await _make_saved_word(user.id, f"own{world.tag}")
        items = await _session_items(user)
        assert [i["list_entry_id"] for i in items] == [None]
    finally:
        await world.close()


# --- Decision 6 and the API shapes --------------------------------------------


@pytest.mark.asyncio
async def test_start_reports_pending_saved_words_and_detail_has_the_wire_shape():
    world = World()
    try:
        user = await world.user("k")
        word_list = await world.word_list("one")
        for rank in range(1, 31):
            await world.entry(word_list, f"w{rank}", rank, cefr="B1" if rank % 2 else None)
        await _make_saved_word(user.id, f"own1{world.tag}")
        await _make_saved_word(user.id, f"own2{world.tag}")
        async with _client() as client:
            started = await client.post(
                f"/api/vocabulary/lists/{word_list.key}/start", headers=_headers(user)
            )
            detail = (await client.get(
                f"/api/vocabulary/lists/{word_list.key}", headers=_headers(user)
            )).json()
            missing = await client.get(
                "/api/vocabulary/lists/nope", headers=_headers(user)
            )
        assert started.json() == {"active": True, "pending_saved": 2}
        assert missing.status_code == 404
        assert set(detail) == {
            "key", "title", "description", "word_count", "owned", "active",
            "started", "cefr", "samples", "attribution", "source_title",
            "licence_name", "licence_url", "pending_saved",
        }
        assert detail["word_count"] == 30 and detail["pending_saved"] == 2
        assert detail["cefr"]["B1"] == 15 and detail["cefr"]["unrated"] == 15
        assert len(detail["samples"]) == 12
        assert set(detail["samples"][0]) == {
            "lemma", "pos", "cefr", "definition_en", "meaning_uz"
        }
        assert detail["samples"][0]["lemma"] != detail["samples"][-1]["lemma"]
    finally:
        await world.close()


@pytest.mark.asyncio
async def test_the_five_lists_are_seeded_and_the_seed_is_idempotent():
    async with async_session_factory() as session:
        lists = await seed_word_lists(session)
        again = await seed_word_lists(session)
    assert {"core", "business", "academic", "medical", "toeic"} <= set(lists)
    assert {k: v.id for k, v in lists.items()} == {k: v.id for k, v in again.items()}
    assert lists["business"].attribution == (
        "Based on the Business Service List by Browne, Culligan & Phillips. "
        "CC BY-SA 4.0."
    )


# --- Decision 7: example versus met --------------------------------------------


async def _corpus_row(world: World, entry: WordListEntry, example: str, surface: str):
    author = await world.user("author")
    material = await _make_material(author.id, f"Corpus {world.tag}")
    world.material_ids.append(material.id)
    part = await _make_part(material.id)
    async with async_session_factory() as session:
        session.add(MaterialVocabulary(
            material_id=material.id, part_id=part.id, lemma=entry.lemma,
            surface=surface, pos="n", meaning_en="x", meaning_uz="y",
            example=example, sense_id=entry.sense_id, cefr_level="B1",
        ))
        await session.commit()
    return material


@pytest.mark.asyncio
async def test_a_corpus_example_is_labelled_and_never_written_as_a_context():
    world = World()
    try:
        user = await world.user("l")
        word_list = await world.word_list("one")
        entry = await world.entry(word_list, "share", 1)
        surface = f"shares{world.tag}"
        material = await _corpus_row(
            world, entry, f"The firm will issue {surface} next week.", surface
        )
        await world.start(user, word_list)

        (item,) = await _session_items(user)
        assert item["exercise_type"] == "recall"
        assert item["context_id"] is None
        assert item["prompt"]["kind"] == "sentence"
        assert item["prompt"]["example_source"] == {
            "material_id": material.id, "material_title": material.title,
        }
        assert surface not in item["prompt"]["before"] + item["prompt"]["after"]

        result = await _answer(user, item, given=surface)
        assert result["verdict"] == "correct"  # graded against the same sentence
        assert result["word"]["material_id"] is None
        assert result["word"]["material_title"] == ""
        (word,) = await _words(user)
        async with async_session_factory() as session:
            contexts = (await session.exec(
                select(func.count(SavedWordContext.id)).where(
                    SavedWordContext.saved_word_id == word.id)
            )).one()
            logged = (await session.exec(
                select(VocabularyReviewLog.context_id).where(
                    VocabularyReviewLog.saved_word_id == word.id)
            )).all()
        assert contexts == 0 and logged == [None]
    finally:
        await world.close()


@pytest.mark.asyncio
async def test_a_saved_word_without_its_own_context_gets_the_labelled_example_too():
    world = World()
    try:
        user = await world.user("m")
        word_list = await world.word_list("one")
        entry = await world.entry(word_list, "share", 1)
        surface = f"shares{world.tag}"
        material = await _corpus_row(world, entry, f"We sold {surface} today.", surface)
        await _make_saved_word(user.id, entry.lemma, lexeme_sense_id=entry.sense_id)
        (item,) = await _session_items(user)
        assert item["word_id"] is not None
        assert item["prompt"]["kind"] == "sentence"
        assert item["prompt"]["example_source"]["material_id"] == material.id
    finally:
        await world.close()


@pytest.mark.asyncio
async def test_no_sentence_anywhere_is_the_masked_definition_path():
    world = World()
    try:
        user = await world.user("n")
        word_list = await world.word_list("one")
        await world.entry(word_list, "share", 1)
        await world.start(user, word_list)
        (item,) = await _session_items(user)
        assert item["prompt"]["kind"] == "definition"
        assert item["prompt"].get("example_source") is None
    finally:
        await world.close()


@pytest.mark.asyncio
async def test_a_hidden_corpus_row_is_not_used():
    world = World()
    try:
        user = await world.user("o")
        word_list = await world.word_list("one")
        entry = await world.entry(word_list, "share", 1)
        surface = f"shares{world.tag}"
        await _corpus_row(world, entry, f"We sold {surface} today.", surface)
        async with async_session_factory() as session:
            for row in (await session.exec(
                select(MaterialVocabulary).where(
                    MaterialVocabulary.sense_id == entry.sense_id)
            )).all():
                row.hidden = True
                session.add(row)
            await session.commit()
        await world.start(user, word_list)
        (item,) = await _session_items(user)
        assert item["prompt"]["kind"] == "definition"
    finally:
        await world.close()


# --- re-enrichment must not break what a list points at -----------------------


async def _two_sense_entry(world: World):
    """A lexeme with an OEWN top sense (t-1) and a deep one (t-3, no rows),
    and a list entry pointing at the DEEP one."""
    word_list = await world.word_list("ref")
    entry = await world.entry(word_list, "refword", 1)
    async with async_session_factory() as session:
        top = await session.get(LexemeSense, entry.sense_id)
        top.oewn_synset_id, top.oewn_rank = "t-1", 1
        deep = LexemeSense(
            lexeme_id=top.lexeme_id, sense_rank=2, definition_en=DEFINITION,
            meaning_uz="chuqur", oewn_synset_id="t-3", oewn_rank=3,
        )
        session.add_all([top, deep])
        await session.flush()
        entry_row = await session.get(WordListEntry, entry.id)
        entry_row.sense_id = deep.id
        session.add(entry_row)
        await session.commit()
        return entry.id, top.id, deep.id, top.lexeme_id


@pytest.mark.asyncio
async def test_reenriching_keeps_a_non_top_oewn_sense_a_list_points_at():
    world = World()
    try:
        entry_id, top_id, deep_id, lexeme_id = await _two_sense_entry(world)
        oewn = {(f"refword{world.tag}", "n"): [
            {"synset": "t-1", "rank": 1, "definition": "top"},
            {"synset": "t-2", "rank": 2, "definition": "second"},
            {"synset": "t-3", "rank": 3, "definition": "deep"},
        ]}
        async with async_session_factory() as session:
            works = await le.load_works(session, [lexeme_id], oewn)
        work = works[0]
        assert work.referenced == {deep_id}
        le.plan_senses(work, [], None)
        assert deep_id not in work.deleted
        assert deep_id in {s.id for s in work.plan}
        le.finalise(work)
        async with async_session_factory() as session:
            await le.apply_work(session, work)
            await session.commit()
        async with async_session_factory() as session:
            assert await session.get(LexemeSense, deep_id) is not None
            assert (await session.get(WordListEntry, entry_id)).sense_id == deep_id
    finally:
        await world.close()


@pytest.mark.asyncio
async def test_an_unreferenced_deep_sense_is_still_deleted():
    work = le.LexemeWork(
        id=uuid.uuid4(), lemma="x", pos="n", is_phrase=False, frequency_band=None,
        oewn=[{"synset": "t-1", "rank": 1, "definition": "a"},
              {"synset": "t-3", "rank": 3, "definition": "c"}],
        senses=[le.Sense(id=uuid.uuid4(), oewn_synset_id="t-1", oewn_rank=1, meaning_uz="a"),
                deep := le.Sense(id=uuid.uuid4(), oewn_synset_id="t-3", oewn_rank=3,
                                 meaning_uz="c")],
        rows=[],
    )
    le.plan_senses(work, [], None)
    assert deep.id in work.deleted
    work.referenced = {deep.id}
    work.deleted.clear()
    le.plan_senses(work, [], None)
    assert deep.id not in work.deleted


@pytest.mark.asyncio
async def test_merging_a_sense_repoints_the_list_entries_that_pointed_at_it():
    world = World()
    try:
        entry_id, top_id, deep_id, lexeme_id = await _two_sense_entry(world)
        async with async_session_factory() as session:
            await le._repoint_word_list_entries(session, deep_id, top_id)
            await session.commit()
        async with async_session_factory() as session:
            entry = await session.get(WordListEntry, entry_id)
            assert entry.sense_id == top_id and entry.lexeme_id == lexeme_id
            # Nothing points at the old sense any more: it can be deleted.
            await session.delete(await session.get(LexemeSense, deep_id))
            await session.commit()
    finally:
        await world.close()


@pytest.mark.asyncio
async def test_a_failing_lexeme_is_isolated_backed_off_and_does_not_stall_the_batch(
    monkeypatch: pytest.MonkeyPatch,
):
    from datetime import datetime, timezone

    world = World()
    try:
        word_list = await world.word_list("fail")
        poison = await world.entry(word_list, "poison", 1)
        good = await world.entry(word_list, "goodone", 2)
        async with async_session_factory() as session:
            for entry in (poison, good):
                lexeme = await session.get(Lexeme, entry.lexeme_id)
                lexeme.enriched_at = None
                session.add(lexeme)
            await session.commit()
        mine = {poison.lexeme_id, good.lexeme_id}
        calls: list[list] = []

        async def fake_enrich(session_factory, gemini, ids, oewn):
            calls.append(list(ids))
            if poison.lexeme_id in ids:
                raise RuntimeError("model said no")
            async with session_factory() as session:
                for lexeme_id in ids:
                    if lexeme_id in mine:
                        lexeme = await session.get(Lexeme, lexeme_id)
                        lexeme.enriched_at = datetime.now(timezone.utc)
                        session.add(lexeme)
                await session.commit()
            return []

        monkeypatch.setattr(worker_module.lexicon_enrich_service, "enrich", fake_enrich)
        monkeypatch.setattr(worker_module.settings, "lexicon_enrich_batch_size", 100000)
        worker_module._enrich_failures.clear()

        await worker_module._lexicon_enrich_once(None, {})
        assert poison.lexeme_id in worker_module._enrich_failures
        assert good.lexeme_id not in worker_module._enrich_failures
        async with async_session_factory() as session:
            assert (await session.get(Lexeme, good.lexeme_id)).enriched_at is not None
            assert (await session.get(Lexeme, poison.lexeme_id)).enriched_at is None

        calls.clear()
        await worker_module._lexicon_enrich_once(None, {})
        assert all(poison.lexeme_id not in ids for ids in calls)  # moved on
    finally:
        worker_module._enrich_failures.clear()
        await world.close()


@pytest.mark.asyncio
async def test_with_one_new_slot_a_day_the_lists_take_turns():
    world = World()
    try:
        user = await world.user("rot")
        first = await world.word_list("one")
        second = await world.word_list("two")
        for rank, lemma in enumerate(["a1", "a2", "a3", "a4"], start=1):
            await world.entry(first, lemma, rank)
        for rank, lemma in enumerate(["b1", "b2", "b3", "b4"], start=1):
            await world.entry(second, lemma, rank)
        await world.start(user, first)
        await world.start(user, second)

        seen: list[str] = []
        for _ in range(4):  # four days, one new slot each
            async with async_session_factory() as session:
                (pick,) = await word_lists_service.next_candidates(session, user.id, 1)
            seen.append(pick.lexeme.lemma.removesuffix(world.tag))
            await _answer(user, {
                "direction": "passive", "exercise_type": "recall", "word_id": None,
                "list_entry_id": pick.entry.id,
            })
        assert seen == ["a1", "b1", "a2", "b2"]

        # A list that runs out hands its turns to the other.
        async with async_session_factory() as session:
            await session.exec(
                delete(WordListEntry).where(
                    WordListEntry.list_id == second.id, WordListEntry.rank > 2
                )
            )
            await session.commit()
        async with async_session_factory() as session:
            (pick,) = await word_lists_service.next_candidates(session, user.id, 1)
        assert pick.lexeme.lemma.removesuffix(world.tag) == "a3"
    finally:
        await world.close()


@pytest.mark.asyncio
async def test_concurrent_starts_do_not_race_into_an_error():
    world = World()
    try:
        user = await world.user("race")
        word_list = await world.word_list("biz")
        await world.entry(word_list, "alpha", 1)

        async def one() -> None:
            async with async_session_factory() as session:
                await word_lists_service.start(session, user.id, word_list.key)

        await asyncio.gather(*(one() for _ in range(8)))
        async with async_session_factory() as session:
            rows = (
                await session.exec(
                    select(UserWordList).where(UserWordList.user_id == user.id)
                )
            ).all()
        assert len(rows) == 1 and rows[0].active
    finally:
        await world.close()
