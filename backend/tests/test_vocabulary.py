"""Integration tests for a passage's vocabulary, against a real DB and the app.

What is worth testing here is everything that is a DECISION rather than a
query:

* the four-step search finds the word somebody tapped -- by span, by surface,
  by lemma, and by reducing an inflected form against this material's own
  lemmas -- with no lemmatiser on this side of the fence;
* a tap inside a phrase's span returns the PHRASE as well as the word, which
  is the whole of how ``give rise to`` is recognised;
* the whole list is refused until the paper has been submitted, because a
  list endpoint open mid-paper would make the browser's budget of three a
  formality;
* saving is deduplicated by lemma across materials and by material within a
  lemma -- one word, two contexts, two meanings;
* a re-extraction replaces what the pipeline wrote and keeps what a person
  edited, which is the entire reason ``source`` exists;
* the words a candidate looked up survive the submit and come back on the
  review;
* a lookup from the REVIEW page is answered like any other and filed apart,
  because "this word stopped me mid-paper" and "I read past this word and
  found out afterwards that I had not understood it" are two different
  facts and only the second says the extraction's filter is wrong.

Nothing here calls Groq. The live-generation path is exercised by swapping
the provider, because a test that depends on somebody's API being up is a
test that fails for reasons that are not about this code.
"""

import uuid

import httpx
import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.attempt import Attempt, AttemptStatus
from app.models.lexicon import Lexeme, LexemeSense, TranslationReport
from app.models.material import Material
from app.models.part import Part
from app.models.user import User
from app.models.vocabulary import (
    LookupEvent,
    MaterialVocabulary,
    SavedWord,
    SavedWordContext,
    VocabularyReviewLog,
)
from app.services import dictionary as dictionary_service
from app.services import vocabulary as vocabulary_service

PASSAGE = {
    "paragraphs": [
        {
            "label": "A",
            "text": (
                "The proponents of vertical farming give rise to a claim that "
                "hothouse produce has long been in vogue."
            ),
        },
        {
            "label": "B",
            "text": "Undertaken carefully, the scheme accommodates two hectares.",
        },
    ],
    "subtitle": None,
    "source": None,
}

#: Offsets checked against the text above rather than counted by eye: the
#: fixture asserts they slice back to the right words before anything else
#: runs, so a typo in the passage fails loudly instead of quietly making a
#: lookup test pass for the wrong reason.
ENTRIES = [
    {"lemma": "proponent", "surface": "proponents", "pos": "n",
     "meaning_en": "somebody who argues for an idea",
     "meaning_uz": "tarafdor", "index": 0, "cefr_level": "C1",
     "frequency_band": "off-list", "is_phrase": False},
    {"lemma": "give rise to", "surface": "give rise to", "pos": "phr",
     "meaning_en": "to cause something to happen",
     "meaning_uz": "sabab bo'lmoq", "index": 0, "cefr_level": "B2",
     "frequency_band": "core", "is_phrase": True},
    {"lemma": "vogue", "surface": "vogue", "pos": "n",
     "meaning_en": "popular fashion at a particular time",
     "meaning_uz": "moda", "index": 0, "cefr_level": "C1",
     "frequency_band": "off-list", "is_phrase": False},
    {"lemma": "undertake", "surface": "Undertaken", "pos": "v",
     "meaning_en": "to begin a piece of work",
     "meaning_uz": "zimmasiga olmoq", "index": 1, "cefr_level": "B2",
     "frequency_band": "common", "is_phrase": False},
    {"lemma": "hectare", "surface": "hectares", "pos": "n",
     "meaning_en": "a unit of area, ten thousand square metres",
     "meaning_uz": "gektar", "index": 1, "cefr_level": "B2",
     "frequency_band": "off-list", "is_phrase": False},
    # A common word doing something unexpected: `scheme` here is the plan,
    # which is the everyday sense -- but `claim` in paragraph A is a noun
    # meaning an assertion rather than a demand, and that is the shape the
    # third question looks for. NGSL-frequent, rated hard.
    {"lemma": "claim", "surface": "claim", "pos": "n",
     "meaning_core_en": "a demand for something you have a right to",
     "meaning_core_uz": "talab",
     "meaning_en": "a statement that something is true, without proof",
     "meaning_uz": "da'vo, tasdiq", "index": 0, "cefr_level": "C1",
     "frequency_band": "core", "is_phrase": False, "unusual": True,
     "sense_differs": True},
]


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _headers(user: User) -> dict:
    return {"Cookie": f"access_token={create_access_token(str(user.id))}"}


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Vocab test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_passage(author_id: uuid.UUID) -> tuple[Material, Part]:
    """A public reading material with the fixture passage and its glosses.

    Offsets are FOUND rather than written down, exactly the way
    `seed/read_vocabulary.py` finds a phrase's: a test carrying hand-counted
    character positions is a test that breaks when somebody fixes a typo in
    the passage, and breaks in a way that looks like a bug in the lookup.
    """
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id,
            type="reading",
            title=f"Vocabulary fixture {uuid.uuid4()}",
            visibility="public",
        )
        session.add(material)
        await session.flush()
        part = Part(
            material_id=material.id, order_index=0,
            title="Reading Passage 1", passage=PASSAGE, first_number=1,
        )
        session.add(part)
        await session.flush()

        for entry in ENTRIES:
            text = PASSAGE["paragraphs"][entry["index"]]["text"]
            at = text.find(entry["surface"])
            assert at >= 0, f"{entry['surface']!r} is not in the fixture passage"
            session.add(
                MaterialVocabulary(
                    material_id=material.id, part_id=part.id,
                    lemma=entry["lemma"], surface=entry["surface"],
                    pos=entry["pos"],
                    meaning_core_en=entry.get("meaning_core_en", ""),
                    meaning_core_uz=entry.get("meaning_core_uz", ""),
                    meaning_en=entry["meaning_en"],
                    meaning_uz=entry["meaning_uz"],
                    sense_differs=bool(entry.get("sense_differs")),
                    example=text, paragraph_index=entry["index"],
                    offset_start=at, offset_end=at + len(entry["surface"]),
                    cefr_level=entry["cefr_level"],
                    frequency_band=entry["frequency_band"],
                    is_phrase=entry["is_phrase"],
                    unusual=bool(entry.get("unusual")),
                )
            )
        await session.commit()
        await session.refresh(material)
        await session.refresh(part)
        return material, part


async def _submit_something(material_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """A finished attempt, so the caller may see the whole list."""
    async with async_session_factory() as session:
        session.add(
            Attempt(
                user_id=user_id, material_id=material_id,
                status=AttemptStatus.SUBMITTED, score=0, total_questions=0,
            )
        )
        await session.commit()


async def _cleanup(material_id: uuid.UUID, *emails: str) -> None:
    async with async_session_factory() as session:
        for model, column in (
            (LookupEvent, LookupEvent.material_id),
            (SavedWordContext, SavedWordContext.material_id),
            (MaterialVocabulary, MaterialVocabulary.material_id),
            (Attempt, Attempt.material_id),
        ):
            for row in (
                await session.exec(select(model).where(column == material_id))
            ).all():
                await session.delete(row)
        await session.flush()
        for part in (
            await session.exec(select(Part).where(Part.material_id == material_id))
        ).all():
            await session.delete(part)
        material = await session.get(Material, material_id)
        if material is not None:
            await session.delete(material)
        await session.commit()

        for email in emails:
            user = (await session.exec(select(User).where(User.email == email))).first()
            if user is None:
                continue
            for word in (
                await session.exec(
                    select(SavedWord).where(SavedWord.user_id == user.id)
                )
            ).all():
                for context in (
                    await session.exec(
                        select(SavedWordContext).where(
                            SavedWordContext.saved_word_id == word.id
                        )
                    )
                ).all():
                    await session.delete(context)
                await session.flush()
                await session.delete(word)
            await session.flush()
            await session.delete(user)
        await session.commit()


class _Silent:
    """A dictionary that knows nothing, for the tests that must not call one."""

    async def look_up(self, word: str, context: str):
        return None


@pytest.mark.asyncio
async def test_a_tapped_word_is_found_four_different_ways() -> None:
    email = f"vocab-find-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    try:
        async with async_session_factory() as session:
            loaded = await session.get(Material, material.id)
            text = PASSAGE["paragraphs"][0]["text"]

            # 1. By where they tapped: the offset falls inside `vogue`.
            at = text.find("vogue")
            by_span = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="vogue", paragraph_index=0, offset=at + 2
            )
            assert by_span["word"].lemma == "vogue"

            # 2. By the surface form, which is what stands in the passage.
            by_surface = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="Undertaken"
            )
            assert by_surface["word"].lemma == "undertake"

            # 3. By the lemma itself.
            by_lemma = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="proponent"
            )
            assert by_lemma["word"].lemma == "proponent"

            # 4. By reduction: `hectares` is stored as its own surface, but a
            #    reader who taps a form the passage does not print still has
            #    to land somewhere. `proponents` reduces to `proponent`.
            by_reduction = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="Proponents,"
            )
            assert by_reduction["word"].lemma == "proponent"
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_tapping_inside_a_phrase_returns_the_phrase_as_well(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The brief's rule, exactly: does the tapped offset fall inside some
    ``is_phrase`` entry's span. `rise` is one of the commonest words in
    English and no frequency filter would ever offer it -- `give rise to` is
    what actually stopped the reader.

    The dictionary is silenced, and that is not decoration. `rise` has no
    entry of its own, so the lookup goes on to ask a model about it -- and
    a model asked about `rise` in this sentence quite correctly answers
    "this is part of `give rise to`", which is the term rule doing its job
    and has nothing to do with what this test is checking.
    """
    email = f"vocab-phrase-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    monkeypatch.setattr(dictionary_service, "providers", lambda: [_Silent()])
    try:
        async with async_session_factory() as session:
            loaded = await session.get(Material, material.id)
            text = PASSAGE["paragraphs"][0]["text"]
            inside = text.find("rise")
            assert text.find("give rise to") < inside < text.find("give rise to") + 12

            found = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="rise", paragraph_index=0, offset=inside
            )
            assert found["phrase"].lemma == "give rise to"
            assert found["phrase"].is_phrase is True
            # And its span slices back to the words it claims, which is the
            # property every offset in this feature has to have.
            phrase = found["phrase"]
            assert (
                text[phrase.offset_start : phrase.offset_end] == "give rise to"
            )
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_the_whole_list_opens_only_once_the_paper_is_finished() -> None:
    reader = f"vocab-gate-{uuid.uuid4()}@test.local"
    writer = f"vocab-author-{uuid.uuid4()}@test.local"
    user = await _make_user(reader)
    author = await _make_user(writer)
    material, _ = await _make_passage(author.id)
    try:
        async with _client() as client:
            refused = await client.get(
                f"/api/materials/{material.id}/vocabulary", headers=_headers(user)
            )
            assert refused.status_code == 403

            # One word at a time is always allowed: that is what the take
            # screen asks, and the budget around it lives in the browser.
            one = await client.post(
                f"/api/materials/{material.id}/lookups",
                json={"word": "vogue"},
                headers=_headers(user),
            )
            assert one.status_code == 200
            assert one.json()["word"]["meaning_uz"] == "moda"

            await _submit_something(material.id, user.id)
            opened = await client.get(
                f"/api/materials/{material.id}/vocabulary", headers=_headers(user)
            )
            assert opened.status_code == 200
            body = opened.json()
            assert body["total"] == len(ENTRIES)
            assert body["levels"] == {"B1": 0, "B2": 3, "C1": 3}
            # The one figure neither measure reports on its own: a word the
            # frequency lists call easy and the model calls C1.
            assert body["unusual"] == 1

            # The author never had to sit their own paper.
            theirs = await client.get(
                f"/api/materials/{material.id}/vocabulary",
                headers=_headers(author),
            )
            assert theirs.status_code == 200
    finally:
        await _cleanup(material.id, reader, writer)


@pytest.mark.asyncio
async def test_frequency_band_never_reaches_the_client() -> None:
    """It is the figure the difficulty arithmetic reads, and it means nothing
    to a learner. `cefr_level` is the one that travels."""
    email = f"vocab-band-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    try:
        async with _client() as client:
            found = await client.post(
                f"/api/materials/{material.id}/lookups",
                json={"word": "vogue"},
                headers=_headers(user),
            )
            assert "frequency_band" not in found.text
            assert found.json()["word"]["cefr_level"] == "C1"
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_one_word_met_twice_is_one_word_with_two_contexts() -> None:
    email = f"vocab-save-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    first, _ = await _make_passage(user.id)
    second, _ = await _make_passage(user.id)
    try:
        async with _client() as client:
            for material in (first, second):
                saved = await client.post(
                    "/api/vocabulary/words",
                    json={"material_id": str(material.id), "lemmas": ["vogue"]},
                    headers=_headers(user),
                )
                assert saved.status_code == 201

            # Pressing save twice on the same page is one word met once.
            again = await client.post(
                "/api/vocabulary/words",
                json={"material_id": str(first.id), "lemmas": ["vogue"]},
                headers=_headers(user),
            )
            assert again.status_code == 201

            listed = await client.get(
                "/api/vocabulary/words", headers=_headers(user)
            )
            words = listed.json()["words"]
            assert [word["lemma"] for word in words] == ["vogue"]
            assert len(words[0]["contexts"]) == 2
            assert {context["material_title"] for context in words[0]["contexts"]} == {
                first.title,
                second.title,
            }

            gone = await client.delete(
                f"/api/vocabulary/words/{words[0]['id']}", headers=_headers(user)
            )
            assert gone.status_code == 204
            assert (
                await client.get("/api/vocabulary/words", headers=_headers(user))
            ).json()["total"] == 0
    finally:
        # The material that does NOT carry the user away first: deleting the
        # user while a second material still names them as its author is a
        # foreign key violation, and the test would then fail for a reason
        # that has nothing to do with saving words.
        await _cleanup(second.id)
        await _cleanup(first.id, email)


@pytest.mark.asyncio
async def test_a_re_extraction_keeps_what_a_person_edited() -> None:
    """The entire reason the ``source`` column exists from the first day.

    A re-run that silently reverted a correction would be discovered by the
    person who made it, months later, with no way to tell what happened."""
    email = f"vocab-source-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, part = await _make_passage(user.id)
    try:
        async with async_session_factory() as session:
            edited = (
                await session.exec(
                    select(MaterialVocabulary).where(
                        MaterialVocabulary.material_id == material.id,
                        MaterialVocabulary.lemma == "vogue",
                    )
                )
            ).one()
            edited.meaning_uz = "urf, moda"
            edited.source = "author_edited"
            session.add(edited)
            await session.commit()

        async with async_session_factory() as session:
            written, kept = await vocabulary_service.replace_extracted(
                session,
                material_id=material.id,
                part_id=part.id,
                rows=[
                    {"lemma": "vogue", "surface": "vogue", "meaning_en": "x",
                     "meaning_uz": "MACHINE", "index": 0, "start": 0, "end": 5,
                     "cefr_level": "B1"},
                    {"lemma": "hothouse", "surface": "hothouse",
                     "meaning_en": "a heated glass building",
                     "meaning_uz": "issiqxona", "index": 0, "start": 0,
                     "end": 8, "cefr_level": "B2"},
                    # The same lemma twice in one passage, which really
                    # happens: the filter offers `descending` and `descent`
                    # as two candidates and the model answers `descend` for
                    # both. The first wins; the second must not reach the
                    # unique constraint, whose answer would be to fail the
                    # whole import of the passage over one repeated word.
                    {"lemma": "hothouse", "surface": "hothouses",
                     "meaning_en": "a second reading of the same word",
                     "meaning_uz": "takror", "index": 1, "start": 0,
                     "end": 9, "cefr_level": "C1"},
                ],
            )
            await session.commit()
            assert (written, kept) == (1, 1)

        async with async_session_factory() as session:
            rows = await vocabulary_service.entries(session, material.id)
            by_lemma = {row.lemma: row for row in rows}
            # The person's wording survived; the pipeline's replacement for
            # it was refused rather than written beside it.
            assert by_lemma["vogue"].meaning_uz == "urf, moda"
            assert by_lemma["vogue"].source == "author_edited"
            # The first reading of `hothouse` is the one that survived.
            assert by_lemma["hothouse"].surface == "hothouse"
            # And everything the pipeline had written before is gone, not
            # accumulated: only the new extraction and the kept edit remain.
            assert set(by_lemma) == {"vogue", "hothouse"}
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_word_nothing_has_glossed_is_an_ordinary_empty_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A name, a number, or a morning the dictionary is unreachable. The
    panel says so; nothing 500s and nothing is invented."""
    email = f"vocab-empty-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    monkeypatch.setattr(dictionary_service, "providers", lambda: [_Silent()])
    try:
        async with _client() as client:
            found = await client.post(
                f"/api/materials/{material.id}/lookups",
                json={"word": "carefully"},
                headers=_headers(user),
            )
            assert found.status_code == 200
            assert found.json() == {"word": None, "phrase": None}
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_generated_gloss_is_kept_for_the_next_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The list grows towards what readers actually find hard, which is a
    better list than any frequency table can describe."""

    class _Knows:
        async def look_up(self, word: str, context: str):
            assert "hothouse" in context, "the paragraph has to travel with the word"
            return dictionary_service.Gloss(
                lemma="scheme", pos="n",
                meaning_en="a plan for doing something",
                meaning_uz="reja", cefr_level="B2",
            )

    email = f"vocab-live-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    monkeypatch.setattr(dictionary_service, "providers", lambda: [_Knows()])
    try:
        async with async_session_factory() as session:
            loaded = await session.get(Material, material.id)
            # Paragraph B holds `scheme`; paragraph A is searched too, which
            # is what lets a client that sent no position still be answered.
            made = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="hothouse"
            )
            assert made["word"].lemma == "scheme"
            assert made["word"].source == "extracted"
            # The surface is the passage's own spelling, and its offsets
            # slice back to it. The search is case-insensitive, so storing
            # the query instead would leave the one field that makes the
            # offsets checkable disagreeing with the text.
            entry = made["word"]
            text = PASSAGE["paragraphs"][entry.paragraph_index]["text"]
            assert (
                text[entry.offset_start : entry.offset_end] == entry.surface
            )
            # No frequency list on this side of the fence, and a guess here
            # would put a made-up figure into the column the difficulty
            # arithmetic reads.
            assert made["word"].frequency_band == ""

        # Asking again does not ask the model again.
        monkeypatch.setattr(dictionary_service, "providers", lambda: [_Silent()])
        async with async_session_factory() as session:
            loaded = await session.get(Material, material.id)
            again = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="scheme"
            )
            assert again["word"].meaning_uz == "reja"
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_every_lookup_is_logged_including_the_ones_that_find_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The log is written from the first day because every question it will
    be asked is about the past.

    `source` is the column that cannot be recovered later: a live answer is
    saved into `material_vocabulary` and becomes indistinguishable from an
    extracted one within milliseconds.
    """
    email = f"vocab-log-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    monkeypatch.setattr(dictionary_service, "providers", lambda: [_Silent()])
    try:
        async with _client() as client:
            # Served from the extraction.
            await client.post(
                f"/api/materials/{material.id}/lookups",
                json={"word": "vogue", "paragraph_index": 0, "offset": 100},
                headers=_headers(user),
            )
            # Nothing extracted and nothing generated: a word the dictionary
            # cannot gloss. Logged all the same — the failures are the half
            # that says whether the extraction's cut is in the right place.
            await client.post(
                f"/api/materials/{material.id}/lookups",
                json={"word": "carefully"},
                headers=_headers(user),
            )

        async with async_session_factory() as session:
            events = (
                await session.exec(
                    select(LookupEvent)
                    .where(LookupEvent.material_id == material.id)
                    .order_by(LookupEvent.created_at)
                )
            ).all()
            assert len(events) == 2
            cached, missed = events

            assert cached.source == "cache"
            assert cached.found is True
            assert cached.lemma == "vogue"
            assert cached.asked == "vogue"
            assert (cached.paragraph_index, cached.offset) == (0, 100)

            assert missed.source == "live"
            assert missed.found is False
            assert missed.lemma == ""
            assert missed.asked == "carefully"

            # Nothing belongs to a sitting yet: no attempt exists while a
            # paper is open.
            assert {event.attempt_id for event in events} == {None}
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_submitting_claims_the_lookups_made_while_the_paper_was_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What stays unclaimed is a passage somebody looked words up in and
    never finished — a fact worth counting, not a gap to apologise for."""
    email = f"vocab-claim-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    monkeypatch.setattr(dictionary_service, "providers", lambda: [_Silent()])
    try:
        async with _client() as client:
            await client.post(
                f"/api/materials/{material.id}/lookups",
                json={"word": "proponent"},
                headers=_headers(user),
            )
            submitted = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={"answers": [], "looked_up": ["proponent"]},
                headers=_headers(user),
            )
            assert submitted.status_code == 200
            attempt_id = uuid.UUID(submitted.json()["attempt_id"])

        async with async_session_factory() as session:
            events = (
                await session.exec(
                    select(LookupEvent).where(
                        LookupEvent.material_id == material.id
                    )
                )
            ).all()
            assert [event.attempt_id for event in events] == [attempt_id]
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_one_provider_being_down_does_not_repeal_the_rule() -> None:
    """Any word a learner selects is answered — and that cannot rest on one
    API.

    Not hypothetical: the seed run hit Groq's spend limit at the 174th
    passage, and every live lookup in the app began returning nothing for
    ordinary words, to readers with no way to know why. One outage had
    quietly repealed the feature's first rule.
    """

    class _Down:
        name = "down"

        async def look_up(self, word: str, context: str):
            raise RuntimeError("spend limit reached")

    class _Up:
        name = "up"

        async def look_up(self, word: str, context: str):
            return dictionary_service.Gloss(
                lemma="scheme", pos="n", meaning_en="a plan",
                meaning_uz="reja", cefr_level="B2",
            )

    class _Refuses:
        name = "refuses"

        async def look_up(self, word: str, context: str):
            return None

    with pytest.MonkeyPatch.context() as patch:
        # A provider that RAISES is out of action, so the next one answers.
        patch.setattr(dictionary_service, "providers", lambda: [_Down(), _Up()])
        found = await dictionary_service.look_up("scheme", "the scheme here")
        assert found is not None
        assert found.lemma == "scheme"

        # A provider that RETURNS NOTHING has answered: it read the
        # paragraph and there is no meaning to give. Asking the next model
        # the same question about the same name spends a request to be told
        # the same thing — and a chain that shops around for a non-empty
        # answer is no longer a chain, it is a vote.
        patch.setattr(
            dictionary_service, "providers", lambda: [_Refuses(), _Up()]
        )
        assert await dictionary_service.look_up("Brazil", "larger than Brazil") is None

        # Every one down is the only case the reader ever sees, and it is
        # reported as ours rather than as a fact about a list.
        # raised as `Unanswered`, never returned as `None`: "we do not know"
        # must not be mistakable for "there is no meaning".
        patch.setattr(dictionary_service, "providers", lambda: [_Down(), _Down()])
        with pytest.raises(dictionary_service.Unanswered):
            await dictionary_service.look_up("scheme", "the scheme here")


@pytest.mark.asyncio
async def test_a_review_lookup_is_answered_and_filed_apart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The review page lets a reader tap ANY word, unrationed, and what comes
    back is kept under a source of its own.

    This is the hole the feature was built for. `appropriate` is NGSL rank
    1019, so the frequency filter calls it known and never glosses it — and a
    reader who did not know it, did not spend one of three on it during the
    paper and did not highlight it had no way at all to find out afterwards
    what it meant. The system's own ignorance was being handed to the learner
    as theirs, on the one screen built for learning.

    Two things have to be true, and neither is enforcement: the answer must
    arrive, and it must be distinguishable afterwards from a mid-paper one.
    """

    class _Knows:
        async def look_up(self, word: str, context: str):
            return dictionary_service.Gloss(
                lemma="scheme", pos="n",
                meaning_en="a plan for doing something",
                meaning_uz="reja", cefr_level="B2",
            )

    email = f"vocab-review-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    monkeypatch.setattr(dictionary_service, "providers", lambda: [_Knows()])
    try:
        async with _client() as client:
            answered = await client.post(
                f"/api/materials/{material.id}/lookups",
                json={"word": "hothouse", "context": "review"},
                headers=_headers(user),
            )
            assert answered.status_code == 200
            assert answered.json()["word"]["lemma"] == "scheme"

            # And a word the extraction DID prepare, from the same screen.
            # Nothing is generated, so nothing new is filed — but the event
            # still records which screen asked.
            await client.post(
                f"/api/materials/{material.id}/lookups",
                json={"word": "vogue", "context": "review"},
                headers=_headers(user),
            )

        async with async_session_factory() as session:
            entry = (
                await session.exec(
                    select(MaterialVocabulary).where(
                        MaterialVocabulary.material_id == material.id,
                        MaterialVocabulary.lemma == "scheme",
                    )
                )
            ).first()
            # Machine-made like an extracted entry, and overwritable on the
            # same terms — but countable on its own, which is the point.
            assert entry is not None
            assert entry.source == "review_lookup"

            events = (
                await session.exec(
                    select(LookupEvent)
                    .where(LookupEvent.material_id == material.id)
                    .order_by(LookupEvent.created_at)
                )
            ).all()
            assert [event.context for event in events] == ["review", "review"]
            # The screen and the SOURCE are two different questions and both
            # are still answered: one says where the reader was, the other
            # whether the extraction had reached this word.
            assert [event.source for event in events] == ["live", "cache"]
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_take_lookup_stays_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client that sends no context means what it has always meant.

    Every row written before the column existed is a mid-paper lookup, and
    so is every request from a client built before the review could ask.
    """
    email = f"vocab-default-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    monkeypatch.setattr(dictionary_service, "providers", lambda: [_Silent()])
    try:
        async with _client() as client:
            await client.post(
                f"/api/materials/{material.id}/lookups",
                json={"word": "vogue"},
                headers=_headers(user),
            )
        async with async_session_factory() as session:
            event = (
                await session.exec(
                    select(LookupEvent).where(
                        LookupEvent.material_id == material.id
                    )
                )
            ).first()
            assert event is not None
            assert event.context == "take"
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_re_extraction_replaces_a_learner_generated_entry() -> None:
    """`review_lookup` is machine-made, and a re-read throws it away.

    The other half of the rule above, and the easier one to get wrong: the
    test that kept an author's edit was `source != "extracted"`, which
    quietly promoted every learner-generated row to the status of a human
    correction the moment that source existed.

    It has to go for two reasons. A fresh extraction knows more about the
    word — a frequency band, a sentence cut properly — and the old row's
    offsets were measured against the text as it stood then. A re-import is
    a passage RE-READ, and a kept row from the previous reading points at
    the wrong words.
    """
    email = f"vocab-relook-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, part = await _make_passage(user.id)
    try:
        async with async_session_factory() as session:
            found = (
                await session.exec(
                    select(MaterialVocabulary).where(
                        MaterialVocabulary.material_id == material.id,
                        MaterialVocabulary.lemma == "vogue",
                    )
                )
            ).one()
            found.source = "review_lookup"
            found.meaning_uz = "STALE"
            session.add(found)
            await session.commit()

        async with async_session_factory() as session:
            written, kept = await vocabulary_service.replace_extracted(
                session,
                material_id=material.id,
                part_id=part.id,
                rows=[
                    {"lemma": "vogue", "surface": "vogue",
                     "meaning_en": "in fashion", "meaning_uz": "moda",
                     "index": 0, "start": 0, "end": 5, "cefr_level": "B2"},
                ],
            )
            await session.commit()
            # Nothing kept: the learner's row is the pipeline's to replace.
            assert (written, kept) == (1, 0)

        async with async_session_factory() as session:
            rows = await vocabulary_service.entries(session, material.id)
            by_lemma = {row.lemma: row for row in rows}
            assert by_lemma["vogue"].meaning_uz == "moda"
            assert by_lemma["vogue"].source == "extracted"
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_re_extraction_survives_a_word_somebody_saved() -> None:
    """Deleting an entry a learner has saved FROM must not fail the import.

    `saved_word_contexts.vocabulary_id` is provenance and nothing else — the
    gloss itself is copied at the moment of saving, on purpose, so that a
    re-glossed material cannot change somebody's saved word underneath them.
    The foreign key did not know that: it was a plain reference with no
    delete behaviour, so one saved word made a passage's entries
    undeletable, and `replace_extracted` deletes every machine-made row by
    design.

    Found by running a vocabulary re-import across the whole corpus for the
    first time on a database that had saved words in it. 202 passages went
    through; `cam11-t1-p1` raised a ForeignKeyViolationError over a single
    row, and the passage's whole import failed with it.

    What the learner keeps is everything that was theirs. What goes null is
    the pointer, which is what "this came from an entry that no longer
    exists" should look like.
    """
    email = f"vocab-fk-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, part = await _make_passage(user.id)
    try:
        async with _client() as client:
            kept = await client.post(
                "/api/vocabulary/words",
                json={"material_id": str(material.id), "lemmas": ["vogue"]},
                headers=_headers(user),
            )
            assert kept.status_code == 201

        async with async_session_factory() as session:
            context = (
                await session.exec(select(SavedWordContext))
            ).all()
            mine = [row for row in context if row.material_id == material.id]
            assert len(mine) == 1
            assert mine[0].vocabulary_id is not None

        # The pipeline runs again over the same passage.
        async with async_session_factory() as session:
            await vocabulary_service.replace_extracted(
                session,
                material_id=material.id,
                part_id=part.id,
                rows=[
                    {"lemma": "vogue", "surface": "vogue",
                     "meaning_en": "in fashion", "meaning_uz": "moda",
                     "index": 0, "start": 0, "end": 5, "cefr_level": "B2"},
                ],
            )
            await session.commit()

        async with async_session_factory() as session:
            rows = [
                row
                for row in (await session.exec(select(SavedWordContext))).all()
                if row.material_id == material.id
            ]
            assert len(rows) == 1, "the learner's word is not the pipeline's"
            # Their own copy, untouched: the meaning they saved, not the one
            # the re-run wrote.
            assert rows[0].meaning_uz == "moda"
            # And the pointer, gone with the row it pointed at.
            assert rows[0].vocabulary_id is None
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_word_carries_its_usual_meaning_as_well_as_this_one() -> None:
    """Both meanings reach the client, and the flag that says whether to
    print the second one.

    `claim` in the fixture is a demand for something you have a right to,
    and in paragraph A it is an assertion made without proof. The first is
    what a learner should carry away; the second is what is true here. An
    entry that only ever carried the second is what put "a computer process
    of finding patterns in data" on somebody's list under the verb `learn`.
    """
    email = f"vocab-core-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    await _submit_something(material.id, user.id)
    try:
        async with _client() as client:
            answer = await client.get(
                f"/api/materials/{material.id}/vocabulary",
                headers=_headers(user),
            )
        assert answer.status_code == 200
        body = answer.json()
        by_lemma = {entry["lemma"]: entry for entry in body["entries"]}

        claim = by_lemma["claim"]
        assert claim["meaning_core_en"] == "a demand for something you have a right to"
        assert claim["meaning_core_uz"] == "talab"
        assert claim["sense_differs"] is True
        # And the contextual one is still exactly where it was. The usual
        # meaning is an addition, not a replacement -- a reader stuck on
        # this sentence still needs the sense this sentence uses.
        assert claim["meaning_en"].startswith("a statement that something is true")

        # An ordinary word says so, and the client then prints one meaning
        # rather than the same line twice.
        assert by_lemma["hectare"]["sense_differs"] is False

        # The header figure counts the same thing the toggle under it
        # filters by, which is `sense_differs` and no longer the narrower
        # `unusual` column.
        assert body["unusual"] == 1
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_live_gloss_of_a_word_inside_a_term_answers_for_the_term(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worst gloss this feature has produced, and the fix for it.

    A reader tapped `learning` in a passage about artificial intelligence.
    What came back was "a computer process of finding patterns in data",
    filed under the lemma `learn` and marked a noun -- a faithful reading of
    `machine learning` and a false statement about the verb they then had on
    their list for ever.

    So a model may answer about something WIDER than the word, and says so
    by naming the term as the paragraph writes it. The entry is stored over
    the term's span, which is also what makes the next tap on any word in it
    land on the right row.
    """

    class _Term:
        async def look_up(self, word: str, context: str):
            return dictionary_service.Gloss(
                lemma="vertical farming", pos="phr",
                meaning_en="growing crops in stacked layers indoors",
                meaning_uz="ko'p qavatli dehqonchilik",
                meaning_core_en="growing crops in stacked layers indoors",
                meaning_core_uz="ko'p qavatli dehqonchilik",
                cefr_level="C1",
                term="vertical farming",
            )

    email = f"vocab-term-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    monkeypatch.setattr(dictionary_service, "providers", lambda: [_Term()])
    try:
        async with async_session_factory() as session:
            loaded = await session.get(Material, material.id)
            made = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="farming"
            )
        entry = made["word"]
        assert entry is not None
        assert entry.lemma == "vertical farming"
        # Stored over the TERM, not over the word that was tapped. The
        # surface slices back out of the passage, which is the property
        # every offset in this feature has to have.
        text = PASSAGE["paragraphs"][entry.paragraph_index]["text"]
        assert text[entry.offset_start : entry.offset_end] == "vertical farming"
        assert entry.surface == "vertical farming"
        assert entry.is_phrase is True
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_term_the_passage_already_has_is_not_written_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model that says "this is part of `give rise to`" is right, and the
    passage already knows.

    This is the common case rather than a corner: the reader tapped a word
    inside a phrase the extraction found long ago, and the caller is already
    showing that phrase. A second row would break one lemma per material on
    the way in, and showing it underneath as "the word on its own" would
    print the same gloss twice in one card.
    """

    class _Term:
        async def look_up(self, word: str, context: str):
            return dictionary_service.Gloss(
                lemma="give rise to", pos="phr",
                meaning_en="to cause something to happen",
                meaning_uz="sabab bo'lmoq",
                cefr_level="B2", term="give rise to",
            )

    email = f"vocab-dupe-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    monkeypatch.setattr(dictionary_service, "providers", lambda: [_Term()])
    try:
        async with async_session_factory() as session:
            loaded = await session.get(Material, material.id)
            text = PASSAGE["paragraphs"][0]["text"]
            inside = text.find("rise")
            answer = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="rise",
                paragraph_index=0, offset=inside,
            )
            assert answer["phrase"].lemma == "give rise to"
            assert answer["word"] is None, "the phrase is already the answer"

        async with async_session_factory() as session:
            rows = await vocabulary_service.entries(session, material.id)
            assert [row.lemma for row in rows].count("give rise to") == 1
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_saved_word_gains_the_usual_meaning_without_losing_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A field that did not exist when somebody saved a word is a gap, not a
    correction.

    A saved context copies its gloss and is deliberately never refreshed:
    a material can be re-glossed, and a learner's word quietly changing
    meaning underneath them is worse than one that has aged. That rule
    stands. What `enrich_saved_contexts` does is fill an EMPTY field and
    write over nothing -- otherwise a card somebody saved before the usual
    meaning existed shows one line for ever, which is the failure the field
    was added to stop.
    """
    email = f"vocab-enrich-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, part = await _make_passage(user.id)
    try:
        async with _client() as client:
            kept = await client.post(
                "/api/vocabulary/words",
                json={"material_id": str(material.id), "lemmas": ["vogue"]},
                headers=_headers(user),
            )
            assert kept.status_code == 201

        # `save` now fills the context's usual meaning live from the entry's
        # sense at save time (P4), so a freshly saved word is no longer the
        # way to construct "saved before the field existed" -- that state is
        # forced by hand here instead, standing in for a context this
        # migration's backfill left with the pre-P4 gap it always could have
        # had.
        async with async_session_factory() as session:
            saved = [
                row
                for row in (await session.exec(select(SavedWordContext))).all()
                if row.material_id == material.id
            ]
            saved[0].meaning_core_en = ""
            saved[0].meaning_core_uz = ""
            session.add(saved[0])
            await session.commit()

        # The pipeline runs again, with the new fields this time.
        async with async_session_factory() as session:
            await vocabulary_service.replace_extracted(
                session,
                material_id=material.id,
                part_id=part.id,
                rows=[
                    {"lemma": "vogue", "surface": "vogue",
                     "meaning_en": "in fashion at this moment",
                     "meaning_uz": "urfda",
                     "sense_differs": False,
                     "index": 0, "start": 0, "end": 5, "cefr_level": "B2"},
                ],
            )
            # `replace_extracted` no longer WRITES `meaning_core_en`/
            # `meaning_core_uz` onto `material_vocabulary` (`lexicon-spec.md`
            # P3: that meaning now lives on the row's `LexemeSense`) -- set
            # directly here so this test keeps exercising
            # `enrich_saved_contexts`'s own fill-when-empty rule on its own
            # terms, not the mapping this used to piggyback on.
            fresh = (await session.exec(
                select(MaterialVocabulary).where(
                    MaterialVocabulary.material_id == material.id,
                    MaterialVocabulary.lemma == "vogue",
                )
            )).first()
            fresh.meaning_core_en = "a fashion that is popular now"
            fresh.meaning_core_uz = "moda"
            session.add(fresh)
            await session.commit()

        async with async_session_factory() as session:
            filled = await vocabulary_service.enrich_saved_contexts(
                session, material_id=material.id)
            await session.commit()
            assert filled == 1

        async with async_session_factory() as session:
            saved = [
                row
                for row in (await session.exec(select(SavedWordContext))).all()
                if row.material_id == material.id
            ]
            assert len(saved) == 1
            # Gained.
            assert saved[0].meaning_core_en == "a fashion that is popular now"
            assert saved[0].meaning_core_uz == "moda"
            # And kept: the meaning they MET, not the one the re-run wrote.
            assert saved[0].meaning_en == "popular fashion at a particular time"
            assert saved[0].meaning_uz == "moda"
            # The pointer the re-extraction nulled, put back.
            assert saved[0].vocabulary_id is not None

        # Running it again changes nothing, which is what "fills where empty"
        # has to mean for a pass that runs on every single import.
        async with async_session_factory() as session:
            again = await vocabulary_service.enrich_saved_contexts(
                session, material_id=material.id)
            await session.commit()
            assert again == 0
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_lemma_the_material_already_has_is_answered_not_inserted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model answering about a word with the term it belongs to will name
    a lemma this material already holds, and that must be an ANSWER rather
    than a failed insert.

    It is the ordinary case, not a corner: a reader taps `rise`, and the
    honest gloss is `give rise to`, which the extraction wrote hours ago.
    Left to the unique constraint it becomes a failed INSERT, and a failed
    INSERT leaves the session's connection unable to serve the re-read that
    was meant to recover from it — so what the reader saw was "we couldn't
    find a meaning for that one" about a word the model had glossed
    perfectly well, or a 500.
    """

    class _Knows:
        async def look_up(self, word: str, context: str):
            return dictionary_service.Gloss(
                lemma="give rise to", pos="phr",
                meaning_en="to cause something to happen",
                meaning_uz="sabab bo'lmoq", cefr_level="B2",
            )

    email = f"vocab-known-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    monkeypatch.setattr(dictionary_service, "providers", lambda: [_Knows()])
    try:
        async with async_session_factory() as session:
            loaded = await session.get(Material, material.id)
            # No position sent, so the span match cannot help and the word
            # goes all the way through to the model.
            answer = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="produce"
            )
            assert answer["word"] is not None
            assert answer["word"].lemma == "give rise to"
            # And the session still works afterwards, which is the half of
            # this that used to fail.
            rows = await vocabulary_service.entries(session, material.id)
            assert [row.lemma for row in rows].count("give rise to") == 1
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_word_is_marked_everywhere_it_stands() -> None:
    """One entry, one gloss, and every occurrence of the word carried on it.

    `AI solutionism` appears twice in Cambridge 21's third passage and only
    the first of them was marked, which reads as the word list being
    incomplete rather than as the mark being economical. Across the corpus
    that was 17% of entries and 8 864 unmarked occurrences.

    One row per lemma per material stays exactly as it is — it is what
    makes a tapped word have one answer — so the other places ride on the
    row.
    """
    email = f"vocab-again-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, part = await _make_passage(user.id)
    await _submit_something(material.id, user.id)
    try:
        async with async_session_factory() as session:
            await vocabulary_service.replace_extracted(
                session,
                material_id=material.id,
                part_id=part.id,
                rows=[
                    {"lemma": "vogue", "surface": "vogue",
                     "meaning_en": "in fashion", "meaning_uz": "moda",
                     "index": 0, "start": 0, "end": 5, "cefr_level": "B2",
                     "again": [[1, 3, 8], [1, 20, 25]]},
                    # A malformed place is dropped rather than stored: it
                    # would be drawn as a highlight somewhere nobody meant.
                    {"lemma": "hectare", "surface": "hectares",
                     "meaning_en": "a unit of area", "meaning_uz": "gektar",
                     "index": 0, "start": 6, "end": 14, "cefr_level": "B2",
                     "again": [[1, 2], "nonsense", [2, 9, 14]]},
                ],
            )
            await session.commit()

        async with _client() as client:
            answer = await client.get(
                f"/api/materials/{material.id}/vocabulary",
                headers=_headers(user),
            )
        assert answer.status_code == 200
        by_lemma = {e["lemma"]: e for e in answer.json()["entries"]}
        assert by_lemma["vogue"]["also_at"] == [[1, 3, 8], [1, 20, 25]]
        assert by_lemma["hectare"]["also_at"] == [[2, 9, 14]]
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_tap_on_a_later_occurrence_finds_the_phrase() -> None:
    """The span test is the only thing that recognises a phrase, and it was
    only ever looking at the first occurrence.

    A reader who taps a word inside the SECOND `give rise to` would be
    answered about the word on its own — which is the one answer the phrase
    entry exists to prevent.
    """
    email = f"vocab-again-tap-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    try:
        text = PASSAGE["paragraphs"][0]["text"]
        first = text.find("give rise to")
        async with async_session_factory() as session:
            # The same expression, pretended to stand in paragraph B as
            # well. Paragraph B is shorter than A, so the offsets are its
            # own and deliberately different from the first occurrence's.
            entry = (
                await session.exec(
                    select(MaterialVocabulary).where(
                        MaterialVocabulary.material_id == material.id,
                        MaterialVocabulary.lemma == "give rise to",
                    )
                )
            ).first()
            entry.also_at = [[1, 0, 12]]
            session.add(entry)
            await session.commit()

        async with async_session_factory() as session:
            loaded = await session.get(Material, material.id)
            # Inside the second occurrence, in the other paragraph.
            found = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="Undertaken",
                paragraph_index=1, offset=4,
            )
            assert found["phrase"] is not None
            assert found["phrase"].lemma == "give rise to"
            # And the first occurrence still answers, which is the half
            # that was already working.
            again = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="rise",
                paragraph_index=0, offset=first + 5,
            )
            assert again["phrase"].lemma == "give rise to"
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_lookup_says_whether_the_word_is_already_saved() -> None:
    """The card's button is a question about the learner's list, and it was
    being answered from a field nobody filled in.

    A reader saved a word from the card, closed it, opened the same word
    again and was offered Save a second time — the page having forgotten
    what they had just done two seconds earlier. Confirmed from the event
    log: `infiltrated` was looked up, saved, and looked up again a minute
    later.
    """
    email = f"vocab-saved-flag-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    try:
        async with _client() as client:
            before = await client.post(
                f"/api/materials/{material.id}/lookups",
                json={"word": "vogue"},
                headers=_headers(user),
            )
            assert before.status_code == 200
            assert before.json()["word"]["saved"] is False

            kept = await client.post(
                "/api/vocabulary/words",
                json={"material_id": str(material.id), "lemmas": ["vogue"]},
                headers=_headers(user),
            )
            assert kept.status_code == 201

            after = await client.post(
                f"/api/materials/{material.id}/lookups",
                json={"word": "vogue"},
                headers=_headers(user),
            )
            assert after.json()["word"]["saved"] is True

            # And somebody else's list is their own.
            other = await _make_user(f"vocab-other-{uuid.uuid4()}@test.local")
            theirs = await client.post(
                f"/api/materials/{material.id}/lookups",
                json={"word": "vogue"},
                headers=_headers(other),
            )
            assert theirs.json()["word"]["saved"] is False
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_saved_word_can_be_taken_off_the_list_again() -> None:
    """A button that can only be pressed one way is a decision the reader
    cannot take back, and the whole invitation is to press it on a hunch."""
    email = f"vocab-unsave-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    await _submit_something(material.id, user.id)
    try:
        async with _client() as client:
            head = {"material_id": str(material.id), "lemmas": ["vogue"]}
            assert (await client.post("/api/vocabulary/words", json=head,
                                      headers=_headers(user))).status_code == 201
            listed = await client.get(
                "/api/vocabulary/words", headers=_headers(user)
            )
            word_id = listed.json()["words"][0]["id"]

            gone = await client.delete(
                f"/api/vocabulary/words/{word_id}", headers=_headers(user)
            )
            assert gone.status_code == 204

            # The list beside the passage says so too, which is what the
            # button on the row is reading.
            listed = await client.get(
                f"/api/materials/{material.id}/vocabulary",
                headers=_headers(user),
            )
            by_lemma = {e["lemma"]: e for e in listed.json()["entries"]}
            assert by_lemma["vogue"]["saved"] is False

            # And it can go back on, which is the half that makes it a
            # toggle rather than a delete.
            assert (await client.post("/api/vocabulary/words", json=head,
                                      headers=_headers(user))).status_code == 201
            again = await client.get(
                f"/api/materials/{material.id}/vocabulary",
                headers=_headers(user),
            )
            assert {e["lemma"]: e for e in again.json()["entries"]}["vogue"][
                "saved"
            ] is True
    finally:
        await _cleanup(material.id, email)


# --- P4: a saved word is a sense, not a spelling ----------------------------


async def _make_material_with_linked_entry(
    author_id: uuid.UUID, *, lemma: str, sense_id: uuid.UUID, lexeme_id: uuid.UUID,
    meaning_en: str, meaning_uz: str,
) -> tuple[Material, MaterialVocabulary]:
    """A one-entry material whose row is ALREADY linked to a given sense --
    what every real writer (`replace_extracted`/`_generate`) guarantees via
    `link_row`, built by hand here so two rows can be pointed at two
    DIFFERENT senses of the SAME lexeme on purpose."""
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id, type="reading",
            title=f"Sense fixture {uuid.uuid4()}", visibility="public",
        )
        session.add(material)
        await session.flush()
        text = f"A sentence about the {lemma}."
        part = Part(
            material_id=material.id, order_index=0, title="Reading Passage 1",
            passage={"paragraphs": [{"label": "A", "text": text}], "subtitle": None,
                    "source": None},
            first_number=1,
        )
        session.add(part)
        await session.flush()
        at = text.find(lemma)
        entry = MaterialVocabulary(
            material_id=material.id, part_id=part.id, lemma=lemma, surface=lemma,
            pos="n", meaning_en=meaning_en, meaning_uz=meaning_uz, example=text,
            offset_start=at, offset_end=at + len(lemma), cefr_level="B1",
            lexeme_id=lexeme_id, sense_id=sense_id,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(material)
        await session.refresh(entry)
        return material, entry


async def _make_two_senses(lemma: str) -> tuple[Lexeme, LexemeSense, LexemeSense]:
    async with async_session_factory() as session:
        lexeme = Lexeme(lemma=lemma, pos="n")
        session.add(lexeme)
        await session.flush()
        first = LexemeSense(
            lexeme_id=lexeme.id, sense_rank=1,
            definition_en="a financial institution", meaning_uz="bank",
        )
        second = LexemeSense(
            lexeme_id=lexeme.id, sense_rank=2,
            definition_en="the land beside a river", meaning_uz="qirg'oq",
        )
        session.add_all([first, second])
        await session.commit()
        await session.refresh(lexeme)
        await session.refresh(first)
        await session.refresh(second)
        return lexeme, first, second


async def _cleanup_lexeme(lexeme_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        for report in (
            await session.exec(
                select(TranslationReport).where(
                    TranslationReport.lexeme_sense_id.in_(
                        select(LexemeSense.id).where(LexemeSense.lexeme_id == lexeme_id)
                    )
                )
            )
        ).all():
            await session.delete(report)
        await session.flush()
        for sense in (
            await session.exec(select(LexemeSense).where(LexemeSense.lexeme_id == lexeme_id))
        ).all():
            await session.delete(sense)
        await session.flush()
        lexeme = await session.get(Lexeme, lexeme_id)
        if lexeme is not None:
            await session.delete(lexeme)
        await session.commit()


@pytest.mark.asyncio
async def test_saving_one_sense_leaves_a_different_sense_of_the_same_lemma_unsaved() -> None:
    """`bank` the financial institution and `bank` the river are two words
    to a learner, and the popover has to be able to tell them apart: saving
    one must not make the OTHER answer `saved: true`, and it must say a
    different meaning of the same lemma IS on the list, quietly."""
    email = f"vocab-sense-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    lexeme, finance, river = await _make_two_senses("bank")
    material_a, _ = await _make_material_with_linked_entry(
        user.id, lemma="bank", sense_id=finance.id, lexeme_id=lexeme.id,
        meaning_en="a financial institution", meaning_uz="bank",
    )
    material_b, _ = await _make_material_with_linked_entry(
        user.id, lemma="bank", sense_id=river.id, lexeme_id=lexeme.id,
        meaning_en="the land beside a river", meaning_uz="qirg'oq",
    )
    try:
        async with _client() as client:
            saved = await client.post(
                "/api/vocabulary/words",
                json={"material_id": str(material_a.id), "lemmas": ["bank"]},
                headers=_headers(user),
            )
            assert saved.status_code == 201

            await _submit_something(material_b.id, user.id)
            other = await client.get(
                f"/api/materials/{material_b.id}/vocabulary", headers=_headers(user)
            )
            entry_b = other.json()["entries"][0]
            assert entry_b["saved"] is False
            assert entry_b["other_sense_saved"] is True

            await _submit_something(material_a.id, user.id)
            mine = await client.get(
                f"/api/materials/{material_a.id}/vocabulary", headers=_headers(user)
            )
            entry_a = mine.json()["entries"][0]
            assert entry_a["saved"] is True
            assert entry_a["saved_word_id"] == saved.json()["words"][0]["id"]
            assert entry_a["other_sense_saved"] is False

            # And the words list carries the two apart, by sense: saving the
            # second sense too is a SECOND word, not a merge into the first.
            saved_b = await client.post(
                "/api/vocabulary/words",
                json={"material_id": str(material_b.id), "lemmas": ["bank"]},
                headers=_headers(user),
            )
            assert saved_b.status_code == 201
            listed = await client.get(
                "/api/vocabulary/words", headers=_headers(user)
            )
            words = listed.json()["words"]
            assert len(words) == 2
            assert {word["lemma"] for word in words} == {"bank"}
            assert {word["sense_id"] for word in words} == {str(finance.id), str(river.id)}
    finally:
        await _cleanup(material_b.id)
        await _cleanup(material_a.id, email)
        await _cleanup_lexeme(lexeme.id)


@pytest.mark.asyncio
async def test_get_or_create_saved_word_survives_a_racing_duplicate_insert() -> None:
    """Two requests racing to save the SAME sense for the SAME learner can
    both pass `save`'s own SELECT check before either commits its INSERT --
    `_get_or_create_saved_word` is what the loser falls back to instead of
    raising `IntegrityError` out of the request. Simulated by committing
    the "winning" row directly first, then calling the helper exactly as
    the loser would: it must return that winner rather than raise, and must
    never leave a second row behind."""
    email = f"vocab-race-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    lexeme, sense, _unused = await _make_two_senses("racehorse")
    try:
        async with async_session_factory() as session:
            winner = SavedWord(
                user_id=user.id, lemma="racehorse", pos="n", lexeme_sense_id=sense.id,
            )
            session.add(winner)
            await session.commit()
            await session.refresh(winner)

        async with async_session_factory() as session:
            word, created = await vocabulary_service._get_or_create_saved_word(
                session, user_id=user.id, sense_id=sense.id, lemma="racehorse", pos="n",
            )
            await session.commit()
        assert created is False
        assert word.id == winner.id

        async with async_session_factory() as session:
            rows = (
                await session.exec(
                    select(SavedWord).where(
                        SavedWord.user_id == user.id,
                        SavedWord.lexeme_sense_id == sense.id,
                    )
                )
            ).all()
        assert len(rows) == 1  # the race never leaves a duplicate behind
    finally:
        async with async_session_factory() as session:
            for word_row in (
                await session.exec(select(SavedWord).where(SavedWord.user_id == user.id))
            ).all():
                await session.delete(word_row)
            await session.flush()
            stale_user = (
                await session.exec(select(User).where(User.email == email))
            ).first()
            if stale_user is not None:
                await session.delete(stale_user)
            await session.commit()
        await _cleanup_lexeme(lexeme.id)


@pytest.mark.asyncio
async def test_translation_report_is_one_open_row_per_user_and_sense() -> None:
    email = f"vocab-report-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    lexeme, finance, _river = await _make_two_senses("bank-report")
    try:
        async with _client() as client:
            first = await client.post(
                "/api/vocabulary/translation-reports",
                json={"sense_id": str(finance.id), "where": "word_page",
                     "note": "this should say financial institution"},
                headers=_headers(user),
            )
            assert first.status_code == 201
            body = first.json()
            assert body["sense_id"] == str(finance.id)
            assert body["status"] == "open"

            # A repeat from the same learner about the same sense is a
            # no-op: 200, not a second row.
            again = await client.post(
                "/api/vocabulary/translation-reports",
                json={"sense_id": str(finance.id), "where": "practice"},
                headers=_headers(user),
            )
            assert again.status_code == 200
            assert again.json()["id"] == body["id"]

            # A sense that does not exist is a 404, not a foreign key crash.
            missing = await client.post(
                "/api/vocabulary/translation-reports",
                json={"sense_id": str(uuid.uuid4()), "where": "word_page"},
                headers=_headers(user),
            )
            assert missing.status_code == 404

        async with async_session_factory() as session:
            reports = (
                await session.exec(
                    select(TranslationReport).where(
                        TranslationReport.lexeme_sense_id == finance.id
                    )
                )
            ).all()
            assert len(reports) == 1
            assert reports[0].source == "word_page"  # the FIRST call's source
            assert reports[0].note == "this should say financial institution"
    finally:
        await _cleanup_lexeme(lexeme.id)
        async with async_session_factory() as session:
            found = (await session.exec(select(User).where(User.email == email))).first()
            if found is not None:
                await session.delete(found)
                await session.commit()


# --- Browse (§C): `browsed_at` and nothing else -----------------------------


@pytest.mark.asyncio
async def test_browsed_endpoint_sets_browsed_at_and_writes_nothing_else() -> None:
    """Browse is explicitly not practice: the one endpoint it has may only
    ever touch `browsed_at` -- no review log, no FSRS card, no due change,
    nothing counted in daily minutes."""
    email = f"vocab-browsed-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    lexeme, finance, _river = await _make_two_senses("browse-word")
    material, _entry = await _make_material_with_linked_entry(
        user.id, lemma="browse-word", sense_id=finance.id, lexeme_id=lexeme.id,
        meaning_en="a financial institution", meaning_uz="bank",
    )
    try:
        async with _client() as client:
            saved = await client.post(
                "/api/vocabulary/words",
                json={"material_id": str(material.id), "lemmas": ["browse-word"]},
                headers=_headers(user),
            )
            assert saved.status_code == 201
            word_id = saved.json()["words"][0]["id"]
            assert saved.json()["words"][0]["browsed_at"] is None

        async with async_session_factory() as session:
            before = await session.get(SavedWord, uuid.UUID(word_id))
            assert before is not None
            passive_due_before = before.passive_due
            passive_state_before = before.passive_state
            reps_before = before.reps

        async with _client() as client:
            r = await client.post(
                f"/api/vocabulary/words/{word_id}/browsed", headers=_headers(user)
            )
            assert r.status_code == 204
            assert r.content == b""

            listed = await client.get(
                "/api/vocabulary/words", headers=_headers(user)
            )
            row = next(w for w in listed.json()["words"] if w["id"] == word_id)
            assert row["browsed_at"] is not None

            detail = await client.get(
                f"/api/vocabulary/words/{word_id}", headers=_headers(user)
            )
            assert detail.json()["word"]["browsed_at"] is not None

        async with async_session_factory() as session:
            after = await session.get(SavedWord, uuid.UUID(word_id))
            assert after is not None
            # Nothing about the FSRS card or the word's own practice
            # bookkeeping moved.
            assert after.passive_due == passive_due_before
            assert after.passive_state == passive_state_before
            assert after.reps == reps_before
            # No review log at all -- Browse is not practice.
            logs = (
                await session.exec(
                    select(VocabularyReviewLog).where(
                        VocabularyReviewLog.saved_word_id == after.id
                    )
                )
            ).all()
            assert logs == []
    finally:
        await _cleanup(material.id, email)
        await _cleanup_lexeme(lexeme.id)


@pytest.mark.asyncio
async def test_browsed_endpoint_is_owner_only() -> None:
    email_a = f"vocab-browsed-a-{uuid.uuid4()}@test.local"
    email_b = f"vocab-browsed-b-{uuid.uuid4()}@test.local"
    owner = await _make_user(email_a)
    stranger = await _make_user(email_b)
    lexeme, finance, _river = await _make_two_senses("browse-owner-word")
    material, _entry = await _make_material_with_linked_entry(
        owner.id, lemma="browse-owner-word", sense_id=finance.id, lexeme_id=lexeme.id,
        meaning_en="a financial institution", meaning_uz="bank",
    )
    try:
        async with _client() as client:
            saved = await client.post(
                "/api/vocabulary/words",
                json={"material_id": str(material.id), "lemmas": ["browse-owner-word"]},
                headers=_headers(owner),
            )
            word_id = saved.json()["words"][0]["id"]

            # A stranger's own id (a word they never saved) is a 404 -- the
            # same shape as every other by-id word route, not a 403 that
            # would confirm somebody else's word exists at all.
            r = await client.post(
                f"/api/vocabulary/words/{word_id}/browsed", headers=_headers(stranger)
            )
            assert r.status_code == 404

            still = await client.get(
                "/api/vocabulary/words", headers=_headers(owner)
            )
            row = next(w for w in still.json()["words"] if w["id"] == word_id)
            assert row["browsed_at"] is None
    finally:
        await _cleanup(material.id, email_a, email_b)
        await _cleanup_lexeme(lexeme.id)
