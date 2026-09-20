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
  review.

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
from app.models.material import Material
from app.models.part import Part
from app.models.user import User
from app.models.vocabulary import MaterialVocabulary, SavedWord, SavedWordContext
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
     "meaning_en": "a statement that something is true, without proof",
     "meaning_uz": "da'vo, tasdiq", "index": 0, "cefr_level": "C1",
     "frequency_band": "core", "is_phrase": False, "unusual": True},
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
                    pos=entry["pos"], meaning_en=entry["meaning_en"],
                    meaning_uz=entry["meaning_uz"],
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
                session, loaded, word="vogue", paragraph_index=0, offset=at + 2
            )
            assert by_span["word"].lemma == "vogue"

            # 2. By the surface form, which is what stands in the passage.
            by_surface = await vocabulary_service.look_up(
                session, loaded, word="Undertaken"
            )
            assert by_surface["word"].lemma == "undertake"

            # 3. By the lemma itself.
            by_lemma = await vocabulary_service.look_up(
                session, loaded, word="proponent"
            )
            assert by_lemma["word"].lemma == "proponent"

            # 4. By reduction: `hectares` is stored as its own surface, but a
            #    reader who taps a form the passage does not print still has
            #    to land somewhere. `proponents` reduces to `proponent`.
            by_reduction = await vocabulary_service.look_up(
                session, loaded, word="Proponents,"
            )
            assert by_reduction["word"].lemma == "proponent"
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_tapping_inside_a_phrase_returns_the_phrase_as_well() -> None:
    """The brief's rule, exactly: does the tapped offset fall inside some
    ``is_phrase`` entry's span. `rise` is one of the commonest words in
    English and no frequency filter would ever offer it -- `give rise to` is
    what actually stopped the reader."""
    email = f"vocab-phrase-{uuid.uuid4()}@test.local"
    user = await _make_user(email)
    material, _ = await _make_passage(user.id)
    try:
        async with async_session_factory() as session:
            loaded = await session.get(Material, material.id)
            text = PASSAGE["paragraphs"][0]["text"]
            inside = text.find("rise")
            assert text.find("give rise to") < inside < text.find("give rise to") + 12

            found = await vocabulary_service.look_up(
                session, loaded, word="rise", paragraph_index=0, offset=inside
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
                "/api/vocabulary/words/vogue", headers=_headers(user)
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
    monkeypatch.setattr(dictionary_service, "provider", lambda: _Silent())
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
    monkeypatch.setattr(dictionary_service, "provider", lambda: _Knows())
    try:
        async with async_session_factory() as session:
            loaded = await session.get(Material, material.id)
            # Paragraph B holds `scheme`; paragraph A is searched too, which
            # is what lets a client that sent no position still be answered.
            made = await vocabulary_service.look_up(
                session, loaded, word="hothouse"
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
        monkeypatch.setattr(dictionary_service, "provider", lambda: _Silent())
        async with async_session_factory() as session:
            loaded = await session.get(Material, material.id)
            again = await vocabulary_service.look_up(session, loaded, word="scheme")
            assert again["word"].meaning_uz == "reja"
    finally:
        await _cleanup(material.id, email)
