"""The worker's CALD hook and its retry sweep (`lexicon_cald.run_hook`,
`run_sweep`): what it does when the API says no, what it costs, and what it
leaves in memory.

* a 402, or a 429 that outlasts the client's own retries, stops the pass at
  once -- one HTTP request (or one request's own retries), no per-item
  re-asks, nothing applied -- and holds the hook off for a cooldown that
  doubles, logged once on entering it and once on leaving it;
* a wall-clock timeout, a per-pass and a daily spend cap;
* the sweep: questions recorded as unanswered, senses nothing ever asked about
  (a word-list build writes them into a finished lexeme), a sense whose Uzbek
  nobody translated; throttled, tried a few times, and silent when nothing
  changed;
* the index and the log are dropped when a call ends.

The real `lexicon_enrich.Gemini` client runs against an `httpx.MockTransport`
for the HTTP failures (no network, no key); everything else uses the fake
model of `tests/test_cald_apply.py`. Dictionary entries are INVENTED.
"""

import asyncio
import gc
import json
import logging
import weakref
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlmodel import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense
from app.services import lexicon_cald as lc
from app.services import lexicon_enrich as le
from tests.test_cald_apply import (
    JUDGE,
    FakeModel,
    _build_index,
    _drop,
    _lemma,
    _seed,
    _state,
)

LOGGER = "app.services.lexicon_cald"


@pytest.fixture(autouse=True)
def hook_settings(monkeypatch):
    """The hook ON with no caps, a controllable clock, and fresh state."""
    lc.reset_hook_state()
    for name, value in dict(
            cald_map_new_lexemes=True, cald_hook_cooldown_s=300.0,
            cald_hook_cooldown_max_s=1200.0, cald_hook_timeout_s=60.0,
            cald_hook_pass_budget_usd=0.0, cald_hook_daily_budget_usd=0.0,
            cald_sweep_interval_s=1800.0, cald_sweep_batch=25, cald_sweep_max_tries=3).items():
        monkeypatch.setattr(settings, name, value)
    now = [10_000.0]
    monkeypatch.setattr(lc, "_clock", lambda: now[0])

    async def no_backoff(attempt: int) -> None:
        return None

    monkeypatch.setattr(le.Gemini, "_backoff", staticmethod(no_backoff))
    yield now
    lc.reset_hook_state()


class CountingModel(FakeModel):
    """`FakeModel` that books each request on its usage, as the real client
    does (the hook reads `usage` for the spend caps and "did it ask")."""

    cost_tokens = 100

    async def ask(self, model, prompt, *, step, **kwargs):
        reply = await super().ask(model, prompt, step=step, **kwargs)
        self.usage.add(model, step, self.cost_tokens, self.cost_tokens)
        return reply


class SilentModel(CountingModel):
    """Answers nothing usable -- no verdict, no HTTP failure either."""

    async def ask(self, model, prompt, *, step, **kwargs):
        self.calls.append(step)
        self.usage.add(model, step, 10, 10)
        return None


class UntranslatingModel(CountingModel):
    async def ask(self, model, prompt, *, step, **kwargs):
        if step == "cald-translate-v2":
            self.calls.append(step)
            return None
        return await super().ask(model, prompt, step=step, **kwargs)


async def _http_gemini(handler) -> le.Gemini:
    """The real client against a scripted server."""
    gemini = le.Gemini(le.UsageLog(), api_key="test-key", attempts=3)
    await gemini._client.aclose()
    gemini._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return gemini


async def _finish_enrichment(ids: dict) -> None:
    async with async_session_factory() as session:
        lexeme = await session.get(Lexeme, ids["lexeme"])
        lexeme.enriched_at = datetime.now(timezone.utc)
        session.add(lexeme)
        await session.commit()


def _messages(caplog, needle: str) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.name == LOGGER and needle in r.getMessage()]


# --- 402 and 429 ------------------------------------------------------------------------


async def test_a_402_stops_the_pass_at_once_and_the_cooldown_doubles(tmp_path, caplog,
                                                                    hook_settings):
    now = hook_settings
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    calls: list[str] = []

    def paid_out(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(402, json={"error": {"message": "billing"}})

    try:
        before = await _state(ids)
        # The engine: ONE request -- the three senses share a batch, and the
        # per-item re-asks that used to follow are refused before they are made.
        with pytest.raises(lc.HookHalt) as halted:
            await lc.map_new_lexemes([ids["lexeme"]], gemini=await _http_gemini(paid_out),
                                     out_dir=out, judge=JUDGE)
        assert halted.value.status == 402 and len(calls) == 1
        assert await _state(ids) == before  # nothing applied
        log = lc.DecisionLog(out / lc.DECISIONS_FILE)
        assert not log.records  # and nothing recorded as unanswered

        # The hook: never raises, pauses, and says so once.
        calls.clear()
        with caplog.at_level(logging.INFO, logger=LOGGER):
            assert await lc.run_hook([ids["lexeme"]], out_dir=out,
                                     gemini=await _http_gemini(paid_out)) == {}
            assert len(calls) == 1 and lc.hook_cooldown_left() == pytest.approx(300.0)
            for _ in range(5):  # every further pass inside the cooldown: no request, no log
                assert await lc.run_hook([ids["lexeme"]], out_dir=out,
                                         gemini=await _http_gemini(paid_out)) == {}
            assert len(calls) == 1
            assert len(_messages(caplog, "paused")) == 1

            # After the cooldown it tries once more; failing again doubles the pause.
            now[0] += 301.0
            await lc.run_hook([ids["lexeme"]], out_dir=out, gemini=await _http_gemini(paid_out))
            assert len(calls) == 2 and lc.hook_cooldown_left() == pytest.approx(600.0)
            now[0] += 601.0
            await lc.run_hook([ids["lexeme"]], out_dir=out, gemini=await _http_gemini(paid_out))
            assert lc.hook_cooldown_left() == pytest.approx(1200.0)  # the cap
            now[0] += 1201.0
            await lc.run_hook([ids["lexeme"]], out_dir=out, gemini=await _http_gemini(paid_out))
            assert lc.hook_cooldown_left() == pytest.approx(1200.0)  # stays at the cap
            assert len(_messages(caplog, "paused")) == 4  # one per state change

            # Paid up: it resumes, applies, and says so once.
            now[0] += 1201.0
            counts = await lc.run_hook([ids["lexeme"]], out_dir=out, gemini=CountingModel(),
                                       judge=JUDGE)
        assert counts["newly applied"] == 2 and lc.hook_cooldown_left() == 0
        assert len(_messages(caplog, "resumed")) == 1
    finally:
        await _drop(ids)


async def test_a_429_that_outlasts_the_clients_retries_stops_the_pass(tmp_path):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    calls: list[int] = []

    def rate_limited(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    try:
        gemini = await _http_gemini(rate_limited)  # attempts=3: the client's own retries
        with pytest.raises(lc.HookHalt) as halted:
            await lc.map_new_lexemes([ids["lexeme"]], gemini=gemini, out_dir=out, judge=JUDGE)
        assert halted.value.status == 429
        assert len(calls) == 3  # one request, retried by the client -- and nothing after
        assert gemini.hard_status == 429
    finally:
        await _drop(ids)


async def test_a_transient_failure_is_not_a_hard_one(tmp_path):
    """A 500 that clears on the retry (or a reply that does not parse) is the
    client's business: no halt, the pass goes on."""
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    model = CountingModel()
    state = {"failed": False}
    real_ask = model.ask

    async def flaky(model_name, prompt, *, step, **kwargs):
        if not state["failed"]:
            state["failed"] = True
            return None
        return await real_ask(model_name, prompt, step=step, **kwargs)

    model.ask = flaky
    try:
        counts = await lc.map_new_lexemes([ids["lexeme"]], gemini=model, out_dir=out, judge=JUDGE)
        assert counts["newly applied"] >= 1
    finally:
        await _drop(ids)


# --- timeout and spend caps ---------------------------------------------------------------


async def test_a_pass_that_overruns_its_wall_clock_is_cancelled_and_backed_off(
        tmp_path, caplog, monkeypatch):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)

    class Slow(CountingModel):
        async def ask(self, model, prompt, *, step, **kwargs):
            await asyncio.sleep(5)

    monkeypatch.setattr(settings, "cald_hook_timeout_s", 0.05)
    try:
        before = await _state(ids)
        with caplog.at_level(logging.INFO, logger=LOGGER):
            assert await lc.run_hook([ids["lexeme"]], out_dir=out, gemini=Slow(),
                                     judge=JUDGE) == {}
        assert lc.hook_cooldown_left() > 0
        assert len(_messages(caplog, "paused")) == 1
        assert await _state(ids) == before
    finally:
        await _drop(ids)


async def test_the_per_pass_cap_stops_before_the_next_request(tmp_path, caplog, monkeypatch):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    monkeypatch.setattr(settings, "cald_hook_pass_budget_usd", 0.50)
    model = CountingModel()
    model.cost_tokens = 10_000_000  # one request is already far past $0.50
    try:
        before = await _state(ids)
        with caplog.at_level(logging.INFO, logger=LOGGER):
            assert await lc.run_hook([ids["lexeme"]], out_dir=out, gemini=model,
                                     judge=JUDGE) == {}
        assert model.calls == ["cald-map"]  # stopped before the translation requests
        assert lc.hook_cooldown_left() == 0  # a cap is not a failure
        assert len(_messages(caplog, "per-pass cap")) == 1
        assert await _state(ids) == before
        # What was paid for is in the log: a later pass asks only the rest.
        model2 = CountingModel()
        monkeypatch.setattr(settings, "cald_hook_pass_budget_usd", 0.0)
        counts = await lc.run_hook([ids["lexeme"]], out_dir=out, gemini=model2, judge=JUDGE)
        assert "cald-map" not in model2.calls and counts["newly applied"] == 2
    finally:
        await _drop(ids)


async def test_the_daily_cap_idles_the_hook_and_says_so_once(tmp_path, caplog, monkeypatch):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    monkeypatch.setattr(settings, "cald_hook_daily_budget_usd", 3.0)
    now = datetime.now(timezone.utc)
    out.mkdir(exist_ok=True)
    with (out / lc.USAGE_FILE).open("w") as fh:
        for when, cmd, cost in ((now - timedelta(days=2), "worker", 50.0),  # not today
                                (now, "map", 9.0),  # a CLI run, not the worker
                                (now, "worker", 2.0), (now, "worker-sweep", 1.5)):
            fh.write(json.dumps({"at": when.isoformat(), "cmd": cmd,
                                 "total_cost_usd": cost}) + "\n")
    try:
        assert lc.worker_spend_today(out) == pytest.approx(3.5)
        model = CountingModel()
        with caplog.at_level(logging.INFO, logger=LOGGER):
            for _ in range(3):
                assert await lc.run_hook([ids["lexeme"]], out_dir=out, gemini=model,
                                         judge=JUDGE) == {}
        assert model.calls == []
        assert len(_messages(caplog, "cap is spent")) == 1
    finally:
        await _drop(ids)


# --- the retry sweep ----------------------------------------------------------------------


async def test_the_sweep_retries_unanswered_questions_throttled_and_then_goes_quiet(
        tmp_path, hook_settings, monkeypatch):
    now = hook_settings
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    await _finish_enrichment(ids)
    try:
        # The hook's pass: the model answers nothing usable -> recorded as unanswered.
        silent = SilentModel()
        counts = await lc.run_hook([ids["lexeme"]], out_dir=out, gemini=silent, judge=JUDGE)
        assert not counts.get("newly applied")
        log = lc.DecisionLog(out / lc.DECISIONS_FILE)
        assert log.records and not any(r.get("answered") for r in log.records.values())

        model = CountingModel()
        swept = await lc.run_sweep(out_dir=out, gemini=model, judge=JUDGE)
        assert swept["swept"] == 1 and swept["newly applied"] == 2
        # Throttled: another sweep inside the interval does nothing at all.
        again = CountingModel()
        assert await lc.run_sweep(out_dir=out, gemini=again, judge=JUDGE) == {}
        assert again.calls == []
        # Later: nothing is owed (the third sense is a settled "none") -- and
        # the index is not even loaded the time after that.
        now[0] += 1801.0
        assert await lc.run_sweep(out_dir=out, gemini=again, judge=JUDGE) == {}
        now[0] += 1801.0

        def refuse(*args, **kwargs):
            raise AssertionError("an empty scan must not load the index again")

        monkeypatch.setattr(lc, "worker_index", refuse)
        assert await lc.run_sweep(out_dir=out, gemini=again, judge=JUDGE) == {}
        assert again.calls == []
    finally:
        await _drop(ids)


async def test_the_sweep_picks_up_a_sense_written_after_the_lexemes_enrichment(
        tmp_path, hook_settings):
    """`word_lists_build.write_new_sense` adds a sense to a lexeme whose
    `enriched_at` is already set: the enrichment hook never sees it."""
    now = hook_settings
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    await _finish_enrichment(ids)
    try:
        await lc.run_hook([ids["lexeme"]], out_dir=out, gemini=CountingModel(), judge=JUDGE)
        async with async_session_factory() as session:
            fresh = LexemeSense(lexeme_id=ids["lexeme"], sense_rank=4,
                                definition_en="a hopeful sign for the future",
                                meaning_uz="umid belgisi", cefr="B1", source_id="model",
                                licence="proprietary", definition_source="model",
                                provisional=False)
            session.add(fresh)
            await session.commit()
            fresh_id = fresh.id
        now[0] += 1801.0
        model = CountingModel()
        swept = await lc.run_sweep(out_dir=out, gemini=model, judge=JUDGE)
        assert swept["swept"] == 1 and swept["newly applied"] == 1
        async with async_session_factory() as session:
            row = await session.get(LexemeSense, fresh_id)
            assert row.definition_source == "cald" and row.cald_applied_at is not None
            assert row.definition_en.startswith("test sense:")
    finally:
        await _drop(ids)


async def test_the_sweep_respects_the_cooldown_and_the_hard_failure(tmp_path, hook_settings):
    now = hook_settings
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    await _finish_enrichment(ids)
    calls: list[int] = []

    def paid_out(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(402, json={})

    try:
        assert await lc.run_sweep(out_dir=out, gemini=await _http_gemini(paid_out)) == {}
        assert len(calls) == 1 and lc.hook_cooldown_left() > 0
        model = CountingModel()
        now[0] += 1801.0  # the sweep interval has passed, the cooldown (300 s) too ...
        lc._hook.until = now[0] + 100.0  # ... unless the hook is still held off
        assert await lc.run_sweep(out_dir=out, gemini=model, judge=JUDGE) == {}
        assert model.calls == [] and len(calls) == 1
    finally:
        await _drop(ids)


async def test_a_sense_nobody_translated_is_deferred_and_the_sweep_finishes_it(
        tmp_path, hook_settings):
    now = hook_settings
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    await _finish_enrichment(ids)
    try:
        before = await _state(ids)
        counts = await lc.run_hook([ids["lexeme"]], out_dir=out, gemini=UntranslatingModel(),
                                   judge=JUDGE)
        assert counts["deferred (untranslated)"] == 2 and not counts.get("newly applied")
        assert await _state(ids) == before  # not applied with the OLD Uzbek, for good
        now[0] += 1801.0
        swept = await lc.run_sweep(out_dir=out, gemini=CountingModel(), judge=JUDGE)
        assert swept["newly applied"] == 2
        assert (await _state(ids))["senses"][ids["light"]]["meaning_uz"] == "yangi nur"
    finally:
        await _drop(ids)


async def test_a_lexeme_the_sweep_keeps_failing_on_is_given_up_after_a_few_tries(
        tmp_path, hook_settings, monkeypatch):
    now = hook_settings
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    await _finish_enrichment(ids)
    monkeypatch.setattr(settings, "cald_sweep_max_tries", 2)
    try:
        asked = []
        for _ in range(4):
            model = SilentModel()
            await lc.run_sweep(out_dir=out, gemini=model, judge=JUDGE)
            asked.append(bool(model.calls))
            now[0] += 1801.0
        assert asked == [True, True, False, False]
    finally:
        await _drop(ids)


# --- memory -------------------------------------------------------------------------------


async def test_the_index_and_the_log_are_dropped_when_a_call_ends(tmp_path, monkeypatch):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    refs: list[weakref.ref] = []
    real_index, real_log = lc.worker_index, lc.DecisionLog

    def spy_index(out_dir):
        index = real_index(out_dir)
        refs.append(weakref.ref(index))
        assert not hasattr(index, "data")  # the raw dict is not kept beside the lookups
        return index

    class SpyLog(real_log):
        def __init__(self, path):
            super().__init__(path)
            refs.append(weakref.ref(self))

    monkeypatch.setattr(lc, "worker_index", spy_index)
    monkeypatch.setattr(lc, "DecisionLog", SpyLog)
    try:
        await lc.run_hook([ids["lexeme"]], out_dir=out, gemini=CountingModel(), judge=JUDGE)
        gc.collect()
        assert len(refs) == 2 and all(ref() is None for ref in refs)

        # Also after a pass that halted.
        refs.clear()

        def paid_out(request: httpx.Request) -> httpx.Response:
            return httpx.Response(402, json={})

        await _drop_applied(ids)
        await lc.run_hook([ids["lexeme"]], out_dir=out, gemini=await _http_gemini(paid_out),
                          judge=JUDGE)
        gc.collect()
        assert all(ref() is None for ref in refs)
    finally:
        await _drop(ids)


async def _drop_applied(ids: dict) -> None:
    """Back to unapplied, for a second run on the same seed."""
    async with async_session_factory() as session:
        await lc.restore_senses(session, None)
        await session.commit()


async def test_the_hook_does_nothing_when_switched_off(tmp_path, monkeypatch):
    lemma = _lemma()
    out = _build_index(tmp_path, lemma)
    ids = await _seed(lemma)
    monkeypatch.setattr(settings, "cald_map_new_lexemes", False)
    try:
        model = CountingModel()
        assert await lc.run_hook([ids["lexeme"]], out_dir=out, gemini=model) == {}
        assert await lc.run_sweep(out_dir=out, gemini=model) == {}
        assert model.calls == []
        async with async_session_factory() as session:
            assert (await session.exec(select(LexemeSense).where(
                LexemeSense.id == ids["light"]))).one().cald_applied_at is None
    finally:
        await _drop(ids)
