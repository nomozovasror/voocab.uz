"""Vocabulary stage 3, the practice side: the three-rung passive ladder,
`listen`, `speak`, the speak check, settings, and On the go."""

import uuid
from datetime import datetime, timedelta, timezone

import fsrs
import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, update
from sqlmodel import select

from app.core.database import async_session_factory
from app.core.security import create_access_token
from app.main import app
from app.models.audio_render import AudioRender, RenderStatus
from app.models.vocabulary import SavedWord, VocabularyReviewLog, VocabularySettings
from app.models.word_audio_log import OnTheGoExposure, SpeakMiss
from app.schemas.vocabulary import (
    PracticeAnswerIn,
    PracticeSessionIn,
    SpeakCheckIn,
    VocabularySettingsIn,
)
from app.services import practice as practice_service
from app.services import tts
from tests.audio_helpers import Created, make_lexeme, make_user, unique_word

DEFINITION = "a thing that people do on every single ordinary day"
NOW = datetime.now(timezone.utc)


@pytest.fixture
async def created():
    made = Created()
    yield made
    async with async_session_factory() as session:
        if made.user_ids:
            await session.execute(
                delete(VocabularyReviewLog).where(VocabularyReviewLog.user_id.in_(made.user_ids))
            )
            await session.execute(delete(SpeakMiss).where(SpeakMiss.user_id.in_(made.user_ids)))
            await session.execute(
                delete(OnTheGoExposure).where(OnTheGoExposure.user_id.in_(made.user_ids))
            )
            await session.execute(
                delete(VocabularySettings).where(VocabularySettings.user_id.in_(made.user_ids))
            )
            await session.commit()
    await made.cleanup()


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _word(created: Created, user, *, level: str = "recall", due: bool = True,
                lemma: str | None = None, definition: str = DEFINITION, **fields) -> SavedWord:
    lexeme, sense = await make_lexeme(created, lemma or unique_word(), definition=definition)
    if due:
        fields.setdefault("status", "review")
        fields.setdefault("passive_state", int(fsrs.State.Review))
        fields.setdefault("passive_stability", 5.0)
        fields.setdefault("passive_difficulty", 5.0)
        fields.setdefault("passive_due", NOW - timedelta(hours=1))
        fields.setdefault("passive_last_review", NOW - timedelta(days=5))
    async with async_session_factory() as session:
        word = SavedWord(
            user_id=user.id, lemma=lexeme.lemma, lexeme_sense_id=sense.id,
            passive_level=level, **fields,
        )
        session.add(word)
        await session.commit()
        await session.refresh(word)
    return word


async def _answer(user, word, exercise_type, given="", **kw):
    async with async_session_factory() as session:
        return await practice_service.record_answer(
            session, user, word_id=word.id, context_id=None, direction="passive",
            exercise_type=exercise_type, given=given, elapsed_ms=1000, **kw,
        )


async def _level(word) -> str:
    async with async_session_factory() as session:
        return (await session.get(SavedWord, word.id)).passive_level


async def _logs(word) -> list[VocabularyReviewLog]:
    async with async_session_factory() as session:
        return list((await session.exec(
            select(VocabularyReviewLog).where(VocabularyReviewLog.saved_word_id == word.id)
            .order_by(VocabularyReviewLog.reviewed_at)
        )).all())


async def _session(user, **kw):
    async with async_session_factory() as session:
        await practice_service.set_daily_minutes(session, user.id, 20)
    async with async_session_factory() as session:
        return await practice_service.build_session(session, user, tz=None, **kw)


async def _ready_audio(created: Created, lemma: str) -> None:
    spec = tts.word_spec(lemma, None)
    created.render_keys.append(spec.key)
    async with async_session_factory() as session:
        await tts.enqueue([spec])
        await session.execute(
            update(AudioRender).where(AudioRender.key == spec.key).values(
                status=RenderStatus.READY, storage_key=tts.storage_key_for(spec.kind, spec.key),
                duration_ms=700,
            )
        )
        await session.commit()


# --- the three-rung ladder ---------------------------------------------------


async def test_recall_promotes_to_listen_after_two_corrects(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall")
    first = await _answer(user, word, "recall", word.lemma)
    assert first["level"] == "recall"
    second = await _answer(user, word, "recall", word.lemma)
    assert second["level"] == "listen" and await _level(word) == "listen"


async def test_a_word_already_at_recall_with_a_streak_promotes_on_its_next_correct(
    created: Created,
) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall")
    async with async_session_factory() as session:
        session.add(VocabularyReviewLog(
            user_id=user.id, saved_word_id=word.id, lemma=word.lemma, direction="passive",
            exercise_type="recall", planned_exercise="recall", rating=int(fsrs.Rating.Good),
            reviewed_at=NOW - timedelta(days=2), state=int(fsrs.State.Review),
        ))
        await session.commit()
    assert (await _answer(user, word, "recall", word.lemma))["level"] == "listen"


async def test_listen_again_demotes_to_recall_and_one_correct_returns(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="listen")
    out = await _answer(user, word, "listen", "wrong answer")
    assert out["level"] == "recall"
    # It has been at `listen`, so ONE correct at recall is enough.
    back = await _answer(user, word, "recall", word.lemma)
    assert back["level"] == "listen"


async def test_recall_again_demotes_to_recognise_and_thresholds_follow_history(
    created: Created,
) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall")
    await _answer(user, word, "recall", word.lemma)
    await _answer(user, word, "recall", word.lemma)          # -> listen
    assert await _level(word) == "listen"
    await _answer(user, word, "listen", "no")                # -> recall
    await _answer(user, word, "recall", "no")                # -> recognise
    assert await _level(word) == "recognise"
    # Has been at recall AND listen: one correct each way.
    assert (await _answer(user, word, "recall", word.lemma, planned_exercise="recognise"))[
        "level"] == "recall"
    assert (await _answer(user, word, "recall", word.lemma))["level"] == "listen"


async def test_a_never_demoted_word_needs_the_full_streak_at_every_rung(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recognise", due=False)
    for _ in range(2):
        await _answer(user, word, "recall", word.lemma)      # planned recognise (fallback)
    assert await _level(word) == "recall"
    await _answer(user, word, "recall", word.lemma)
    assert await _level(word) == "recall"
    await _answer(user, word, "recall", word.lemma)
    assert await _level(word) == "listen"


async def test_hard_never_demotes_the_middle_or_top_rung(created: Created) -> None:
    user = await make_user(created)
    slip = "wrong"
    for level in ("recall", "listen"):
        word = await _word(created, user, level=level, lemma=unique_word() + "ation")
        typo = word.lemma[:-1]  # one letter short: Hard
        out = await _answer(user, word, level if level == "listen" else "recall", typo)
        assert out["rating"] == int(fsrs.Rating.Hard)
        assert await _level(word) == level, slip


async def test_an_easier_recognise_fallback_is_not_promotion_evidence(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall", definition="a b")  # unreadable cue
    for _ in range(3):
        async with async_session_factory() as session:
            from app.services.distractors import option_id
            out = await practice_service.record_answer(
                session, user, word_id=word.id, context_id=None, direction="passive",
                exercise_type="recognise",
                given=option_id(word.id, "a b"), elapsed_ms=10,
            )
        assert out["rating"] == int(fsrs.Rating.Good)
    assert await _level(word) == "recall"


# --- speak rows never touch the ladder ---------------------------------------


async def test_a_speak_row_between_two_recall_answers_does_not_reset_the_streak(
    created: Created,
) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall")
    await _answer(user, word, "recall", word.lemma)
    gave_up = await _answer(user, word, "speak", "", gave_up=True)
    assert gave_up["rating"] == int(fsrs.Rating.Again) and gave_up["level"] == "recall"
    spoken = await _answer(user, word, "speak", word.lemma)
    assert spoken["rating"] == int(fsrs.Rating.Good) and await _level(word) == "recall"
    # The recall streak is still 1: the next correct promotes.
    assert (await _answer(user, word, "recall", word.lemma))["level"] == "listen"


async def test_speak_never_counts_as_reaching_a_rung_or_a_demotion(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="listen")
    await _answer(user, word, "speak", "", gave_up=True)
    assert await _level(word) == "listen"
    logs = await _logs(word)
    assert logs[0].exercise_type == "speak" and logs[0].planned_exercise == "speak"
    # The typing fallback of a speak card is an ordinary typed answer (see
    # `test_a_claimed_speak_plan_is_never_read`), so it is NOT in this list.


async def test_speak_lapse_counts_towards_leech_like_any_answer(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall")
    await _answer(user, word, "speak", "", gave_up=True)
    async with async_session_factory() as session:
        reloaded = await session.get(SavedWord, word.id)
    assert reloaded.lapses == 1 and reloaded.reps == 1  # a Review-state Again


# --- record_answer's authority ----------------------------------------------


async def _rejects(user, word, exercise_type, given="", **kw) -> None:
    with pytest.raises(HTTPException) as exc:
        await _answer(user, word, exercise_type, given, **kw)
    assert exc.value.status_code == 422


async def test_listen_fallback_is_accepted_and_demotes_on_again(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="listen")
    ok = await _answer(user, word, "recall", word.lemma, planned_exercise="listen")
    assert ok["verdict"] == "correct" and await _level(word) == "listen"
    assert (await _logs(word))[0].planned_exercise == "listen"
    bad = await _answer(user, word, "recall", "no", planned_exercise="listen")
    assert bad["level"] == "recall"


async def test_other_new_combinations_are_rejected(created: Created) -> None:
    user = await make_user(created)
    at_recall = await _word(created, user, level="recall")
    at_recognise = await _word(created, user, level="recognise", due=False)
    at_listen = await _word(created, user, level="listen")
    await _rejects(user, at_recall, "listen", at_recall.lemma)       # not on that rung yet
    await _rejects(user, at_recognise, "listen", at_recognise.lemma)
    await _rejects(user, at_listen, "produce", at_listen.lemma)
    await _rejects(user, at_recognise, "speak", at_recognise.lemma)  # speak opens at recall
    async with async_session_factory() as session:
        with pytest.raises(HTTPException):
            await practice_service.record_answer(
                session, user, word_id=at_recall.id, context_id=None, direction="active",
                exercise_type="speak", given=at_recall.lemma, elapsed_ms=1,
            )
    assert not await _logs(at_recall) and not await _logs(at_recognise)


async def test_listen_grades_as_recall_against_the_lemma(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="listen", lemma=unique_word() + "ing")
    exact = await _answer(user, word, "listen", word.lemma.upper())
    assert exact["verdict"] == "correct" and exact["rating"] == int(fsrs.Rating.Good)
    assert exact["answer"] == word.lemma
    close = await _answer(user, word, "listen", word.lemma[:-1])
    assert close["rating"] == int(fsrs.Rating.Hard)
    wrong = await _answer(user, word, "listen", "zzzzzzzz")
    assert wrong["rating"] == int(fsrs.Rating.Again)


async def test_speak_answer_is_verified_by_the_matcher(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall", lemma="thinker" + unique_word("x")[:0])
    await _rejects(user, word, "speak", "banana")
    await _rejects(user, word, "speak", "")
    assert not await _logs(word)
    ok = await _answer(user, word, "speak", "tinker")   # th -> t
    assert ok["verdict"] == "correct" and ok["rating"] == int(fsrs.Rating.Good)
    log = (await _logs(word))[0]
    assert log.exercise_type == "speak" and log.given == "tinker"
    async with async_session_factory() as session:
        stored = await session.get(SavedWord, word.id)
    assert stored.reps == 1 and stored.passive_state is not None


def test_gave_up_is_only_for_speak() -> None:
    with pytest.raises(ValidationError):
        PracticeAnswerIn(word_id=uuid.uuid4(), direction="passive",
                         exercise_type="recall", elapsed_ms=1, gave_up=True)
    ok = PracticeAnswerIn(word_id=uuid.uuid4(), direction="passive",
                          exercise_type="speak", elapsed_ms=1, gave_up=True)
    assert ok.gave_up


async def test_the_reveal_carries_audio_when_ready(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall")
    first = await _answer(user, word, "recall", word.lemma)
    assert first["word"]["audio"] is None  # not ready: queued
    await _ready_audio(created, word.lemma)
    second = await _answer(user, word, "recall", word.lemma)
    assert set(second["word"]["audio"]) == {"url"}


# --- serving listen -----------------------------------------------------------


async def test_listen_is_served_with_audio_and_a_recall_fallback(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="listen")
    first = await _session(user)
    # Not ready: an ordinary recall item whose plan stays listen (and it is queued).
    assert [(i["exercise_type"], i["planned_exercise"], i["prompt"]["kind"]) for i in first] == [
        ("recall", "listen", "definition")]
    await _ready_audio(created, word.lemma)
    (item,) = await _session(user)
    assert item["exercise_type"] == "listen" and item["planned_exercise"] == "listen"
    prompt = item["prompt"]
    assert prompt["kind"] == "listen" and set(prompt["audio"]) == {"url"}
    assert prompt["fallback"]["kind"] == "definition"
    assert "answer" not in prompt["fallback"]
    assert word.lemma not in prompt["audio"]["url"]


async def test_audio_is_looked_up_once_for_the_whole_session(created: Created, monkeypatch) -> None:
    user = await make_user(created)
    for _ in range(3):
        await _word(created, user, level="listen")
    calls = []
    real = practice_service.word_audio.word_audio_many

    async def spy(session, senses, **kw):
        calls.append(len(senses))
        return await real(session, senses, **kw)

    monkeypatch.setattr(practice_service.word_audio, "word_audio_many", spy)
    items = await _session(user)
    assert len(items) == 3 and calls == [3]


# --- speak: serving -----------------------------------------------------------


async def test_speak_is_manual_only_and_takes_recall_and_listen_words(created: Created) -> None:
    user = await make_user(created)
    recall = await _word(created, user, level="recall")
    listen = await _word(created, user, level="listen")
    await _word(created, user, level="recognise")
    auto = await _session(user)
    assert all(i["exercise_type"] != "speak" for i in auto)
    items = await _session(user, mode="speak")
    assert {i["lemma"] for i in items} == {recall.lemma, listen.lemma}
    for item in items:
        assert item["exercise_type"] == "speak" and item["planned_exercise"] == "speak"
        p = item["prompt"]
        assert p["kind"] == "speak" and p["definition_audio_url"] is None
        assert p["definition"] and recall.lemma not in p["definition"]
        assert p["fallback"]["kind"] == "definition"


async def test_speak_by_settings_and_listen_mode_and_empty(created: Created) -> None:
    user = await make_user(created)
    listen = await _word(created, user, level="listen")
    await _word(created, user, level="recall")
    only_listen = await _session(user, mode="listen")
    assert {i["lemma"] for i in only_listen} == {listen.lemma}
    async with async_session_factory() as session:
        await practice_service.update_settings(
            session, user.id, daily_minutes=20, direction="passive", exercise_types=["speak"])
    from_settings = await _session(user)
    assert len(from_settings) == 2 and all(i["exercise_type"] == "speak" for i in from_settings)
    other = await make_user(created)
    await _word(created, other, level="recognise")
    assert await _session(other, mode="speak") == []
    assert await _session(other, mode="listen") == []


# --- speak-check ---------------------------------------------------------------


async def test_speak_check_catch_miss_and_the_third_attempt_reveal(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall", lemma="window" + "")
    await _ready_audio(created, word.lemma)

    async def check(alts, attempt):
        async with async_session_factory() as session:
            return await practice_service.speak_check(
                session, user, word_id=word.id, alternatives=alts, attempt=attempt)

    assert await check(["vindo", "vindow"], 1) == {
        "caught": True, "matched": "vindow", "answer": None, "audio": None}
    miss = await check(["wind"], 1)
    assert miss == {"caught": False, "matched": None, "answer": None, "audio": None}
    assert (await check(["wind", "wendy"], 2))["answer"] is None
    reveal = await check(["windy"], 3)
    assert reveal["caught"] is False and reveal["answer"] == word.lemma
    assert set(reveal["audio"]) == {"url"}
    async with async_session_factory() as session:
        misses = (await session.exec(select(SpeakMiss).where(SpeakMiss.user_id == user.id))).all()
    assert sorted(m.attempt for m in misses) == [1, 2, 3]
    assert {tuple(m.alternatives) for m in misses} >= {("wind",), ("wind", "wendy")}
    # Nothing at all reached the schedule.
    assert await _logs(word) == []
    async with async_session_factory() as session:
        stored = await session.get(SavedWord, word.id)
    assert stored.reps == 0 and stored.lapses == 0


async def test_speak_check_is_owner_only_and_gated(created: Created) -> None:
    owner, other = await make_user(created), await make_user(created)
    word = await _word(created, owner, level="recall")
    recognise = await _word(created, owner, level="recognise", due=False)
    async with async_session_factory() as session:
        assert await practice_service.speak_check(
            session, other, word_id=word.id, alternatives=["x"], attempt=1) is None
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await practice_service.speak_check(
                session, owner, word_id=recognise.id, alternatives=["x"], attempt=1)
    assert exc.value.status_code == 422


def test_speak_check_body_is_bounded() -> None:
    wid = uuid.uuid4()
    SpeakCheckIn(word_id=wid, alternatives=["a"] * 5, attempt=3)
    for bad in (
        dict(alternatives=[], attempt=1), dict(alternatives=["a"] * 6, attempt=1),
        dict(alternatives=["a" * 201], attempt=1), dict(alternatives=["a"], attempt=4),
        dict(alternatives=["a"], attempt=0),
    ):
        with pytest.raises(ValidationError):
            SpeakCheckIn(word_id=wid, **bad)


async def test_speak_check_over_http(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="listen", lemma="thing" + "")
    cookies = {"access_token": create_access_token(str(user.id))}
    async with _client() as client:
        r = await client.post("/api/vocabulary/practice/speak-check", cookies=cookies,
                              json={"word_id": str(word.id), "alternatives": ["sing", "ting"], "attempt": 1})
        assert r.status_code == 200 and r.json()["matched"] == "sing"
        r = await client.post("/api/vocabulary/practice/speak-check", cookies=cookies,
                              json={"word_id": str(uuid.uuid4()), "alternatives": ["x"], "attempt": 1})
        assert r.status_code == 404


# --- settings -------------------------------------------------------------------


def test_settings_accept_listen_and_speak_still_exactly_one() -> None:
    for kind in ("listen", "speak"):
        assert VocabularySettingsIn(
            daily_minutes=10, direction="passive", exercise_types=[kind]).exercise_types == [kind]
    with pytest.raises(ValidationError):
        VocabularySettingsIn(daily_minutes=10, direction="passive", exercise_types=["listen", "speak"])
    assert PracticeSessionIn(mode="speak").mode == "speak"
    assert PracticeSessionIn(mode="listen").mode == "listen"


async def test_pronunciation_is_optional_on_put_and_defaults_on(created: Created) -> None:
    user = await make_user(created)
    cookies = {"access_token": create_access_token(str(user.id))}
    body = {"daily_minutes": 10, "direction": "passive", "exercise_types": None}
    async with _client() as client:
        assert (await client.get("/api/vocabulary/settings", cookies=cookies)).json()["pronunciation"] is True
        r = await client.put("/api/vocabulary/settings", cookies=cookies, json={**body, "pronunciation": False})
        assert r.json()["pronunciation"] is False
        r = await client.put("/api/vocabulary/settings", cookies=cookies, json={**body, "daily_minutes": 15})
        assert r.json()["pronunciation"] is False and r.json()["daily_minutes"] == 15
        r = await client.put("/api/vocabulary/settings", cookies=cookies,
                             json={**body, "exercise_types": ["speak"], "pronunciation": True})
        assert r.json()["exercise_types"] == ["speak"] and r.json()["pronunciation"] is True


# --- the word page --------------------------------------------------------------


async def test_word_page_has_top_level_audio(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall")
    cookies = {"access_token": create_access_token(str(user.id))}
    async with _client() as client:
        r = await client.get(f"/api/vocabulary/words/{word.id}", cookies=cookies)
        assert r.status_code == 200 and r.json()["audio"] is None and "audio" not in r.json()["word"]
        await _ready_audio(created, word.lemma)
        r = await client.get(f"/api/vocabulary/words/{word.id}", cookies=cookies)
        assert set(r.json()["audio"]) == {"url"}


# --- On the go -------------------------------------------------------------------


async def _ready_item(created: Created, word: SavedWord) -> None:
    lexeme_sense = DEFINITION
    definition = tts.definition_spec(lexeme_sense, word.lemma)
    item = tts.item_spec(definition, tts.word_spec(word.lemma, None))
    created.render_keys.extend([definition.key, item.key, tts.word_spec(word.lemma, None).key])
    async with async_session_factory() as session:
        await tts.enqueue([item])
        await session.execute(
            update(AudioRender).where(AudioRender.key == item.key).values(
                status=RenderStatus.READY, storage_key=tts.storage_key_for(item.kind, item.key),
                duration_ms=9000, word_offset_ms=4200,
            )
        )
        await session.commit()


async def test_on_the_go_lists_ready_items_newest_first_and_counts_the_rest(
    created: Created,
) -> None:
    user = await make_user(created)
    old = await _word(created, user, level="recognise", due=False, created_at=NOW - timedelta(days=3))
    new = await _word(created, user, level="recognise", due=False, created_at=NOW - timedelta(days=1))
    pending = await _word(created, user, level="recognise", due=False, created_at=NOW - timedelta(days=2))
    for excluded in ("known", "suspended", "leech"):
        await _word(created, user, due=False, status=excluded)
    for word in (old, new):
        await _ready_item(created, word)
    cookies = {"access_token": create_access_token(str(user.id))}
    async with _client() as client:
        data = (await client.get("/api/vocabulary/on-the-go", cookies=cookies)).json()
    assert [i["word_id"] for i in data["items"]] == [str(new.id), str(old.id)]
    assert data["preparing"] == 1 and str(pending.id) not in str(data["items"])
    assert data["items"][0]["duration_ms"] == 9000 and data["items"][0]["word_offset_ms"] == 4200
    assert set(data["items"][0]) == {"word_id", "url", "duration_ms", "word_offset_ms"}
    # It is independent of the queue: nothing is due, the list is still there.
    async with async_session_factory() as session:
        # The pending word's item (and its parts) were queued by the request.
        item = tts.item_spec(tts.definition_spec(DEFINITION, pending.lemma), tts.word_spec(pending.lemma, None))
        created.render_keys.append(item.key)
        assert (await session.exec(select(AudioRender).where(AudioRender.key == item.key))).first()


async def test_exposures_are_owner_only_and_never_touch_fsrs(created: Created) -> None:
    user, other = await make_user(created), await make_user(created)
    word = await _word(created, user, level="recall")
    before = await _logs(word)
    async with async_session_factory() as session:
        snapshot = (await session.get(SavedWord, word.id)).model_dump()
    async with _client() as client:
        mine = {"access_token": create_access_token(str(user.id))}
        theirs = {"access_token": create_access_token(str(other.id))}
        body = {"word_id": str(word.id)}
        assert (await client.post("/api/vocabulary/on-the-go/exposures", json=body, cookies=mine)).status_code == 204
        assert (await client.post("/api/vocabulary/on-the-go/exposures", json=body, cookies=theirs)).status_code == 404
        assert (await client.post("/api/vocabulary/on-the-go/exposures",
                                  json={"word_id": str(uuid.uuid4())}, cookies=mine)).status_code == 404
    async with async_session_factory() as session:
        rows = (await session.exec(select(OnTheGoExposure).where(
            OnTheGoExposure.saved_word_id == word.id))).all()
        assert len(rows) == 1 and rows[0].user_id == user.id
        assert (await session.get(SavedWord, word.id)).model_dump() == snapshot
    assert await _logs(word) == before


# --- the speak typing fallback is an ordinary typed answer --------------------


async def test_a_claimed_speak_plan_is_never_read(created: Created) -> None:
    """Forging: `planned_exercise="speak"` on a typed answer used to skip the
    ladder, hiding a wrong answer. Now the plan is the word's own level."""
    user = await make_user(created)
    word = await _word(created, user, level="recall")
    first = await _answer(user, word, "recall", word.lemma, planned_exercise="speak")
    assert first["rating"] == int(fsrs.Rating.Good) and await _level(word) == "recall"
    wrong = await _answer(user, word, "recall", "zzzzzzzz", planned_exercise="speak")
    assert wrong["rating"] == int(fsrs.Rating.Again)
    assert wrong["level"] == "recognise"  # demoted: the ladder saw it
    again = await _answer(user, word, "recall", word.lemma, planned_exercise="speak")
    assert again["rating"] == int(fsrs.Rating.Good) and await _level(word) != "listen"
    assert [log.planned_exercise for log in await _logs(word)] == [
        "recall", "recall", "recognise"]


async def test_the_speak_fallback_at_listen_is_the_listen_plan_fallback(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="listen")
    wrong = await _answer(user, word, "recall", "zzzzzzzz", planned_exercise="speak")
    assert wrong["level"] == "recall"
    assert (await _logs(word))[0].planned_exercise == "listen"


async def test_a_streak_counts_through_a_speak_fallback_answer(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall")
    await _answer(user, word, "recall", word.lemma)
    out = await _answer(user, word, "recall", word.lemma, planned_exercise="speak")
    assert out["level"] == "listen"


# --- the requeue of a listen / speak card -------------------------------------


async def test_a_requeued_listen_card_may_be_answered_as_its_recall_fallback(
    created: Created,
) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="listen")
    failed = await _answer(user, word, "listen", "zzzzzzzz")
    assert failed["level"] == "recall"  # the Again demoted it
    out = await _answer(user, word, "recall", word.lemma, requeued=True,
                        planned_exercise="listen")
    assert out["verdict"] == "correct" and await _level(word) == "recall"
    log = (await _logs(word))[-1]
    assert log.exercise_type == "recall" and log.planned_exercise is None


async def test_a_requeued_listen_card_is_still_accepted_as_listen(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="listen")
    await _answer(user, word, "listen", "zzzzzzzz")
    out = await _answer(user, word, "listen", word.lemma, requeued=True)
    assert out["verdict"] == "correct" and await _level(word) == "recall"


async def test_a_requeued_speak_card_may_be_answered_as_its_typed_fallback(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall")
    await _answer(user, word, "speak", "", gave_up=True)
    typed = await _answer(user, word, "recall", word.lemma, requeued=True,
                          planned_exercise="speak")
    assert typed["verdict"] == "correct"
    assert (await _logs(word))[-1].planned_exercise is None  # a requeue, no plan
    assert await _level(word) == "recall"


async def test_requeue_does_not_convert_other_exercises(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall")
    await _answer(user, word, "recall", "no")  # Again at recall, demoted to recognise
    await _rejects(user, word, "listen", word.lemma, requeued=True)
    await _rejects(user, word, "speak", word.lemma, requeued=True)


async def test_requeue_applies_the_speak_and_listen_level_gates(created: Created) -> None:
    user = await make_user(created)
    spoken = await _word(created, user, level="recall")
    await _answer(user, spoken, "speak", "", gave_up=True)
    heard = await _word(created, user, level="listen")
    await _answer(user, heard, "listen", "zzzzzzzz")
    async with async_session_factory() as session:
        await session.execute(
            update(SavedWord).where(SavedWord.id.in_([spoken.id, heard.id]))
            .values(passive_level="recognise")
        )
        await session.commit()
    for exercise_type in ("speak", "recall"):
        await _rejects(user, spoken, exercise_type, spoken.lemma, requeued=True)
    for exercise_type in ("listen", "recall"):
        await _rejects(user, heard, exercise_type, heard.lemma, requeued=True)
    # Nothing was logged for either refused requeue.
    assert len(await _logs(spoken)) == 1 and len(await _logs(heard)) == 1


# --- the audio layer failing does not fail the session -------------------------


async def test_a_failing_audio_lookup_degrades_the_session(created: Created, monkeypatch) -> None:
    user = await make_user(created)
    await _word(created, user, level="listen")

    async def boom(*args, **kwargs):
        raise RuntimeError("storage is down")

    monkeypatch.setattr(practice_service.word_audio, "word_audio_many", boom)
    monkeypatch.setattr(practice_service.word_audio, "definition_audio_urls", boom)
    (item,) = await _session(user)
    assert (item["exercise_type"], item["planned_exercise"]) == ("recall", "listen")
    assert item["prompt"]["kind"] == "definition"
    (spoken,) = await _session(user, mode="speak")
    assert spoken["exercise_type"] == "speak"
    assert spoken["prompt"]["definition_audio_url"] is None


# --- speak-check counts the attempts itself ------------------------------------


async def _check(user, word, alts, attempt):
    async with async_session_factory() as session:
        return await practice_service.speak_check(
            session, user, word_id=word.id, alternatives=alts, attempt=attempt)


async def _miss_rows(user, word) -> list[SpeakMiss]:
    async with async_session_factory() as session:
        return list((await session.exec(
            select(SpeakMiss).where(SpeakMiss.saved_word_id == word.id)
            .order_by(SpeakMiss.created_at))).all())


async def test_a_forged_attempt_reveals_nothing(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall", lemma="window")
    first = await _check(user, word, ["wind"], 3)
    assert first == {"caught": False, "matched": None, "answer": None, "audio": None}
    assert (await _check(user, word, ["wind"], 3))["answer"] is None
    third = await _check(user, word, ["wind"], 1)  # the server's third
    assert third["answer"] == word.lemma
    rows = await _miss_rows(user, word)
    assert [m.attempt for m in rows] == [1, 2, 3] and {m.lemma for m in rows} == {"window"}
    # A new run starts after the reveal.
    assert (await _check(user, word, ["wind"], 3))["answer"] is None
    assert [m.attempt for m in await _miss_rows(user, word)] == [1, 2, 3, 1]


async def test_old_misses_do_not_count_and_rows_are_capped(created: Created) -> None:
    user = await make_user(created)
    word = await _word(created, user, level="recall", lemma="window")
    await _check(user, word, ["wind"], 1)
    await _check(user, word, ["wind"], 1)
    async with async_session_factory() as session:
        await session.execute(
            update(SpeakMiss).where(SpeakMiss.saved_word_id == word.id)
            .values(created_at=NOW - practice_service.SPEAK_ATTEMPT_WINDOW - timedelta(minutes=1))
        )
        await session.commit()
    assert (await _check(user, word, ["wind"], 1))["answer"] is None  # attempt 1 again
    for _ in range(30):
        await _check(user, word, ["wind"], 3)
    in_window = [m for m in await _miss_rows(user, word)
                 if m.created_at >= NOW - timedelta(minutes=5)]
    assert len(in_window) == practice_service.SPEAK_MISS_ROW_CAP


# --- On the go: a failed render is not "being prepared" ------------------------


async def test_on_the_go_preparing_ignores_failed_renders(created: Created) -> None:
    user = await make_user(created)
    failed_item = await _word(created, user, level="recognise", due=False)
    failed_part = await _word(created, user, level="recognise", due=False)
    waiting = await _word(created, user, level="recognise", due=False)
    cookies = {"access_token": create_access_token(str(user.id))}
    async with _client() as client:  # queues all three words' renders
        first = (await client.get("/api/vocabulary/on-the-go", cookies=cookies)).json()
        assert first["preparing"] == 3 and first["items"] == []
        for word in (failed_item, failed_part, waiting):
            definition = tts.definition_spec(DEFINITION, word.lemma)
            spoken = tts.word_spec(word.lemma, None)
            item = tts.item_spec(definition, spoken)
            created.render_keys.extend([definition.key, spoken.key, item.key])
        key_item = tts.item_spec(
            tts.definition_spec(DEFINITION, failed_item.lemma), tts.word_spec(failed_item.lemma, None)).key
        key_part = tts.word_spec(failed_part.lemma, None).key
        async with async_session_factory() as session:
            await session.execute(
                update(AudioRender).where(AudioRender.key.in_([key_item, key_part]))
                .values(status=RenderStatus.FAILED)
            )
            await session.commit()
        data = (await client.get("/api/vocabulary/on-the-go", cookies=cookies)).json()
    assert data["items"] == [] and data["preparing"] == 1
