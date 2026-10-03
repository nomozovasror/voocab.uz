"""The live lookup's failure rules: the system's own ignorance is never
handed to the learner as theirs.

The bug these pin: `play` returned "no meaning" because the model correctly
said A1, the parser only accepted B1-C1, and the chain took the refusal for
an answer so the second provider was never asked.
"""

import json
import uuid

import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense
from app.models.material import Material
from app.models.vocabulary import LookupEvent, MaterialVocabulary
from app.services import dictionary as dictionary_service
from app.services import vocabulary as vocabulary_service

from tests.test_vocabulary import (
    _cleanup, _make_passage, _make_user, _Silent, PASSAGE,
)

REPLY = {
    "lemma": "scheme", "term": "", "pos": "n",
    "meaning_core_en": "a plan", "meaning_core_uz": "reja",
    "meaning_en": "a plan", "meaning_uz": "reja",
    "sense_differs": False, "cefr": "A1",
}


def test_an_a1_gloss_is_accepted_and_a_bad_level_is_unusable() -> None:
    gloss = dictionary_service.parse(json.dumps(REPLY))
    assert gloss is not None and gloss.cefr_level == "A1"
    for level in ("A2", "C2"):
        assert dictionary_service.parse(json.dumps({**REPLY, "cefr": level}))
    with pytest.raises(dictionary_service.UnusableReply):
        dictionary_service.parse(json.dumps({**REPLY, "cefr": "D9"}))
    with pytest.raises(dictionary_service.UnusableReply):
        dictionary_service.parse("not json")
    with pytest.raises(dictionary_service.UnusableReply):
        dictionary_service.parse(json.dumps({"lemma": "x"}))
    # Only an explicitly empty lemma means "no meaning".
    assert dictionary_service.parse('{"lemma": ""}') is None


@pytest.mark.asyncio
async def test_an_unusable_reply_moves_on_but_no_meaning_stops_the_chain() -> None:
    class _Garbled:
        name = "garbled"

        async def look_up(self, word: str, context: str):
            return dictionary_service.parse("sorry, I cannot")

    class _Says:
        def __init__(self, reply: str) -> None:
            self.name, self.reply, self.asked = "says", reply, 0

        async def look_up(self, word: str, context: str):
            self.asked += 1
            return dictionary_service.parse(self.reply)

    with pytest.MonkeyPatch.context() as patch:
        gemini = _Says(json.dumps(REPLY))
        patch.setattr(dictionary_service, "providers", lambda: [_Garbled(), gemini])
        found = await dictionary_service.look_up("scheme", "the scheme")
        assert found is not None and gemini.asked == 1

        second = _Says(json.dumps(REPLY))
        patch.setattr(
            dictionary_service, "providers",
            lambda: [_Says('{"lemma": ""}'), second],
        )
        assert await dictionary_service.look_up("Brazil", "in Brazil") is None
        assert second.asked == 0

        patch.setattr(dictionary_service, "providers", lambda: [_Garbled()])
        with pytest.raises(dictionary_service.Unanswered):
            await dictionary_service.look_up("scheme", "the scheme")


class _Easy:
    async def look_up(self, word: str, context: str):
        return dictionary_service.Gloss(
            lemma="scheme", pos="n", meaning_en="a plan",
            meaning_uz="reja", cefr_level="A2",
        )


@pytest.mark.asyncio
async def test_an_easy_word_is_answered_hidden_found_again_and_in_the_tappers_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = f"live-easy-{uuid.uuid4()}@test.local"
    other_email = f"live-easy-o-{uuid.uuid4()}@test.local"
    user, other = await _make_user(email), await _make_user(other_email)
    material, _ = await _make_passage(user.id)
    monkeypatch.setattr(dictionary_service, "providers", lambda: [_Easy()])
    try:
        async with async_session_factory() as session:
            loaded = await session.get(Material, material.id)
            made = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="scheme")
            assert made["word"].meaning_uz == "reja"  # the tapper gets the answer
            row = (await session.exec(select(MaterialVocabulary).where(
                MaterialVocabulary.material_id == material.id,
                MaterialVocabulary.lemma == "scheme"))).one()
            assert row.hidden is True
            assert row.sense_id is not None and row.meaning_core_en == ""

            # A later tap finds it, without asking a model.
            monkeypatch.setattr(dictionary_service, "providers", lambda: [_Silent()])
            again = await vocabulary_service.look_up(
                session, loaded, user_id=other.id, word="scheme")
            assert again["word"] is not None

            # Not on the shared list, but on the tapper's own review.
            shared = await vocabulary_service.entries(session, material.id)
            assert "scheme" not in {e.lemma for e in shared}
            mine = await vocabulary_service.entries_for_reader(
                session, material.id, user.id)
            assert "scheme" in {e.lemma for e in mine}
            # `other` also tapped it, so it is theirs too; a third reader
            # who did not tap it does not get it.
            third = await vocabulary_service.entries_for_reader(
                session, material.id, uuid.uuid4())
            assert "scheme" not in {e.lemma for e in third}
    finally:
        await _cleanup(material.id, email, other_email)


@pytest.mark.asyncio
async def test_when_every_provider_fails_the_lexicon_answers_and_is_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Down:
        name = "down"

        async def look_up(self, word: str, context: str):
            raise RuntimeError("down")

    email = f"live-lex-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    lemma = f"hothouse"  # in PASSAGE; no extracted row for the lemma below
    lexeme_ids: list[uuid.UUID] = []
    async with async_session_factory() as session:
        # Two POS under one lemma; the more-used sense (any POS) must win.
        noun = Lexeme(lemma=lemma, pos="n")
        verb = Lexeme(lemma=lemma, pos="v")
        proper = Lexeme(lemma="vertical", pos="adj", is_proper_noun=True)
        session.add_all([noun, verb, proper])
        await session.flush()
        lexeme_ids = [noun.id, verb.id, proper.id]
        rare = LexemeSense(lexeme_id=noun.id, definition_en="rare use",
                           meaning_uz="kam", cefr="B1", oewn_count=1)
        common = LexemeSense(lexeme_id=verb.id, sense_rank=2,
                             definition_en="common use", meaning_uz="keng",
                             cefr="A2", oewn_count=40)
        session.add_all([rare, common,
                         LexemeSense(lexeme_id=proper.id, definition_en="a name",
                                     meaning_uz="ism", cefr="B1", oewn_count=99)])
        await session.commit()
        common_id = common.id
    monkeypatch.setattr(dictionary_service, "providers", lambda: [_Down(), _Down()])
    try:
        async with async_session_factory() as session:
            loaded = await session.get(Material, material.id)
            made = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word=lemma)
            word = made["word"]
            assert word is not None
            assert (word.meaning_en, word.meaning_uz) == ("common use", "keng")
            assert word.cefr_level == "A2" and word.sense_differs is False
            row = (await session.exec(select(MaterialVocabulary).where(
                MaterialVocabulary.material_id == material.id,
                MaterialVocabulary.lemma == lemma))).one()
            assert row.sense_id == common_id and row.hidden is True  # A2
            event = (await session.exec(select(LookupEvent).where(
                LookupEvent.material_id == material.id))).one()
            assert event.source == "lexicon" and event.found is True

            # A proper noun in the lexicon is never an answer; nothing known
            # means the honest empty answer.
            none = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="vertical")
            assert none["word"] is None
    finally:
        await _cleanup(material.id, email)
        async with async_session_factory() as session:
            for sense in (await session.exec(select(LexemeSense).where(
                    LexemeSense.lexeme_id.in_(lexeme_ids)))).all():
                await session.delete(sense)
            await session.flush()
            for lexeme in (await session.exec(select(Lexeme).where(
                    Lexeme.id.in_(lexeme_ids)))).all():
                await session.delete(lexeme)
            await session.commit()
