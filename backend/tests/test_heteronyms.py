"""Heteronyms: the vendored pronunciation data, the candidate sets, and the
replayable decisions (`app.services.pronunciation`, `heteronym_decisions`)."""

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import update
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.lexicon import LexemeSense
from app.services import heteronym_decisions as hd
from app.services import pronunciation as pron
from tests.audio_helpers import Created, make_lexeme, unique_word

#: misaki's British phoneme alphabet (`misaki/en.py` GB_VOCAB) plus the space.
GB_VOCAB = set("AIQWYabdfhijklmnpstuvwzðŋɑɒɔəɛɜɡɪɹʃʊʌʒʤʧˈˌːθᵊ")


@pytest.fixture
async def created():
    made = Created()
    yield made
    await made.cleanup()


# --- the data --------------------------------------------------------------------


def test_the_vendored_misaki_table_is_the_788_pos_keyed_entries() -> None:
    raw = json.loads(pron.MISAKI_PATH.read_text(encoding="utf-8"))
    assert len(raw) == 788
    assert all(isinstance(v, dict) and "DEFAULT" in v for v in raw.values())


def test_every_phoneme_string_uses_misakis_alphabet_not_ipa() -> None:
    raw = json.loads(pron.MISAKI_PATH.read_text(encoding="utf-8"))
    extras = json.loads(pron.EXTRAS_PATH.read_text(encoding="utf-8"))
    strings = [v for entry in raw.values() for v in entry.values() if v]
    strings += [item["ps"] for items in extras.values() for item in items]
    bad = {s: sorted(set(s) - GB_VOCAB) for s in strings if set(s) - GB_VOCAB}
    assert not bad, f"not misaki phonemes: {bad}"


def test_the_words_the_brief_names_are_heteronyms_with_distinct_candidates() -> None:
    for word in ("lead", "tear", "bass", "row", "sow", "bow", "wound", "does", "dove",
                 "minute", "close", "record", "present", "live", "wind", "read"):
        assert pron.is_heteronym(word), word
        ps = [c.ps for c in pron.candidates(word)]
        assert len({pron.strip_stress(p) for p in ps}) == len(ps) >= 2


def test_lead_the_metal_is_there_alongside_to_lead() -> None:
    assert {c.ps for c in pron.candidates("lead")} == {"lˈiːd", "lˈɛd"}


def test_stress_only_variants_are_not_heteronyms() -> None:
    # misaki keys `be` as DEFAULT biː / None bˈiː: a stressed and an unstressed
    # reading of one word. A clip of `be` is as good as any.
    assert not pron.is_heteronym("be")
    assert not pron.is_heteronym("table")
    assert not pron.is_heteronym("close down")  # a phrase is never one


def test_the_fallback_is_misakis_entry_for_the_pos_else_default() -> None:
    assert pron.fallback_pronunciation("record", "v") == "ɹɪkˈɔːd"
    assert pron.fallback_pronunciation("record", "n") == "ɹˈɛkɔːd"  # DEFAULT
    assert pron.fallback_pronunciation("record", "") == "ɹˈɛkɔːd"
    assert pron.fallback_pronunciation("table", "n") is None


def test_a_decided_pronunciation_wins_and_a_non_heteronym_gets_none() -> None:
    assert pron.sense_pronunciation("record", "v", "ɹˈɛkɔːd") == "ɹˈɛkɔːd"
    assert pron.sense_pronunciation("record", "v", None) == "ɹɪkˈɔːd"
    assert pron.sense_pronunciation("table", "n", "whatever") is None


def test_to_ipa_renders_misakis_diphthong_capitals() -> None:
    assert pron.to_ipa("klˈQs") == "klˈəʊs"
    assert pron.to_ipa("bˈW") == "bˈaʊ"


# --- decisions ---------------------------------------------------------------------


def test_a_sense_is_keyed_by_synset_or_definition_never_by_a_database_id() -> None:
    with_synset = hd.sense_key("Record", "n", "oewn-1-n", "a thing")
    assert with_synset == hd.sense_key("record", "n", "oewn-1-n", "a DIFFERENT wording")
    no_synset = hd.sense_key("record", "n", None, "A  Thing")
    assert no_synset == hd.sense_key("record", "n", None, "a thing")
    assert no_synset != hd.sense_key("record", "n", None, "another thing")


def test_parse_choices_accepts_only_valid_numbers() -> None:
    reply = {"s1": 2, "s2": "1", "s3": 0, "s4": 9, "s5": "x"}
    assert hd.parse_choices(reply, ["s1", "s2", "s3", "s4", "s5", "s6"], 2) == {"s1": 2, "s2": 1}
    assert hd.parse_choices(None, ["s1"], 2) == {}


def test_the_prompt_carries_the_notes_and_the_senses() -> None:
    text = hd.render_prompt(
        "lead", pron.candidates("lead"),
        [("s1", "n", "a soft heavy metal"), ("s2", "v", "take somebody somewhere")],
    )
    assert "1. /lˈiːd/" in text and "2. /lˈɛd/" in text
    assert "metal" in text and "s1: (n) a soft heavy metal" in text


class FakeGemini:
    """Answers each sense with the candidate whose number the rule returns."""

    def __init__(self, rule) -> None:
        self.rule, self.prompts = rule, []

    async def ask(self, model, prompt, *, step, max_tokens=0, **kw):
        self.prompts.append(prompt)
        out = {}
        for key, line in re.findall(r"^(s\d+): (.*)$", prompt, re.M):
            out[key] = self.rule(line)
        return out


async def test_decide_logs_replayably_and_apply_writes_the_column(
    created: Created, tmp_path: Path
) -> None:
    noun_lexeme, noun = await make_lexeme(created, "record", pos="n", definition="a document that keeps facts")
    verb_lexeme, verb = await make_lexeme(created, "record", pos="v", definition="set down in permanent form")
    async with async_session_factory() as session:
        await session.execute(
            update(LexemeSense).where(LexemeSense.id == noun.id).values(oewn_synset_id="oewn-test-n")
        )
        await session.commit()
        mine = [r for r in await hd.heteronym_senses(session) if r.sense_id in {noun.id, verb.id}]
    assert len(mine) == 2

    log_path = tmp_path / "decisions.jsonl"
    log = hd.DecisionLog(log_path)
    # candidate 1 = DEFAULT (noun-style), 2 = VERB
    gemini = FakeGemini(lambda line: 2 if "(v)" in line else 1)
    report = await hd.decide(gemini, log, mine)
    assert (report.decided, report.replayed, report.undecided) == (2, 0, [])
    assert len(gemini.prompts) == 1  # one request per lemma
    assert log.get("record", "n", "oewn-test-n", "x") == "ɹˈɛkɔːd"
    assert log.get("record", "v", None, "set down in permanent form") == "ɹɪkˈɔːd"

    # Replay: a fresh log read from disk answers everything; no request is made.
    again = FakeGemini(lambda line: 1)
    replay = await hd.decide(again, hd.DecisionLog(log_path), mine)
    assert (replay.decided, replay.replayed, again.prompts) == (0, 2, [])
    lines = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert {(l["lemma"], l["pos"]) for l in lines} == {("record", "n"), ("record", "v")}
    assert "id" not in lines[0] and "sense_id" not in lines[0]  # nothing database-local

    async with async_session_factory() as session:
        applied = await hd.apply(session, hd.DecisionLog(log_path))
    assert applied.written == 2 and applied.stale == []
    async with async_session_factory() as session:
        stored = {
            s.id: s.pronunciation
            for s in (await session.exec(select(LexemeSense).where(LexemeSense.id.in_([noun.id, verb.id])))).all()
        }
    assert stored == {noun.id: "ɹˈɛkɔːd", verb.id: "ɹɪkˈɔːd"}
    async with async_session_factory() as session:
        assert (await hd.apply(session, hd.DecisionLog(log_path))).written == 0  # idempotent


async def test_apply_leaves_an_undecided_sense_null_and_skips_a_stale_answer(
    created: Created, tmp_path: Path
) -> None:
    _, undecided = await make_lexeme(created, "bow", pos="n", definition="the front of a ship")
    _, stale = await make_lexeme(created, "bow", pos="v", definition="bend forward at the waist")
    log = hd.DecisionLog(tmp_path / "d.jsonl")
    log.put("bow", "v", None, "bend forward at the waist", "not-a-candidate", "test")
    async with async_session_factory() as session:
        report = await hd.apply(session, log)
    assert any(label.startswith("bow (n)") for label in report.undecided)
    assert any("not-a-candidate" in label for label in report.stale)
    async with async_session_factory() as session:
        rows = (await session.exec(select(LexemeSense).where(LexemeSense.id.in_([undecided.id, stale.id])))).all()
    assert all(r.pronunciation is None for r in rows)  # nothing guessed into the column


async def test_a_word_that_is_not_a_heteronym_is_never_asked_about(created: Created) -> None:
    _, sense = await make_lexeme(created, unique_word(), definition="a plain thing")
    async with async_session_factory() as session:
        assert sense.id not in {r.sense_id for r in await hd.heteronym_senses(session)}
