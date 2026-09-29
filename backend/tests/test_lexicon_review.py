"""Studio's admin review tab (`app.api.lexicon`, `app.services.lexicon_review`)
and the public licences page (`app.services.lexicon_licences`) --
`brief-lexicon.md` §6.2, §9.

Real DB, ASGI transport + minted cookie, same pattern as
`test_studio_stats.py`. Every fixture is tagged with a fresh uuid so this
file can run beside whatever else the test database already holds, and
assertions about shared aggregates (the reason counts, the licences page)
are written as "our row is present with the right shape", never as an exact
total over the whole table.
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
from app.models.vocabulary import LookupEvent, MaterialVocabulary, SavedWord


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _make_user(*, admin: bool) -> User:
    async with async_session_factory() as session:
        user = User(
            email=f"lexicon-review-{uuid.uuid4().hex}@test.local",
            display_name="review test",
            is_admin=admin,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_lexeme(tag: str, **kwargs) -> Lexeme:
    async with async_session_factory() as session:
        lexeme = Lexeme(lemma=f"lex{tag}", pos="n", **kwargs)
        session.add(lexeme)
        await session.commit()
        await session.refresh(lexeme)
        return lexeme


async def _make_sense(lexeme_id: uuid.UUID, **kwargs) -> LexemeSense:
    async with async_session_factory() as session:
        sense = LexemeSense(lexeme_id=lexeme_id, **kwargs)
        session.add(sense)
        await session.commit()
        await session.refresh(sense)
        return sense


async def _cleanup(
    *,
    lexeme_ids: tuple[uuid.UUID, ...] = (),
    material_ids: tuple[uuid.UUID, ...] = (),
    user_ids: tuple[uuid.UUID, ...] = (),
) -> None:
    async with async_session_factory() as session:
        for material_id in material_ids:
            for row in (
                await session.exec(
                    select(MaterialVocabulary).where(
                        MaterialVocabulary.material_id == material_id
                    )
                )
            ).all():
                await session.delete(row)
            await session.flush()
            for part in (
                await session.exec(select(Part).where(Part.material_id == material_id))
            ).all():
                await session.delete(part)
            await session.flush()
            material = await session.get(Material, material_id)
            if material is not None:
                await session.delete(material)
        await session.flush()

        for lexeme_id in lexeme_ids:
            for sense in (
                await session.exec(
                    select(LexemeSense).where(LexemeSense.lexeme_id == lexeme_id)
                )
            ).all():
                await session.delete(sense)
            await session.flush()
            lexeme = await session.get(Lexeme, lexeme_id)
            if lexeme is not None:
                await session.delete(lexeme)
        await session.flush()

        for user_id in user_ids:
            user = await session.get(User, user_id)
            if user is not None:
                await session.delete(user)
        await session.commit()


@pytest.mark.asyncio
async def test_review_endpoints_403_for_non_admin() -> None:
    user = await _make_user(admin=False)
    token = create_access_token(str(user.id))
    try:
        async with _client() as client:
            cookies = {"access_token": token}
            r = await client.get("/api/admin/lexicon/review", cookies=cookies)
            assert r.status_code == 403

            r = await client.post(
                f"/api/admin/lexicon/review/{uuid.uuid4()}/approve", cookies=cookies
            )
            assert r.status_code == 403

            r = await client.post(
                f"/api/admin/lexicon/review/{uuid.uuid4()}/fix",
                json={"meaning_uz": "x"},
                cookies=cookies,
            )
            assert r.status_code == 403
    finally:
        await _cleanup(user_ids=(user.id,))


@pytest.mark.asyncio
async def test_queue_priority_pos_mismatch_then_needs_review_then_core() -> None:
    admin = await _make_user(admin=True)
    token = create_access_token(str(admin.id))
    tag = uuid.uuid4().hex[:8]

    # A: rank-1, needs_review, pos_mismatch -- must sort first.
    lex_a = await _make_lexeme(f"a{tag}", frequency_band="wider", frequency_source="ngsl")
    sense_a = await _make_sense(
        lex_a.id, sense_rank=1, definition_en="def a", meaning_uz="uz a",
        needs_review=True, review_reasons=["pos_mismatch"],
    )
    # B: rank-1, needs_review for an unrelated reason -- sorts after A.
    lex_b = await _make_lexeme(f"b{tag}", frequency_band="wider", frequency_source="ngsl")
    sense_b = await _make_sense(
        lex_b.id, sense_rank=1, definition_en="def b", meaning_uz="uz b",
        needs_review=True, review_reasons=["judge_unsure"],
    )
    # C: rank-1, never flagged, never approved, core-frequency -- the core
    # bucket, sorting after every needs_review row.
    lex_c = await _make_lexeme(f"c{tag}", frequency_band="core", frequency_source="ngsl")
    sense_c = await _make_sense(
        lex_c.id, sense_rank=1, definition_en="def c", meaning_uz="uz c",
        needs_review=False,
    )

    try:
        async with _client() as client:
            cookies = {"access_token": token}
            r = await client.get(
                "/api/admin/lexicon/review", params={"limit": 200}, cookies=cookies
            )
            assert r.status_code == 200, r.text
            body = r.json()
            ids = [row["sense_id"] for row in body["rows"]]
            assert str(sense_a.id) in ids and str(sense_b.id) in ids and str(sense_c.id) in ids
            i_a, i_b, i_c = ids.index(str(sense_a.id)), ids.index(str(sense_b.id)), ids.index(str(sense_c.id))
            assert i_a < i_b < i_c

            assert body["reason_counts"]["pos_mismatch"] >= 1
            assert body["reason_counts"]["judge_unsure"] >= 1
            assert body["core_pending"] >= 1

            row_c = body["rows"][i_c]
            assert row_c["lemma"] == lex_c.lemma
            assert row_c["frequency_band"] == "core"
            assert row_c["approved_at"] is None

            # Filtering by reason narrows to exactly that reason.
            r = await client.get(
                "/api/admin/lexicon/review",
                params={"reason": "pos_mismatch", "limit": 200},
                cookies=cookies,
            )
            assert r.status_code == 200
            filtered_ids = [row["sense_id"] for row in r.json()["rows"]]
            assert str(sense_a.id) in filtered_ids
            assert str(sense_b.id) not in filtered_ids
            assert str(sense_c.id) not in filtered_ids

            # The synthetic "core" filter isolates the second bucket.
            r = await client.get(
                "/api/admin/lexicon/review",
                params={"reason": "core", "limit": 200},
                cookies=cookies,
            )
            assert r.status_code == 200
            core_ids = [row["sense_id"] for row in r.json()["rows"]]
            assert str(sense_c.id) in core_ids
            assert str(sense_a.id) not in core_ids

            # An unknown reason is a 422, not a silently empty page.
            r = await client.get(
                "/api/admin/lexicon/review",
                params={"reason": "not_a_real_reason"},
                cookies=cookies,
            )
            assert r.status_code == 422
    finally:
        await _cleanup(
            lexeme_ids=(lex_a.id, lex_b.id, lex_c.id), user_ids=(admin.id,)
        )


@pytest.mark.asyncio
async def test_approve_clears_needs_review_and_records_reviewer() -> None:
    admin = await _make_user(admin=True)
    token = create_access_token(str(admin.id))
    tag = uuid.uuid4().hex[:8]
    lexeme = await _make_lexeme(f"appr{tag}", frequency_band="wider", frequency_source="ngsl")
    sense = await _make_sense(
        lexeme.id, sense_rank=1, definition_en="def", meaning_uz="uz",
        needs_review=True, review_reasons=["judge_unsure"],
    )

    try:
        async with _client() as client:
            r = await client.post(
                f"/api/admin/lexicon/review/{sense.id}/approve",
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["needs_review"] is False
            assert body["approved_by"] == str(admin.id)
            assert body["approved_at"] is not None
            # The reasons stay, as the audit trail of what was once flagged.
            assert body["review_reasons"] == ["judge_unsure"]

        async with async_session_factory() as session:
            refreshed = await session.get(LexemeSense, sense.id)
            assert refreshed is not None
            assert refreshed.needs_review is False
            assert refreshed.approved_by == admin.id
            assert refreshed.approved_at is not None
    finally:
        await _cleanup(lexeme_ids=(lexeme.id,), user_ids=(admin.id,))


@pytest.mark.asyncio
async def test_fix_edits_fields_approves_and_updates_lexeme_cefr() -> None:
    admin = await _make_user(admin=True)
    token = create_access_token(str(admin.id))
    tag = uuid.uuid4().hex[:8]
    lexeme = await _make_lexeme(
        f"fix{tag}", frequency_band="core", frequency_source="ngsl", cefr="B1"
    )
    sense = await _make_sense(
        lexeme.id, sense_rank=1, definition_en="old def", meaning_uz="old uz",
        cefr="B1", needs_review=True, review_reasons=["ngsl_conflict"],
    )

    try:
        async with _client() as client:
            r = await client.post(
                f"/api/admin/lexicon/review/{sense.id}/fix",
                json={"meaning_uz": "new uz", "definition_en": "new def", "cefr": "A2"},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["meaning_uz"] == "new uz"
            assert body["definition_en"] == "new def"
            assert body["cefr"] == "A2"
            assert body["needs_review"] is False
            assert body["approved_by"] == str(admin.id)

        async with async_session_factory() as session:
            refreshed_lexeme = await session.get(Lexeme, lexeme.id)
            assert refreshed_lexeme is not None
            # sense_rank == 1: the lexeme's own denormalised cefr follows.
            assert refreshed_lexeme.cefr == "A2"

            # An unknown CEFR level is refused before anything is written.
        async with _client() as client:
            r = await client.post(
                f"/api/admin/lexicon/review/{sense.id}/fix",
                json={"cefr": "Z9"},
                cookies={"access_token": token},
            )
            assert r.status_code == 422
    finally:
        await _cleanup(lexeme_ids=(lexeme.id,), user_ids=(admin.id,))


@pytest.mark.asyncio
async def test_review_contexts_peek_at_material_sentences() -> None:
    admin = await _make_user(admin=True)
    token = create_access_token(str(admin.id))
    tag = uuid.uuid4().hex[:8]
    lexeme = await _make_lexeme(f"ctx{tag}", frequency_band="wider", frequency_source="ngsl")
    sense = await _make_sense(
        lexeme.id, sense_rank=1, definition_en="def", meaning_uz="uz",
    )

    async with async_session_factory() as session:
        author = User(email=f"ctx-author-{tag}@test.local", display_name="ctx author")
        session.add(author)
        await session.flush()
        material = Material(
            author_id=author.id, type="reading", title=f"ctx material {tag}",
            visibility="private",
        )
        session.add(material)
        await session.flush()
        part = Part(
            material_id=material.id, order_index=0, title="P",
            passage={"paragraphs": []}, first_number=1,
        )
        session.add(part)
        await session.flush()
        session.add(MaterialVocabulary(
            material_id=material.id, part_id=part.id, lemma=f"ctx{tag}",
            surface="ctx-surface", pos="n", meaning_en="m", meaning_uz="uz",
            example="A sentence using ctx-surface.", cefr_level="B1",
            lexeme_id=lexeme.id, sense_id=sense.id,
        ))
        await session.commit()

    try:
        async with _client() as client:
            r = await client.get(
                f"/api/admin/lexicon/review/{sense.id}/contexts",
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert len(body) == 1
            assert body[0]["material_title"] == material.title
            assert body[0]["surface"] == "ctx-surface"
            assert "ctx-surface" in body[0]["example"]
    finally:
        await _cleanup(
            lexeme_ids=(lexeme.id,),
            material_ids=(material.id,),
            user_ids=(admin.id, author.id),
        )


@pytest.mark.asyncio
async def test_licences_page_is_generated_and_public() -> None:
    tag = uuid.uuid4().hex[:8]
    lex_ngsl = await _make_lexeme(f"lic-ngsl{tag}", frequency_source="ngsl", frequency_band="core")
    lex_offlist = await _make_lexeme(f"lic-off{tag}", frequency_source="off-list")
    sense = await _make_sense(
        lex_ngsl.id, sense_rank=1, definition_en="def", meaning_uz="uz",
        source_id="oewn", licence="cc-by-4.0", oewn_synset_id="oewn-test-1-n", oewn_rank=1,
    )

    try:
        # No auth cookie at all -- the page is public.
        async with _client() as client:
            r = await client.get("/api/licences")
            assert r.status_code == 200, r.text
            body = r.json()
            by_key = {row["key"]: row for row in body["sources"]}

            assert "ngsl" in by_key
            assert by_key["ngsl"]["authors"] == "Browne, C., Culligan, B. & Phillips, J."
            assert by_key["ngsl"]["licence_name"] == "CC BY-SA 4.0"
            assert by_key["ngsl"]["licence_url"].startswith("https://creativecommons.org/licenses/by-sa/")
            assert by_key["ngsl"]["count"] >= 1
            assert by_key["ngsl"]["usage_note"] == ""

            assert "oewn" in by_key
            assert by_key["oewn"]["authors"] == "Open English WordNet Team"
            assert by_key["oewn"]["licence_name"] == "CC BY 4.0"
            assert by_key["oewn"]["count"] >= 1

            # off-list and model are not third-party sources -- never listed.
            assert "off-list" not in by_key
            assert "model" not in by_key

            # (B) Princeton WordNet 3.1's SemCor counts appear ONLY because a
            # sense's `oewn_rank` is actually non-null in this deployment's
            # data -- generated, not a permanent hand-written row.
            assert "wordnet-semcor" in by_key
            wn = by_key["wordnet-semcor"]
            assert wn["title"] == "Princeton WordNet 3.1 — SemCor sense frequencies"
            assert wn["authors"] == "Princeton University"
            assert wn["licence_name"] == "WordNet 3.1 licence"
            assert wn["licence_url"] == "https://wordnet.princeton.edu/license-and-commercial-use"
            assert wn["usage_note"] == "Sense ordering only, not stored as definitions."
            assert wn["count"] >= 1
    finally:
        await _cleanup(lexeme_ids=(lex_ngsl.id, lex_offlist.id))


# --- P4: "this translation is wrong" reports lead the queue -----------------


@pytest.mark.asyncio
async def test_a_reported_sense_leads_the_queue_and_carries_its_notes() -> None:
    """An open report outranks even a `pos_mismatch` `needs_review` row --
    a learner already did the finding a reviewer would otherwise have to do
    themselves."""
    admin = await _make_user(admin=True)
    reporter = await _make_user(admin=False)
    token = create_access_token(str(admin.id))
    tag = uuid.uuid4().hex[:8]

    lex_reported = await _make_lexeme(
        f"rep{tag}", frequency_band="wider", frequency_source="ngsl"
    )
    sense_reported = await _make_sense(
        lex_reported.id, sense_rank=1, definition_en="def reported",
        meaning_uz="uz reported", needs_review=False,
    )
    lex_flagged = await _make_lexeme(
        f"flag{tag}", frequency_band="wider", frequency_source="ngsl"
    )
    sense_flagged = await _make_sense(
        lex_flagged.id, sense_rank=1, definition_en="def flagged",
        meaning_uz="uz flagged", needs_review=True,
        review_reasons=["pos_mismatch"],
    )

    async with async_session_factory() as session:
        session.add(TranslationReport(
            user_id=reporter.id, lexeme_sense_id=sense_reported.id,
            source="word_page", note="this is not what it means",
        ))
        await session.commit()

    try:
        async with _client() as client:
            cookies = {"access_token": token}
            r = await client.get(
                "/api/admin/lexicon/review", params={"limit": 200}, cookies=cookies
            )
            assert r.status_code == 200, r.text
            body = r.json()
            ids = [row["sense_id"] for row in body["rows"]]
            i_reported = ids.index(str(sense_reported.id))
            i_flagged = ids.index(str(sense_flagged.id))
            assert i_reported < i_flagged
            assert body["reported_pending"] >= 1

            row = body["rows"][i_reported]
            assert row["report_count"] == 1
            assert row["report_notes"] == ["this is not what it means"]

            # The synthetic "reported" filter isolates exactly this bucket.
            r = await client.get(
                "/api/admin/lexicon/review",
                params={"reason": "reported", "limit": 200},
                cookies=cookies,
            )
            assert r.status_code == 200
            reported_ids = [row["sense_id"] for row in r.json()["rows"]]
            assert str(sense_reported.id) in reported_ids
            assert str(sense_flagged.id) not in reported_ids

            # Approving closes the report -- it no longer leads the queue.
            approved = await client.post(
                f"/api/admin/lexicon/review/{sense_reported.id}/approve",
                cookies=cookies,
            )
            assert approved.status_code == 200
            assert approved.json()["report_count"] == 0

        async with async_session_factory() as session:
            refreshed = (
                await session.exec(
                    select(TranslationReport).where(
                        TranslationReport.lexeme_sense_id == sense_reported.id
                    )
                )
            ).one()
            assert refreshed.status == "resolved"
            assert refreshed.resolved_at is not None
    finally:
        async with async_session_factory() as session:
            for row in (
                await session.exec(
                    select(TranslationReport).where(
                        TranslationReport.lexeme_sense_id == sense_reported.id
                    )
                )
            ).all():
                await session.delete(row)
            await session.commit()
        await _cleanup(
            lexeme_ids=(lex_reported.id, lex_flagged.id),
            user_ids=(admin.id, reporter.id),
        )


# --- A1: exposure orders the non-reported bucket -----------------------------


async def _make_material_entry(
    author_id: uuid.UUID, *, lemma: str, sense_id: uuid.UUID, lexeme_id: uuid.UUID,
) -> tuple[Material, MaterialVocabulary]:
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id, type="reading",
            title=f"exposure fixture {uuid.uuid4()}", visibility="public",
        )
        session.add(material)
        await session.flush()
        part = Part(
            material_id=material.id, order_index=0, title="P",
            passage={"paragraphs": []}, first_number=1,
        )
        session.add(part)
        await session.flush()
        entry = MaterialVocabulary(
            material_id=material.id, part_id=part.id, lemma=lemma, surface=lemma,
            pos="n", meaning_en="m", meaning_uz="uz", example="", cefr_level="B1",
            lexeme_id=lexeme_id, sense_id=sense_id,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(material)
        return material, entry


async def _make_attempt(user_id: uuid.UUID, material_id: uuid.UUID) -> None:
    async with async_session_factory() as session:
        session.add(Attempt(
            user_id=user_id, material_id=material_id,
            status=AttemptStatus.SUBMITTED, score=0, total_questions=0,
        ))
        await session.commit()


async def _make_lookup(user_id: uuid.UUID, material_id: uuid.UUID, lemma: str) -> None:
    async with async_session_factory() as session:
        session.add(LookupEvent(
            user_id=user_id, material_id=material_id, asked=lemma, lemma=lemma,
            source="cache", found=True,
        ))
        await session.commit()


async def _make_save(user_id: uuid.UUID, sense_id: uuid.UUID, lemma: str) -> None:
    async with async_session_factory() as session:
        session.add(SavedWord(user_id=user_id, lemma=lemma, lexeme_sense_id=sense_id))
        await session.commit()


async def _cleanup_exposure_fixtures(
    *, material_ids: tuple[uuid.UUID, ...], sense_ids: tuple[uuid.UUID, ...],
    user_ids: tuple[uuid.UUID, ...],
) -> None:
    async with async_session_factory() as session:
        for sense_id in sense_ids:
            for row in (
                await session.exec(
                    select(SavedWord).where(SavedWord.lexeme_sense_id == sense_id)
                )
            ).all():
                await session.delete(row)
        await session.flush()
        for material_id in material_ids:
            for row in (
                await session.exec(
                    select(LookupEvent).where(LookupEvent.material_id == material_id)
                )
            ).all():
                await session.delete(row)
            for row in (
                await session.exec(
                    select(Attempt).where(Attempt.material_id == material_id)
                )
            ).all():
                await session.delete(row)
        await session.commit()
    await _cleanup(material_ids=material_ids, user_ids=user_ids)


@pytest.mark.asyncio
async def test_exposure_orders_the_non_reported_bucket_and_ties_break_correctly() -> None:
    """Reported still leads; everything else is ONE list by exposure desc,
    a needs_review sense breaking a tie ahead of an unflagged core sense,
    material_count breaking anything left."""
    admin = await _make_user(admin=True)
    reader1 = await _make_user(admin=False)
    reader2 = await _make_user(admin=False)
    reader3 = await _make_user(admin=False)
    token = create_access_token(str(admin.id))
    tag = uuid.uuid4().hex[:8]

    # High exposure, needs_review -- three attempters.
    lex_high = await _make_lexeme(f"high{tag}", frequency_band="wider")
    sense_high = await _make_sense(
        lex_high.id, sense_rank=1, definition_en="d", meaning_uz="u",
        needs_review=True, review_reasons=["judge_unsure"],
    )
    material_high, _ = await _make_material_entry(
        admin.id, lemma=f"high{tag}", sense_id=sense_high.id, lexeme_id=lex_high.id,
    )
    for reader in (reader1, reader2, reader3):
        await _make_attempt(reader.id, material_high.id)

    # Equal (lower) exposure -- one attempter each -- but one is
    # needs_review and the other is an unflagged CORE sense: the flagged
    # one must sort first on the tie.
    lex_flagged = await _make_lexeme(f"tie-flag{tag}", frequency_band="wider")
    sense_flagged = await _make_sense(
        lex_flagged.id, sense_rank=1, definition_en="d", meaning_uz="u",
        needs_review=True, review_reasons=["judge_unsure"],
    )
    material_flagged, _ = await _make_material_entry(
        admin.id, lemma=f"tieflag{tag}", sense_id=sense_flagged.id,
        lexeme_id=lex_flagged.id,
    )
    await _make_attempt(reader1.id, material_flagged.id)

    lex_core = await _make_lexeme(f"tie-core{tag}", frequency_band="core")
    sense_core = await _make_sense(
        lex_core.id, sense_rank=1, definition_en="d", meaning_uz="u",
        needs_review=False,
    )
    material_core, _ = await _make_material_entry(
        admin.id, lemma=f"tiecore{tag}", sense_id=sense_core.id, lexeme_id=lex_core.id,
    )
    await _make_attempt(reader1.id, material_core.id)

    # Lowest exposure of the lot -- zero of everything.
    lex_low = await _make_lexeme(f"low{tag}", frequency_band="wider")
    sense_low = await _make_sense(
        lex_low.id, sense_rank=1, definition_en="d", meaning_uz="u",
        needs_review=True, review_reasons=["judge_unsure"],
    )

    material_ids = (material_high.id, material_flagged.id, material_core.id)
    sense_ids = (sense_high.id, sense_flagged.id, sense_core.id, sense_low.id)
    lexeme_ids = (lex_high.id, lex_flagged.id, lex_core.id, lex_low.id)
    user_ids = (admin.id, reader1.id, reader2.id, reader3.id)
    try:
        async with _client() as client:
            r = await client.get(
                "/api/admin/lexicon/review", params={"limit": 200},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            rows = {row["sense_id"]: row for row in r.json()["rows"]}

            assert rows[str(sense_high.id)]["exposure"] == 3
            assert rows[str(sense_high.id)]["exposure_parts"] == {
                "attempters": 3, "lookups": 0, "saves": 0,
            }
            assert rows[str(sense_flagged.id)]["exposure"] == 1
            assert rows[str(sense_core.id)]["exposure"] == 1
            assert rows[str(sense_low.id)]["exposure"] == 0

            ids = [row["sense_id"] for row in r.json()["rows"]]
            i_high = ids.index(str(sense_high.id))
            i_flagged = ids.index(str(sense_flagged.id))
            i_core = ids.index(str(sense_core.id))
            i_low = ids.index(str(sense_low.id))

            # Exposure descending, above everything else.
            assert i_high < i_flagged
            assert i_high < i_core
            # Equal exposure (1): needs_review sorts before the unflagged
            # core sense.
            assert i_flagged < i_core
            # Zero exposure, and not needs_review's own tie-break winner --
            # last of the four.
            assert i_low > i_flagged and i_low > i_core
    finally:
        await _cleanup_exposure_fixtures(
            material_ids=material_ids, sense_ids=sense_ids, user_ids=user_ids,
        )
        await _cleanup(lexeme_ids=lexeme_ids)


@pytest.mark.asyncio
async def test_exposure_sums_attempters_lookups_and_saves_with_no_weighting() -> None:
    admin = await _make_user(admin=True)
    reader1 = await _make_user(admin=False)
    reader2 = await _make_user(admin=False)
    token = create_access_token(str(admin.id))
    tag = uuid.uuid4().hex[:8]

    lexeme = await _make_lexeme(f"sum{tag}", frequency_band="wider")
    sense = await _make_sense(
        lexeme.id, sense_rank=1, definition_en="d", meaning_uz="u",
        needs_review=True, review_reasons=["judge_unsure"],
    )
    material, _ = await _make_material_entry(
        admin.id, lemma=f"sum{tag}", sense_id=sense.id, lexeme_id=lexeme.id,
    )
    await _make_attempt(reader1.id, material.id)
    await _make_attempt(reader2.id, material.id)
    await _make_lookup(reader1.id, material.id, f"sum{tag}")
    await _make_lookup(reader1.id, material.id, f"sum{tag}")
    await _make_lookup(reader2.id, material.id, f"sum{tag}")
    await _make_save(reader1.id, sense.id, f"sum{tag}")

    try:
        async with _client() as client:
            r = await client.get(
                "/api/admin/lexicon/review", params={"limit": 200},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            row = next(
                row for row in r.json()["rows"] if row["sense_id"] == str(sense.id)
            )
            # 2 attempters + 3 lookups + 1 save = 6, a plain sum, no weights.
            assert row["exposure"] == 6
            assert row["exposure_parts"] == {
                "attempters": 2, "lookups": 3, "saves": 1,
            }
            assert row["material_count"] == 1

            # `approve`'s own response carries the identical figures.
            approved = await client.post(
                f"/api/admin/lexicon/review/{sense.id}/approve",
                cookies={"access_token": token},
            )
            assert approved.status_code == 200
            assert approved.json()["exposure"] == 6
            assert approved.json()["exposure_parts"] == {
                "attempters": 2, "lookups": 3, "saves": 1,
            }
    finally:
        await _cleanup_exposure_fixtures(
            material_ids=(material.id,), sense_ids=(sense.id,),
            user_ids=(admin.id, reader1.id, reader2.id),
        )
        await _cleanup(lexeme_ids=(lexeme.id,))


@pytest.mark.asyncio
async def test_fixing_a_sense_also_closes_its_open_report() -> None:
    admin = await _make_user(admin=True)
    reporter = await _make_user(admin=False)
    token = create_access_token(str(admin.id))
    tag = uuid.uuid4().hex[:8]

    lexeme = await _make_lexeme(f"fixrep{tag}", frequency_band="core", frequency_source="ngsl")
    sense = await _make_sense(
        lexeme.id, sense_rank=1, definition_en="old def", meaning_uz="old uz",
    )
    async with async_session_factory() as session:
        session.add(TranslationReport(
            user_id=reporter.id, lexeme_sense_id=sense.id, source="practice_reveal",
        ))
        await session.commit()

    try:
        async with _client() as client:
            r = await client.post(
                f"/api/admin/lexicon/review/{sense.id}/fix",
                json={"meaning_uz": "new uz"},
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            assert r.json()["report_count"] == 0

        async with async_session_factory() as session:
            refreshed = (
                await session.exec(
                    select(TranslationReport).where(
                        TranslationReport.lexeme_sense_id == sense.id
                    )
                )
            ).one()
            assert refreshed.status == "resolved"
    finally:
        async with async_session_factory() as session:
            for row in (
                await session.exec(
                    select(TranslationReport).where(
                        TranslationReport.lexeme_sense_id == sense.id
                    )
                )
            ).all():
                await session.delete(row)
            await session.commit()
        await _cleanup(lexeme_ids=(lexeme.id,), user_ids=(admin.id, reporter.id))
