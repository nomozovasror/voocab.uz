"""How an attempt was worked, not just how it scored (brief §54, §71).

Two halves. The pure functions that cross what the learner played against
where the author said the answers are — testable without a database, and the
place where the interesting judgements live ("half of the moment counts as
hearing it"). Then the round trip: submit with timing, read it back off the
rows, and fetch the whole result again by id the way a refreshed results page
would.

The security assertion in here is the one about ownership: an attempt is a
record of somebody's mistakes, and the material's author is not entitled to it
either.
"""

import uuid

import httpx
import pytest
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.attempt import Attempt
from app.models.audio_asset import AudioAsset
from app.models.audio_blob import AudioBlob, TranscriptStatus
from app.models.audio_segment import AudioSegment
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import QuestionGroup
from app.models.user import User
from app.schemas.listening import ListenedSpanIn
from app.services import grading as grading_service


def _span(start: int, end: int) -> ListenedSpanIn:
    return ListenedSpanIn(start_ms=start, end_ms=end)


# --- Crossing playback with the author's marks -------------------------------


def test_a_play_that_covers_the_moment_counts_as_hearing_it() -> None:
    assert grading_service.count_hearings([_span(0, 30_000)], [(10_000, 12_000)]) == 1


def test_the_same_stretch_played_twice_counts_twice() -> None:
    """The reason the client is told NOT to merge its spans: two identical
    plays are the signal."""
    spans = [_span(10_000, 13_000), _span(10_000, 13_000)]
    assert grading_service.count_hearings(spans, [(10_000, 12_000)]) == 2


def test_scrubbing_past_the_moment_is_not_hearing_it() -> None:
    """A play that clips the last 400ms of a 2s answer heard a syllable."""
    assert grading_service.count_hearings([_span(11_600, 14_000)], [(10_000, 12_000)]) == 0


def test_half_the_moment_is_enough() -> None:
    """Playback that started mid-sentence still heard the answer."""
    assert grading_service.count_hearings([_span(11_000, 20_000)], [(10_000, 12_000)]) == 1


def test_a_play_that_misses_the_moment_entirely_counts_nothing() -> None:
    assert grading_service.count_hearings([_span(0, 5_000)], [(10_000, 12_000)]) == 0


def test_a_question_with_no_marked_range_has_no_hearings() -> None:
    """Nothing to cross against isn't zero listening — but zero is the only
    honest number here, and the column is NULL when nothing was reported at
    all, which is the distinction that matters."""
    assert grading_service.count_hearings([_span(0, 60_000)], []) == 0


def test_either_half_of_a_two_letter_answer_counts() -> None:
    """A "choose TWO" is answered in two places. They are kept apart rather
    than flattened into the span enclosing both — otherwise the minute of
    unrelated audio between them would count as the question's moment."""
    ranges = [(10_000, 12_000), (70_000, 72_000)]
    assert grading_service.count_hearings([_span(69_000, 75_000)], ranges) == 1
    assert grading_service.count_hearings([_span(30_000, 40_000)], ranges) == 0


def test_a_marked_point_is_heard_by_a_play_that_reaches_it() -> None:
    """A zero-length range would make "at least half the overlap" trivially
    true for every span, so it is handled as containment instead."""
    assert grading_service.count_hearings([_span(0, 30_000)], [(10_000, 10_000)]) == 1
    assert grading_service.count_hearings([_span(0, 5_000)], [(10_000, 10_000)]) == 0


def test_listened_ms_counts_overlapping_plays_once() -> None:
    """Three plays of the same minute is one minute of the recording heard."""
    spans = [_span(0, 60_000), _span(0, 60_000), _span(30_000, 90_000)]
    assert grading_service.merged_ms(spans) == 90_000


def test_listened_ms_adds_separate_stretches() -> None:
    assert grading_service.merged_ms([_span(0, 1_000), _span(5_000, 6_000)]) == 2_000


def test_listened_ms_of_nothing_is_zero() -> None:
    assert grading_service.merged_ms([]) == 0


def test_spans_must_run_forwards() -> None:
    with pytest.raises(ValueError):
        ListenedSpanIn(start_ms=5_000, end_ms=4_000)


# --- Which transcript lines an answer's moment falls in -----------------------


_LINES = [
    {"start_ms": 0, "end_ms": 5_000, "text": "first"},
    {"start_ms": 5_000, "end_ms": 10_000, "text": "second"},
    {"start_ms": 10_000, "end_ms": 15_000, "text": "third"},
]


def test_transcript_returns_the_line_the_moment_lands_in() -> None:
    got = grading_service.transcript_across(_LINES, [(6_000, 8_000)])
    assert [line["text"] for line in got] == ["second"]


def test_transcript_spans_every_line_the_moment_crosses() -> None:
    got = grading_service.transcript_across(_LINES, [(4_000, 11_000)])
    assert [line["text"] for line in got] == ["first", "second", "third"]


def test_a_range_snapped_to_a_line_edge_does_not_drag_in_the_line_before() -> None:
    """Authors mark ranges by snapping to segment boundaries, so overlap has
    to be strict — otherwise every marked answer would quote the preceding
    sentence too."""
    got = grading_service.transcript_across(_LINES, [(5_000, 10_000)])
    assert [line["text"] for line in got] == ["second"]


def test_a_line_covered_by_two_moments_appears_once() -> None:
    got = grading_service.transcript_across(_LINES, [(6_000, 7_000), (8_000, 9_000)])
    assert [line["text"] for line in got] == ["second"]


def test_no_marked_range_quotes_nothing() -> None:
    assert grading_service.transcript_across(_LINES, []) == []


# --- Fixtures for the round trip ---------------------------------------------


async def _make_user(email: str) -> User:
    async with async_session_factory() as session:
        user = (await session.exec(select(User).where(User.email == email))).first()
        if user is not None:
            return user
        user = User(email=email, display_name=f"Timing test {email}")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def _make_audio(owner_id: uuid.UUID) -> AudioAsset:
    """A recording with a two-line transcript, the second line corrected by
    its owner. The correction is what the review must quote."""
    async with async_session_factory() as session:
        blob = AudioBlob(
            sha256=f"timing-{uuid.uuid4().hex}",
            storage_key=f"audio/{uuid.uuid4().hex}.mp3",
            size_bytes=10,
            mime_type="audio/mpeg",
            transcript_status=TranscriptStatus.READY,
            duration_ms=30_000,
        )
        session.add(blob)
        await session.commit()
        await session.refresh(blob)

        for index, (start, end, text) in enumerate(
            [(0, 10_000, "the machine heard this"), (10_000, 20_000, "wrong guess")]
        ):
            session.add(
                AudioSegment(
                    blob_id=blob.id,
                    order_index=index,
                    start_ms=start,
                    end_ms=end,
                    text=text,
                    words=[],
                )
            )
        asset = AudioAsset(
            owner_id=owner_id,
            blob_id=blob.id,
            title="Timing fixture",
            transcript_overrides={"1": "the author fixed this"},
        )
        session.add(asset)
        await session.commit()
        await session.refresh(asset)
        return asset


async def _make_material(author_id: uuid.UUID, asset_id: uuid.UUID | None) -> Material:
    async with async_session_factory() as session:
        material = Material(
            author_id=author_id,
            type="listening",
            title=f"Timing fixture {uuid.uuid4()}",
            visibility="public",
            audio_asset_id=asset_id,
        )
        session.add(material)
        await session.commit()
        await session.refresh(material)
        return material


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _seed_two_gaps(
    client: httpx.AsyncClient, token: str, material_id: uuid.UUID
) -> list[dict]:
    """Two gaps: the first answered at 2–4s (in the ASR's own line), the
    second at 12–14s (in the line the author corrected)."""
    r_part = await client.post(
        f"/api/materials/{material_id}/parts",
        json={"order_index": 0, "title": "Part 1"},
        cookies={"access_token": token},
    )
    assert r_part.status_code == 201, r_part.text
    part_id = r_part.json()["id"]

    r_group = await client.post(
        f"/api/parts/{part_id}/question-groups",
        json={
            "type": "form_completion",
            "instructions": "Complete the form.",
            "config": {"template": "1: {{1}}\n2: {{2}}"},
            "questions": [
                {
                    "number": 1,
                    "correct_answers": ["alpha"],
                    "replay_start_ms": 2_000,
                    "replay_end_ms": 4_000,
                },
                {
                    "number": 2,
                    "correct_answers": ["beta"],
                    "replay_start_ms": 12_000,
                    "replay_end_ms": 14_000,
                },
            ],
        },
        cookies={"access_token": token},
    )
    assert r_group.status_code == 201, r_group.text

    # Authoring writes re-check the publishing rules and would demote this
    # half-built material, so the flag is set after the seeding.
    async with async_session_factory() as session:
        material = await session.get(Material, material_id)
        assert material is not None
        material.visibility = "public"
        session.add(material)
        await session.commit()

    return r_group.json()["questions"]


async def _cleanup(material_id: uuid.UUID, *emails: str) -> None:
    async with async_session_factory() as session:
        attempts = (
            await session.exec(
                select(Attempt).where(Attempt.material_id == material_id)
            )
        ).all()
        for attempt in attempts:
            for qa in (
                await session.exec(
                    select(QuestionAttempt).where(
                        QuestionAttempt.attempt_id == attempt.id
                    )
                )
            ).all():
                await session.delete(qa)
        await session.flush()
        for attempt in attempts:
            await session.delete(attempt)
        await session.flush()

        for part in (
            await session.exec(select(Part).where(Part.material_id == material_id))
        ).all():
            groups = (
                await session.exec(
                    select(QuestionGroup).where(QuestionGroup.part_id == part.id)
                )
            ).all()
            for group in groups:
                for question in (
                    await session.exec(
                        select(Question).where(Question.group_id == group.id)
                    )
                ).all():
                    await session.delete(question)
            await session.flush()
            for group in groups:
                await session.delete(group)
            await session.flush()
            await session.delete(part)
        await session.flush()

        material = await session.get(Material, material_id)
        asset_id = material.audio_asset_id if material else None
        if material is not None:
            await session.delete(material)
        await session.flush()

        if asset_id is not None:
            asset = await session.get(AudioAsset, asset_id)
            if asset is not None:
                blob_id = asset.blob_id
                await session.delete(asset)
                await session.flush()
                for segment in (
                    await session.exec(
                        select(AudioSegment).where(AudioSegment.blob_id == blob_id)
                    )
                ).all():
                    await session.delete(segment)
                await session.flush()
                blob = await session.get(AudioBlob, blob_id)
                if blob is not None:
                    await session.delete(blob)
        await session.commit()

        for email in emails:
            user = (
                await session.exec(select(User).where(User.email == email))
            ).first()
            if user is not None:
                await session.delete(user)
        await session.commit()


# --- The round trip -----------------------------------------------------------


@pytest.mark.asyncio
async def test_submitting_with_timing_records_how_the_attempt_was_worked() -> None:
    email = "t1-learner@example.com"
    user = await _make_user(email)
    asset = await _make_audio(user.id)
    material = await _make_material(user.id, asset.id)
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            questions = await _seed_two_gaps(client, token, material.id)

            r = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        {
                            "question_id": questions[0]["id"],
                            "given_answer": "alpha",
                            "timing": {
                                "first_answered_ms": 8_000,
                                "last_changed_ms": 9_500,
                                "changes": 2,
                                "focus_ms": 4_200,
                            },
                        },
                        {
                            "question_id": questions[1]["id"],
                            "given_answer": "wrong",
                            "timing": {
                                "first_answered_ms": 20_000,
                                "last_changed_ms": 20_000,
                                "changes": 0,
                                "focus_ms": 1_100,
                            },
                        },
                    ],
                    # The first answer's moment (2–4s) played twice; the
                    # second's (12–14s) never.
                    "listened": [
                        {"start_ms": 0, "end_ms": 10_000},
                        {"start_ms": 0, "end_ms": 6_000},
                    ],
                    "seeks_back": 3,
                    "elapsed_ms": 45_000,
                },
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text

            async with async_session_factory() as session:
                attempt = (
                    await session.exec(
                        select(Attempt).where(Attempt.material_id == material.id)
                    )
                ).one()
                assert attempt.time_spent_ms == 45_000
                assert attempt.seeks_back == 3
                # Overlapping plays counted once: 0–10s, not 16s.
                assert attempt.listened_ms == 10_000
                # started_at is derived from the server's clock minus the
                # reported duration, so the session no longer looks
                # instantaneous.
                assert (attempt.submitted_at - attempt.started_at).total_seconds() >= 44

                rows = {
                    str(row.question_id): row
                    for row in (
                        await session.exec(
                            select(QuestionAttempt).where(
                                QuestionAttempt.attempt_id == attempt.id
                            )
                        )
                    ).all()
                }

            first = rows[questions[0]["id"]]
            assert first.first_answered_ms == 8_000
            assert first.last_changed_ms == 9_500
            assert first.changes == 2
            assert first.focus_ms == 4_200
            assert first.hearings == 2

            second = rows[questions[1]["id"]]
            assert second.focus_ms == 1_100
            assert second.hearings == 0
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_client_that_reports_nothing_is_graded_the_same_and_measured_none() -> None:
    """NULL means "not measured". Defaulting these to 0 would have every
    attempt from before this feature claim the learner never pressed play."""
    email = "t2-learner@example.com"
    user = await _make_user(email)
    material = await _make_material(user.id, None)
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            questions = await _seed_two_gaps(client, token, material.id)

            r = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        {"question_id": questions[0]["id"], "given_answer": "alpha"}
                    ]
                },
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            assert r.json()["score"] == 1

            async with async_session_factory() as session:
                attempt = (
                    await session.exec(
                        select(Attempt).where(Attempt.material_id == material.id)
                    )
                ).one()
                assert attempt.listened_ms is None
                assert attempt.seeks_back is None
                rows = (
                    await session.exec(
                        select(QuestionAttempt).where(
                            QuestionAttempt.attempt_id == attempt.id
                        )
                    )
                ).all()
                assert all(row.first_answered_ms is None for row in rows)
                assert all(row.changes is None for row in rows)
                assert all(row.hearings is None for row in rows)
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_the_result_quotes_the_authors_transcript_not_the_machines() -> None:
    email = "t3-learner@example.com"
    user = await _make_user(email)
    asset = await _make_audio(user.id)
    material = await _make_material(user.id, asset.id)
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            questions = await _seed_two_gaps(client, token, material.id)

            r = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        {"question_id": questions[0]["id"], "given_answer": "alpha"},
                        {"question_id": questions[1]["id"], "given_answer": "beta"},
                    ]
                },
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            results = {row["number"]: row for row in r.json()["results"]}

            # 2–4s falls in the untouched first line.
            assert [line["text"] for line in results[1]["transcript"]] == [
                "the machine heard this"
            ]
            # 12–14s falls in the line the author corrected. Quoting the ASR's
            # "wrong guess" would show the learner a transcript that
            # contradicts the answer key written against the correction.
            assert [line["text"] for line in results[2]["transcript"]] == [
                "the author fixed this"
            ]
            assert results[2]["transcript"][0]["start_ms"] == 10_000
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_a_material_with_no_transcript_still_grades() -> None:
    """Practice doesn't wait for the ASR. A review with nothing to quote is an
    ordinary state, not a failure."""
    email = "t4-learner@example.com"
    user = await _make_user(email)
    material = await _make_material(user.id, None)
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            questions = await _seed_two_gaps(client, token, material.id)
            r = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        {"question_id": questions[0]["id"], "given_answer": "alpha"}
                    ]
                },
                cookies={"access_token": token},
            )
            assert r.status_code == 200, r.text
            assert all(row["transcript"] == [] for row in r.json()["results"])
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_fetching_an_attempt_by_id_returns_what_the_submit_returned() -> None:
    """The refresh key. A results page reached by reloading the URL is the
    same page as the one reached by pressing submit."""
    email = "t5-learner@example.com"
    user = await _make_user(email)
    asset = await _make_audio(user.id)
    material = await _make_material(user.id, asset.id)
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            questions = await _seed_two_gaps(client, token, material.id)
            posted = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        {"question_id": questions[0]["id"], "given_answer": " Alpha "},
                        {"question_id": questions[1]["id"], "given_answer": "nope"},
                    ]
                },
                cookies={"access_token": token},
            )
            assert posted.status_code == 200, posted.text
            body = posted.json()

            fetched = await client.get(
                f"/api/attempts/{body['attempt_id']}",
                cookies={"access_token": token},
            )
            assert fetched.status_code == 200, fetched.text
            assert fetched.json() == body

            assert body["material_title"] == material.title
            assert body["score"] == 1
            assert body["total_questions"] == 2
            # What the learner typed, kept raw — normalization is for
            # comparison only.
            given = {row["number"]: row["given_answer"] for row in body["results"]}
            assert given == {1: " Alpha ", 2: "nope"}
    finally:
        await _cleanup(material.id, email)


@pytest.mark.asyncio
async def test_an_attempt_belongs_to_whoever_made_it_not_to_the_author() -> None:
    """404 rather than 403: whether a given attempt id exists is itself a fact
    about another person's practice."""
    author_email = "t6-author@example.com"
    learner_email = "t6-learner@example.com"
    author = await _make_user(author_email)
    learner = await _make_user(learner_email)
    material = await _make_material(author.id, None)
    author_token = create_access_token(str(author.id))
    learner_token = create_access_token(str(learner.id))

    try:
        async with _client() as client:
            questions = await _seed_two_gaps(client, author_token, material.id)
            posted = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [
                        {"question_id": questions[0]["id"], "given_answer": "alpha"}
                    ]
                },
                cookies={"access_token": learner_token},
            )
            assert posted.status_code == 200, posted.text
            attempt_id = posted.json()["attempt_id"]

            # The author owns the material and still cannot read the attempt.
            denied = await client.get(
                f"/api/attempts/{attempt_id}", cookies={"access_token": author_token}
            )
            assert denied.status_code == 404

            missing = await client.get(
                f"/api/attempts/{uuid.uuid4()}",
                cookies={"access_token": learner_token},
            )
            assert missing.status_code == 404
    finally:
        await _cleanup(material.id, author_email, learner_email)


@pytest.mark.asyncio
async def test_more_listened_spans_than_the_cap_is_refused() -> None:
    """A cap rather than trust: a broken client should not be able to post a
    megabyte of playback spans."""
    email = "t7-learner@example.com"
    user = await _make_user(email)
    material = await _make_material(user.id, None)
    token = create_access_token(str(user.id))

    try:
        async with _client() as client:
            await _seed_two_gaps(client, token, material.id)
            r = await client.post(
                f"/api/materials/{material.id}/attempts",
                json={
                    "answers": [],
                    "listened": [
                        {"start_ms": i, "end_ms": i + 1} for i in range(501)
                    ],
                },
                cookies={"access_token": token},
            )
            assert r.status_code == 422
    finally:
        await _cleanup(material.id, email)
