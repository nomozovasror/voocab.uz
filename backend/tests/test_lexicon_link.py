"""P3 find-or-create (`app.services.lexicon.link_row`) and the worker loop
that finishes what it starts (`app.worker`'s lexicon loop).

`lexicon-spec.md` D6: every `material_vocabulary` write -- the seed import
path (`app.services.vocabulary.replace_extracted`) and a live lookup
(`app.services.vocabulary._generate`) -- must leave the row with a
`lexeme_id` and a `sense_id`, synchronously, with no model call. What is
worth testing here is the same shape `test_lexicon_enrich.py` uses for P2:
the DECISIONS (the merge rule reused rather than copied, the dedupe of an
identical meaning, a lexeme reopened for enrichment) plus two real,
end-to-end runs -- a live lookup, and an import of real seed-shaped rows --
proving the wiring, not just the pure functions.

Nothing here calls Gemini except through a scripted stand-in, the same
pattern `test_lexicon_enrich.py`'s `ScriptedGemini` uses.
"""

import uuid

import pytest
from sqlmodel import select

from app import worker as worker_module
from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense
from app.models.material import Material
from app.models.part import Part
from app.models.user import User
from app.models.vocabulary import LookupEvent, MaterialVocabulary
from app.services import dictionary as dictionary_service
from app.services import lexicon as lexicon_service
from app.services import lexicon_enrich as lexicon_enrich_service
from app.services import vocabulary as vocabulary_service

# --- The merge rule and normalisation, reused not copied ---------------------


def test_merge_candidate_and_normalise_meaning_are_the_p1_rule() -> None:
    """`app.services.lexicon` is now where `scripts/build_lexicon.py` gets
    these from too -- see that script's own import line. A change here is a
    change to both P1's batch rule and P3's incremental one at once."""
    known_verbs = {"accumulate", "reserve"}
    assert lexicon_service.merge_candidate("accumulating", "v", known_verbs) == "accumulate"
    assert lexicon_service.merge_candidate("reserved", "v", known_verbs) == "reserve"
    # `digest` -> `dig` is exactly the false positive the rule was narrowed
    # to avoid (an agent-noun `-er`/`-est`-shaped ending is only trusted for
    # adjectives, never nouns or verbs).
    assert lexicon_service.merge_candidate("digest", "v", {"dig"}) is None

    assert (lexicon_service.normalise_meaning("An Action Of Moving Downward!")
            == lexicon_service.normalise_meaning("an action of moving downward"))
    assert lexicon_service.lexeme_is_phrase("give rise to", "") is True
    assert lexicon_service.lexeme_is_phrase("subject", "phr") is True
    assert lexicon_service.lexeme_is_phrase("subject", "n") is False


# --- link_row ------------------------------------------------------------


def _row(**kwargs) -> MaterialVocabulary:
    """An in-memory `MaterialVocabulary` row for `link_row` to read --
    never added to the session or committed in the tests below, which only
    care about `link_row`'s OWN writes (the `Lexeme`/`LexemeSense`) and the
    `lexeme_id`/`sense_id` attributes it sets on this object. Its
    `material_id`/`part_id` are therefore fake on purpose: a real FK would
    need a real `Material`/`Part`, which the tests that actually persist a
    row (the live lookup and the real import, below) build for real.
    """
    defaults = dict(
        material_id=uuid.uuid4(), part_id=uuid.uuid4(),
        surface=kwargs.get("lemma", ""), pos="n",
        meaning_en="a demand for something", meaning_uz="talab",
        cefr_level="B2",
    )
    defaults.update(kwargs)
    return MaterialVocabulary(**defaults)


async def _delete_lexemes(*lemmas: str) -> None:
    """Test cleanup: every `Lexeme` (and its `LexemeSense`s) with one of
    these exact lemmas -- keeps the shared `app_test` database, and in
    particular `app.worker`'s "pending" queue, exactly as empty after this
    file runs as before it."""
    async with async_session_factory() as session:
        lexemes = (await session.exec(select(Lexeme).where(Lexeme.lemma.in_(lemmas)))).all()
        for lexeme in lexemes:
            for sense in (await session.exec(
                select(LexemeSense).where(LexemeSense.lexeme_id == lexeme.id)
            )).all():
                await session.delete(sense)
            await session.flush()
            await session.delete(lexeme)
        await session.commit()


@pytest.mark.asyncio
async def test_link_row_creates_a_lexeme_and_a_provisional_sense() -> None:
    tag = uuid.uuid4().hex[:8]
    lemma = f"zorbex{tag}"
    try:
        async with async_session_factory() as session:
            row = _row(lemma=lemma, pos="n", meaning_en="a fictional test word",
                        meaning_uz="sinov so'zi", cefr_level="B1")
            await lexicon_service.link_row(session, row)
            await session.commit()

            assert row.lexeme_id is not None and row.sense_id is not None
            lexeme = await session.get(Lexeme, row.lexeme_id)
            sense = await session.get(LexemeSense, row.sense_id)
            assert lexeme.lemma == lemma and lexeme.pos == "n"
            # Off every frequency list -- a made-up word.
            assert lexeme.frequency_band == "off-list"
            assert lexeme.cefr == "B1"  # copied from the row, no model call
            assert sense.provisional is True
            assert sense.source_id == "model" and sense.licence == "proprietary"
            assert sense.cefr == "B1"
            assert sense.definition_en == "a fictional test word"
            assert sense.meaning_uz == "sinov so'zi"
            # No model call in the request path: nothing here awaited a
            # network call, and the row is already fully linked.
            assert lexeme.enriched_at is None
    finally:
        await _delete_lexemes(lemma)


@pytest.mark.asyncio
async def test_link_row_never_writes_meaning_core_on_the_row() -> None:
    """The row's own `meaning_core_en`/`meaning_core_uz` stay dead
    (`lexicon-spec.md` P3, brief §3): `link_row` only ever reads them off
    whatever the CALLER happened to set before calling it, and never sets
    them itself."""
    tag = uuid.uuid4().hex[:8]
    async with async_session_factory() as session:
        row = _row(lemma=f"plainword{tag}")
        assert row.meaning_core_en == "" and row.meaning_core_uz == ""
        await lexicon_service.link_row(session, row)
        assert row.meaning_core_en == "" and row.meaning_core_uz == ""


@pytest.mark.asyncio
async def test_link_row_merges_an_inflected_form_into_an_existing_lexeme() -> None:
    """The identical rule `scripts/build_lexicon.py` runs over the whole
    corpus at once, applied here one row at a time: a lemma that is an
    inflected form of a lexeme ALREADY IN THE DATABASE attaches to it
    instead of minting a second one -- the `descending`/`descent` collision
    the rule exists for, replayed live."""
    tag = uuid.uuid4().hex[:8]
    # The tag sits BEFORE the inflectional suffix, not after it -- the
    # merge rule matches on the literal ending ("...ing" -> "...", "...e"),
    # and a tag appended after "accumulating" would leave the lemma not
    # actually ending in "ing" at all.
    base = f"accum{tag}ate"
    inflected = f"accum{tag}ating"
    try:
        async with async_session_factory() as session:
            existing = Lexeme(lemma=base, pos="v", frequency_band="core",
                              frequency_source="ngsl")
            session.add(existing)
            await session.commit()
            await session.refresh(existing)

            row = _row(lemma=inflected, pos="v",
                        meaning_en="gathering over time", meaning_uz="to'planmoq")
            await lexicon_service.link_row(session, row)
            await session.commit()

            assert row.lexeme_id == existing.id
            # And the merge did not silently invent a second, orphaned lexeme.
            stray = (await session.exec(
                select(Lexeme).where(Lexeme.lemma == inflected)
            )).first()
            assert stray is None
    finally:
        await _delete_lexemes(base, inflected)


@pytest.mark.asyncio
async def test_link_row_dedupes_a_sense_with_the_identical_normalised_meaning() -> None:
    """Two rows glossing one lexeme with the same wording -- differing only
    by case and punctuation -- must not each buy a provisional sense: P1's
    own clustering would merge them on its next rebuild, so `link_row`
    checks first, with the identical `normalise_meaning` key P1 clusters
    with."""
    tag = uuid.uuid4().hex[:8]
    lemma = f"descendx{tag}"
    try:
        async with async_session_factory() as session:
            lexeme = Lexeme(lemma=lemma, pos="v", frequency_band="off-list")
            session.add(lexeme)
            await session.commit()
            await session.refresh(lexeme)
            first_sense = LexemeSense(
                lexeme_id=lexeme.id, sense_rank=1,
                definition_en="an action of moving downward",
                meaning_uz="pastga tushish", cefr="B1", provisional=True,
            )
            session.add(first_sense)
            await session.commit()
            await session.refresh(first_sense)

            row = _row(lemma=lemma, pos="v",
                        meaning_en="An Action Of Moving Downward!",
                        meaning_uz="boshqacha yozilgan", cefr_level="B2")
            await lexicon_service.link_row(session, row)
            await session.commit()

            assert row.sense_id == first_sense.id
            senses = (await session.exec(
                select(LexemeSense).where(LexemeSense.lexeme_id == lexeme.id)
            )).all()
            assert len(senses) == 1  # no second, near-duplicate sense
    finally:
        await _delete_lexemes(lemma)


@pytest.mark.asyncio
async def test_link_row_adds_a_distinct_sense_and_reopens_an_enriched_lexeme() -> None:
    """A genuinely different meaning gets its own sense -- and if the lexeme
    had already been enriched (P2 finished it), that sense being new is
    exactly the fact that must send it back to the worker's queue, or the
    new sense sits ungraded forever."""
    tag = uuid.uuid4().hex[:8]
    lemma = f"springx{tag}"
    try:
        async with async_session_factory() as session:
            lexeme = Lexeme(lemma=lemma, pos="n", frequency_band="common",
                            frequency_source="ngsl", cefr="B1")
            session.add(lexeme)
            await session.commit()
            await session.refresh(lexeme)
            session.add(LexemeSense(
                lexeme_id=lexeme.id, sense_rank=1, definition_en="the season after winter",
                meaning_uz="bahor", cefr="B1", source_id="oewn", licence="cc-by-4.0",
                provisional=False,
            ))
            await session.commit()
            # This lexeme is DONE, as far as P2 is concerned.
            lexeme.enriched_at = lexeme.created_at
            session.add(lexeme)
            await session.commit()

            row = _row(lemma=lemma, pos="n", meaning_en="a coil of metal",
                        meaning_uz="prujina", cefr_level="B2")
            await lexicon_service.link_row(session, row)
            await session.commit()

            senses = (await session.exec(
                select(LexemeSense).where(LexemeSense.lexeme_id == lexeme.id)
            )).all()
            assert len(senses) == 2
            assert row.sense_id not in {s.id for s in senses if not s.provisional}
            new_sense = next(s for s in senses if s.id == row.sense_id)
            assert new_sense.provisional is True

            refreshed = await session.get(Lexeme, lexeme.id)
            assert refreshed.enriched_at is None  # back on the worker's queue
            # The lexeme's OWN denormalised cefr is untouched: this was not
            # its first sense.
            assert refreshed.cefr == "B1"
    finally:
        await _delete_lexemes(lemma)


# --- A real live lookup, wired end to end -------------------------------


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        user = User(email=email, display_name="lexicon link test")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_material() -> tuple[Material, Part, User]:
    passage = {
        "paragraphs": [{"label": "A", "text": (
            "Beekeeping has flourished in remote highland villages for "
            "generations, and the practice continues to this day."
        )}],
        "subtitle": None, "source": None,
    }
    user = await _make_user(f"lexicon-link-owner-{uuid.uuid4()}@test.local")
    async with async_session_factory() as session:
        material = Material(author_id=user.id, type="reading",
                            title=f"lexicon link fixture {uuid.uuid4()}",
                            visibility="private")
        session.add(material)
        await session.flush()
        part = Part(material_id=material.id, order_index=0, title="Reading Passage 1",
                    passage=passage, first_number=1)
        session.add(part)
        await session.commit()
        await session.refresh(material)
        await session.refresh(part)
        return material, part, user


async def _cleanup(material_id: uuid.UUID, user_id: uuid.UUID | None = None) -> None:
    async with async_session_factory() as session:
        for row in (await session.exec(
            select(LookupEvent).where(LookupEvent.material_id == material_id)
        )).all():
            await session.delete(row)
        for row in (await session.exec(
            select(MaterialVocabulary).where(MaterialVocabulary.material_id == material_id)
        )).all():
            await session.delete(row)
        for part in (await session.exec(
            select(Part).where(Part.material_id == material_id)
        )).all():
            await session.delete(part)
        material = await session.get(Material, material_id)
        if material is not None:
            await session.delete(material)
        await session.flush()
        if user_id is not None:
            user = await session.get(User, user_id)
            if user is not None:
                await session.delete(user)
        await session.commit()


class _Beekeeping:
    async def look_up(self, word: str, context: str):
        return dictionary_service.Gloss(
            lemma="beekeeping", pos="n",
            meaning_core_en="the practice of keeping bees for honey",
            meaning_core_uz="asalarichilik",
            meaning_en="the practice of keeping bees for honey",
            meaning_uz="asalarichilik",
            cefr_level="B2",
        )


@pytest.mark.asyncio
async def test_a_live_lookup_links_its_row_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_generate` -- the live-lookup writer -- calls `link_row` before the
    row is ever committed, so a word the seed extraction never saw is fully
    linked from the moment it exists, with no model call beyond the one
    already answering the reader's own question."""
    material, _, user = await _make_material()
    monkeypatch.setattr(dictionary_service, "providers", lambda: [_Beekeeping()])
    try:
        async with async_session_factory() as session:
            loaded = await session.get(Material, material.id)
            made = await vocabulary_service.look_up(
                session, loaded, user_id=user.id, word="beekeeping",
            )
        entry = made["word"]
        assert entry is not None and entry.lemma == "beekeeping"
        assert entry.lexeme_id is not None and entry.sense_id is not None
        # Dead for writes: the usual meaning now lives on the LexemeSense.
        assert entry.meaning_core_en == "" and entry.meaning_core_uz == ""

        async with async_session_factory() as session:
            lexeme = await session.get(Lexeme, entry.lexeme_id)
            sense = await session.get(LexemeSense, entry.sense_id)
            assert lexeme.lemma == "beekeeping" and lexeme.pos == "n"
            assert sense.provisional is True
            assert sense.definition_en == "the practice of keeping bees for honey"
            assert sense.meaning_uz == "asalarichilik"
    finally:
        await _cleanup(material.id, user.id)
        await _delete_lexemes("beekeeping")


# --- A real import of seed-shaped rows -----------------------------------

#: Copied verbatim from a real `seed/read_vocabulary.py` run
#: (`seed/work/cam10-t1-p1/vocabulary.json`) rather than read from that
#: gitignored, machine-local cache at test time -- real shape, hermetic
#: test. `descend`/`descending` is added on top of the genuine rows to
#: exercise the merge rule inside a real import, the same collision
#: `scripts/build_lexicon.py`'s own docstring measured 315 real cases of.
SEED_SHAPED_ROWS = [
    {"lemma": "inhabitant", "pos": "n",
     "meaning_core_en": "A person or animal that lives in a particular place.",
     "meaning_core_uz": "muayyan joyda yashovchi shaxs yoki jonivor",
     "meaning_en": "A person or animal that lives in a particular place.",
     "meaning_uz": "muayyan joyda yashovchi shaxs yoki jonivor",
     "sense_differs": False, "cefr_level": "B2", "frequency_band": "off-list",
     "surface": "inhabitants", "index": 0, "start": 44, "end": 55,
     "example": "The inhabitants of the region built canals.",
     "is_phrase": False, "again": []},
    {"lemma": "modern-day", "pos": "adj",
     "meaning_core_en": "Relating to the present time; contemporary.",
     "meaning_core_uz": "hozirgi zamonga oid; zamonaviy",
     "meaning_en": "Relating to the present time; contemporary.",
     "meaning_uz": "hozirgi zamonga oid; zamonaviy",
     "sense_differs": False, "cefr_level": "B2", "frequency_band": "off-list",
     "surface": "modern-day", "index": 0, "start": 63, "end": 73,
     "example": "The modern-day states of the region.",
     "is_phrase": False, "again": []},
    {"lemma": "descend", "pos": "v",
     "meaning_core_en": "To move downward.", "meaning_core_uz": "pastga tushmoq",
     "meaning_en": "To move downward.", "meaning_uz": "pastga tushmoq",
     "sense_differs": False, "cefr_level": "B1", "frequency_band": "wider",
     "surface": "descend", "index": 0, "start": 0, "end": 7,
     "example": "Water descends through the canal system.",
     "is_phrase": False, "again": []},
    {"lemma": "descending", "pos": "v",
     "meaning_core_en": "Moving downward.", "meaning_core_uz": "pastga tushayotgan",
     "meaning_en": "Moving downward in this passage.", "meaning_uz": "pastga tushayotgan",
     "sense_differs": False, "cefr_level": "B1", "frequency_band": "off-list",
     "surface": "descending", "index": 0, "start": 20, "end": 30,
     "example": "The descending water is collected below.",
     "is_phrase": False, "again": []},
]


@pytest.mark.asyncio
async def test_a_real_import_links_every_row_and_the_worker_enriches_them() -> None:
    """`replace_extracted` -- the seed import path -- run against real,
    seed-shaped rows, proving two things end to end: every row it writes has
    a `lexeme_id`/`sense_id` immediately (no model call in the import loop
    beyond what the seed pipeline already paid for), and the ONE inflected
    collision in this batch (`descending` -> `descend`) merges into the
    lexeme its own material row created moments earlier -- P1's own rule,
    exercised live instead of in a batch rebuild.

    The second half proves the worker's own job -- every lexeme this import
    just created is `enriched_at IS NULL`, and a scripted, per-lexeme
    `app.services.lexicon_enrich.enrich` run (exactly what
    `app.worker._lexicon_enrich_once` calls once it has picked its ids)
    finishes them. That wrapper's OWN "which ids" query is exercised
    separately, on an isolated lexeme, by the test below this one --
    `app_test` is shared with every other test file, and asserting an exact
    global "0 pending" here would make this test depend on what else
    happens to be sitting in the queue when it runs.
    """
    material, part, user = await _make_material()
    try:
        async with async_session_factory() as session:
            written, kept = await vocabulary_service.replace_extracted(
                session, material_id=material.id, part_id=part.id,
                rows=SEED_SHAPED_ROWS,
            )
            await session.commit()
        assert written == 4 and kept == 0

        async with async_session_factory() as session:
            rows = (await session.exec(
                select(MaterialVocabulary).where(MaterialVocabulary.material_id == material.id)
            )).all()
            assert len(rows) == 4
            assert all(r.lexeme_id is not None and r.sense_id is not None for r in rows)
            # Dead for writes, on every row this import produced.
            assert all(r.meaning_core_en == "" and r.meaning_core_uz == "" for r in rows)

            by_lemma = {r.lemma: r for r in rows}
            assert by_lemma["descending"].lexeme_id == by_lemma["descend"].lexeme_id
            lexeme_ids = list({r.lexeme_id for r in rows})
            assert len(lexeme_ids) == 3  # four rows, one merge -> three lexemes

            pending_before = (await session.exec(
                select(Lexeme.id).where(
                    Lexeme.id.in_(lexeme_ids), Lexeme.enriched_at.is_(None)
                )
            )).all()
            assert set(pending_before) == set(lexeme_ids)

        gemini = _ScriptedWorkerGemini()
        await lexicon_enrich_service.enrich(async_session_factory, gemini, lexeme_ids, {})

        async with async_session_factory() as session:
            still_pending = (await session.exec(
                select(Lexeme.id).where(
                    Lexeme.id.in_(lexeme_ids), Lexeme.enriched_at.is_(None)
                )
            )).all()
            assert still_pending == []
            senses = (await session.exec(
                select(LexemeSense).where(LexemeSense.lexeme_id.in_(lexeme_ids))
            )).all()
            assert senses and all(not s.provisional for s in senses)
            assert all(s.cefr == "B2" for s in senses)  # the scripted grade below
    finally:
        await _cleanup(material.id, user.id)
        await _delete_lexemes("inhabitant", "modern-day", "descend", "descending")


@pytest.mark.asyncio
async def test_lexicon_enrich_once_picks_up_a_pending_lexeme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`app.worker._lexicon_enrich_once` -- the worker's own wrapper around
    `enrich` -- actually selects `enriched_at IS NULL` lexemes and finishes
    them, on an isolated lexeme so this holds regardless of whatever else
    `app_test` (shared with every other test file) happens to have pending
    at the moment this runs.

    ``lexicon_enrich_batch_size`` is raised for the call so this lexeme --
    freshly created and therefore the NEWEST by `created_at`, the column the
    wrapper orders by -- is not pushed out of a small batch by older pending
    rows some other test left behind.
    """
    tag = uuid.uuid4().hex[:8]
    lemma = f"wrapword{tag}"
    monkeypatch.setattr(worker_module.settings, "lexicon_enrich_batch_size", 1000)
    try:
        async with async_session_factory() as session:
            row = _row(lemma=lemma, pos="n", meaning_en="a wrapper test word",
                        meaning_uz="test so'zi", cefr_level="B1")
            await lexicon_service.link_row(session, row)
            await session.commit()
            lexeme_id = row.lexeme_id

        gemini = _ScriptedWorkerGemini()
        done = await worker_module._lexicon_enrich_once(gemini, {})
        assert done >= 1

        async with async_session_factory() as session:
            lexeme = await session.get(Lexeme, lexeme_id)
            assert lexeme.enriched_at is not None
    finally:
        await _delete_lexemes(lemma)


class _ScriptedWorkerGemini:
    """The minimum a `Gemini`-shaped object needs for
    `app.services.lexicon_enrich.enrich` to finish a lexeme with no real
    network call -- every step answers something valid and deterministic,
    the same role `test_lexicon_enrich.py`'s own `ScriptedGemini` plays for
    P2's CLI runner."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def ask(self, model, prompt, *, step, max_tokens=0, repair_flat=False):
        self.calls.append(step)
        keys = __import__("re").findall(r"^(k\d+):", prompt, __import__("re").M)
        if step == "match":
            return {"words": []}
        if step == "cefr":
            return {"levels": {k: "B2" for k in keys}}
        if step == "translate":
            return {"uz": {k: "so'z" for k in keys}}
        if step == "judge":
            return {"verdicts": {k: {"verdict": "same", "better": "both"} for k in keys}}
        return None

    async def aclose(self) -> None:
        pass
