"""Tests for corrections in `build_questions.py`. Two of them were found by
the same bug report against `cam21-t4-s1` (Cambridge 21, Test 4, Section 1):
a marker that names the interviewer's turn instead of the reply that actually
answers the question, and a marker that names the plain mention of a name
instead of where it is spelled out. See `seed/README.md` for the fuller story
and the measurement across the corpus.

A third guards the interviewer-turn widen itself: unbounded, it can reach
past the reply turn and into a later question's own marked evidence, an
out-of-order-marker shape `in_order` already has a real corpus case for
(`cam12-t3-s4`).

Run directly, the same way `answer_key.py` runs its own cases:

    seed/.venv/bin/python seed/test_build_questions.py

Needs `seed/catalogue.db` to exist (even empty) so the `build()` call at the
end of a real run has a `stage` table to update -- it matches zero rows for a
section this file made up, which is not an error. Build one with:

    sqlite3 seed/catalogue.db < seed/schema.sql

Writes and removes its own `seed/work/zzfix-*` directories; never touches a
real section.
"""

import json
import pathlib
import shutil
import sys

SEED = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SEED))

import build_questions as bq  # noqa: E402

WORK = SEED / "work"


# --- building a fixture ---------------------------------------------------


def turns_and_alignment(entries: list[tuple[str, str, str | None]]
                        ) -> tuple[list[dict], list[dict]]:
    """``[(speaker, text, marker), ...]`` -> the two files `align.py` and
    `read_audioscript.py` actually hand `build_questions.py`: turns, and one
    aligned word every 400ms with a 600ms gap between turns, so nothing here
    straddles a turn boundary by accident.
    """
    turns: list[dict] = []
    aligned: list[dict] = []
    t = 0
    for speaker, text, marker in entries:
        turns.append({"speaker": speaker, "text": text, "marker": marker,
                      "answer": None})
        for word in text.split():
            aligned.append({"word": word, "start_ms": t, "end_ms": t + 380,
                            "turn": len(turns) - 1, "tokens": 1, "score": 0.9})
            t += 400
        t += 600
    return turns, aligned


def write_section(section_id: str, entries: list[tuple[str, str, str | None]],
                  groups: list[dict]) -> pathlib.Path:
    work = WORK / section_id
    work.mkdir(parents=True, exist_ok=True)
    turns, aligned = turns_and_alignment(entries)
    (work / "turns.json").write_text(json.dumps(turns))
    (work / "aligned.json").write_text(json.dumps(aligned))
    (work / "questions.src.json").write_text(
        json.dumps({"source": {"kind": "listening"}, "groups": groups}))
    return work


def gap_group(keys: dict[int, str]) -> dict:
    """A ten-gap form-completion group, one gap per question 1-10 -- the
    band a `-s1` section id is held to."""
    template = "\n".join(f"{{{{{n}}}}}" for n in range(1, 11))
    return {"type": "form_completion", "instructions": "Complete the form.",
            "word_limit": 1, "template": template,
            "questions": [{"number": n, "paper_number": n, "key": keys[n]}
                         for n in range(1, 11)]}


# --- the fixture that reproduces the report -------------------------------

#: Ten questions. Q1 is a name marked on its plain mention, spelled out two
#: turns later. Q3 is marked on the interviewer's own question, which is the
#: only place "gym" is said; the candidate's opinion of it is the next turn.
#: Q2 and Q4-10 are ordinary: marked on the respondent's own turn, with
#: nothing to correct -- the control that says the fix leaves a right answer
#: alone.
ENTRIES: list[tuple[str, str, str | None]] = [
    ("WOMAN", "Good morning can I ask you some questions", None),
    ("MAN", "Sure go ahead", None),
    ("WOMAN", "Could I start by taking your name please", None),
    ("MAN", "Smith", "Q1"),
    ("WOMAN", "How do you spell that", None),
    ("MAN", "Its S-M-I-T-H", None),
    ("WOMAN", "What do you do", None),
    ("MAN", "teacher", "Q2"),
    ("WOMAN", "Have you visited the new gym", "Q3"),
    ("MAN", "No I think its too expensive", None),
    ("WOMAN", "What about the river near here", None),
    ("MAN", "river", "Q4"),
    ("WOMAN", "next", None),
    ("MAN", "lake", "Q5"),
    ("WOMAN", "next", None),
    ("MAN", "forest", "Q6"),
    ("WOMAN", "next", None),
    ("MAN", "desert", "Q7"),
    ("WOMAN", "next", None),
    ("MAN", "island", "Q8"),
    ("WOMAN", "next", None),
    ("MAN", "valley", "Q9"),
    ("WOMAN", "next", None),
    ("MAN", "canyon", "Q10"),
]
KEYS = {1: "Smith", 2: "teacher", 3: "gym", 4: "river", 5: "lake",
        6: "forest", 7: "desert", 8: "island", 9: "valley", 10: "canyon"}

FIXTURE = "zzfix-t9-s1"


def run_fixture() -> dict:
    work = write_section(FIXTURE, ENTRIES, [gap_group(KEYS)])
    try:
        rc = bq.build(FIXTURE)
        assert rc == 0, f"build() refused the fixture (exit {rc})"
        return json.loads((work / "questions.json").read_text())
    finally:
        shutil.rmtree(work)


def by_number(built: dict) -> dict[int, dict]:
    return {q["number"]: q for g in built["groups"] for q in g["questions"]}


# --- unit tests on the pure helpers ----------------------------------------


def test_dominant_speaker_needs_a_majority_and_enough_data() -> None:
    turns = [{"speaker": s} for s in
             ["MAN", "WOMAN", "MAN", "WOMAN", "MAN", "WOMAN", "MAN", "MAN"]]
    # 3 MAN, 1 WOMAN among the markers below: a real majority.
    assert bq.dominant_speaker(turns, {1: 0, 2: 2, 3: 4, 4: 3}) == "MAN"
    # Only two markers -- not enough to act on.
    assert bq.dominant_speaker(turns, {1: 0, 2: 1}) is None
    # A tie: no speaker the section's own markers agree on.
    assert bq.dominant_speaker(turns, {1: 0, 2: 1, 3: 2, 4: 3}) is None


def test_spelling_finds_a_letter_by_letter_confirmation() -> None:
    aligned = [
        {"word": "Smith", "start_ms": 0, "end_ms": 400, "turn": 0},
        {"word": "How", "start_ms": 1000, "end_ms": 1300, "turn": 1},
        {"word": "Its", "start_ms": 2000, "end_ms": 2300, "turn": 2},
        {"word": "S-M-I-T-H", "start_ms": 2400, "end_ms": 3200, "turn": 2},
    ]
    # Inside the window: found.
    found = bq.spelling(["Smith"], aligned, 400, 10_000)
    assert found == (2400, 3200)
    # The plain mention at ms 0 is excluded because it is not past `lo`.
    assert bq.spelling(["Smith"], aligned, 3200, 10_000) is None
    # Past the ceiling: not found.
    assert bq.spelling(["Smith"], aligned, 400, 2000) is None
    # A different name: not found.
    assert bq.spelling(["Jones"], aligned, 400, 10_000) is None


def test_spelled_out_regex_does_not_fire_on_ordinary_hyphenation() -> None:
    assert bq.SPELLED_OUT.match("L-E-I-G-H.")
    assert bq.SPELLED_OUT.match("S-M-I-T-H")
    assert not bq.SPELLED_OUT.match("L-double-E?")
    assert not bq.SPELLED_OUT.match("self-employed")


def test_next_marker_start() -> None:
    spans = {1: (0, 100), 5: (500, 600), 9: (900, 1000)}
    assert bq.next_marker_start(spans, 1) == 500
    assert bq.next_marker_start(spans, 5) == 900
    assert bq.next_marker_start(spans, 9) == 1 << 62


def test_next_marker_start_skips_a_shared_choose_two_span() -> None:
    """"Q21/22" against one turn gives both numbers the SAME span -- the
    shape that regressed `cam18-t3-s3`. Reading 22's start as 21's ceiling
    reads back 21's own start and blocks any widen outright; the ceiling has
    to keep looking for the next number whose span actually differs."""
    spans = {21: (100, 200), 22: (100, 200), 23: (300, 400)}
    assert bq.next_marker_start(spans, 21) == 300
    assert bq.next_marker_start(spans, 22) == 300
    # No later question at all: the shared pair is the end of the world too.
    assert bq.next_marker_start({21: (100, 200), 22: (100, 200)}, 21) == 1 << 62


# --- the end-to-end fixture -------------------------------------------------


def test_interviewer_turn_widens_to_the_reply_that_answers_it() -> None:
    built = by_number(run_fixture())
    q3 = built[3]
    # The marker's own turn ("Have you visited the new gym") is where the
    # span used to stop; the fix widens it to take in the reply that
    # actually answers "believes the ___ is unnecessary"-shaped questions.
    assert q3["replay_end_ms"] > 9_600, (
        "Q3's span should reach past the interviewer's own turn and into "
        f"the reply; got {q3}")


def test_name_widens_to_where_it_is_spelled() -> None:
    built = by_number(run_fixture())
    q1 = built[1]
    # Turn 5 ("Its S-M-I-T-H") starts at 4200ms (turns 0-4 above it: 4
    # turns * (word count*400 + 600) -- easiest to just assert the span
    # reaches well past Q1's own one-word turn, which ends at 380ms.
    assert q1["replay_end_ms"] > 3_000, (
        f"Q1's span should reach the spelled-out confirmation; got {q1}")


def test_ordinary_answers_are_not_touched() -> None:
    """The control. Q2 is the respondent's own turn already; Q4-10 are
    marked and spoken in the same single-word turn. Nothing here should be
    widened by either correction -- a fix that improves the two broken
    questions and changes six good ones has not been measured carefully
    enough."""
    built = by_number(run_fixture())
    for n in (2, 4, 5, 6, 7, 8, 9, 10):
        q = built[n]
        # One word at 400ms/word -- each of these spans should be a few
        # hundred milliseconds, not seconds: nothing after it was pulled in.
        span = q["replay_end_ms"] - q["replay_start_ms"]
        assert span < 1_000, f"Q{n} was widened unexpectedly: {q}"


# --- the interviewer widen's own ceiling -------------------------------------

#: Q2 is the same interviewer trick as Q3 above: marked on the WOMAN's
#: question, answered by MAN in the very next turn. That reply turn runs on
#: for a dozen words -- long enough that, unwidened, it would carry the
#: moment Q4 is answered from too. Q3 is left unmarked on purpose: the next
#: numbered question with a marker at all is Q4, and it is Q4's OWN span the
#: ceiling has to be read off, not a question that never had one.
REASSIGN_ENTRIES: list[tuple[str, str, str | None]] = [
    ("WOMAN", "hello there", None),
    ("WOMAN", "could i start by taking your name please", None),
    ("MAN", "teacher", "Q1"),
    ("WOMAN", "have you visited the new museum", "Q2"),
    ("MAN", "no but the roof needs repairing and its too small for everyone", None),
    ("MAN", "cheap", "Q4"),
    ("WOMAN", "next", None),
    ("MAN", "river", "Q5"),
    ("WOMAN", "next", None),
    ("MAN", "lake", "Q6"),
    ("WOMAN", "next", None),
    ("MAN", "forest", "Q7"),
    ("WOMAN", "next", None),
    ("MAN", "desert", "Q8"),
    ("WOMAN", "next", None),
    ("MAN", "island", "Q9"),
    ("WOMAN", "next", None),
    ("MAN", "valley", "Q10"),
]
REASSIGN_KEYS = {1: "teacher", 2: "museum", 3: "sunshine", 4: "cheap",
                 5: "river", 6: "lake", 7: "forest", 8: "desert",
                 9: "island", 10: "valley"}
REASSIGN_FIXTURE = "zzfix-t10-s1"


def run_reassign_fixture() -> dict:
    """Builds :data:`REASSIGN_ENTRIES`, then moves Q4's own marker turn --
    generated after Q2's reply turn, sequentially, by
    :func:`turns_and_alignment` -- to a timestamp INSIDE that reply turn.

    Out of order on purpose. `in_order`'s own docstring names a real case of
    exactly this (`cam12-t3-s4`: Q37 marked on a later turn than Q38), and it
    is what makes the reassign widen's ceiling matter here: with the reply
    turn's own words all in natural, ascending order, the widen could never
    reach past a later question's marker on its own -- the turns are
    sequential and gapped. Bringing Q4's marker inside the reply turn is what
    puts an unmarked next question's evidence (Q3 has none at all) and a
    later marked one's (Q4's own "cheap") both within the reply turn's reach,
    which is the shape the ceiling has to survive.
    """
    work = write_section(REASSIGN_FIXTURE, REASSIGN_ENTRIES,
                         [gap_group(REASSIGN_KEYS)])
    try:
        aligned = json.loads((work / "aligned.json").read_text())
        reply_words = [w for w in aligned if w["turn"] == 4]  # Q2's reply
        cheap = next(w for w in aligned if w["turn"] == 5)  # Q4's own turn
        mid = reply_words[len(reply_words) // 2]
        cheap["start_ms"] = mid["start_ms"]
        cheap["end_ms"] = mid["start_ms"] + 380
        (work / "aligned.json").write_text(json.dumps(aligned))

        rc = bq.build(REASSIGN_FIXTURE)
        assert rc == 0, f"build() refused the fixture (exit {rc})"
        return json.loads((work / "questions.json").read_text())
    finally:
        shutil.rmtree(work)


def test_reassign_widen_stops_at_the_next_marked_question() -> None:
    """The bug: with no ceiling, Q2's widen took the WHOLE of the reply turn
    -- past the point, inside that same turn, where Q4's own marker now sits
    -- handing Q4's answer to Q2's replay window. `next_marker_start` bounds
    it the same way the spelling widen already is."""
    built = by_number(run_reassign_fixture())
    q2, q4 = built[2], built[4]
    assert q2["replay_end_ms"] <= q4["replay_start_ms"], (
        "Q2's widened span reached Q4's own marked evidence; got "
        f"Q2={q2} Q4={q4}")
    # The control half: some widening DID happen -- this is not the ceiling
    # accidentally cancelling the whole feature out. Q2's own turn
    # ("have you visited the new museum") ends well under 5 seconds in.
    assert q2["replay_end_ms"] > 5_000, (
        f"Q2 should still widen into part of the reply turn; got {q2}")


# --- a shared "choose TWO" marker widening into the reply -------------------

#: The `cam18-t3-s3` shape itself: "Q2/3" prints against ONE turn, so
#: `spans[2]` and `spans[3]` come out identical -- and the interviewer widen
#: has to run for BOTH of them, not just the first. Otherwise Q1, Q4-10 are
#: the same control as :data:`REASSIGN_ENTRIES`.
REASSIGN_SHARED_ENTRIES: list[tuple[str, str, str | None]] = [
    ("WOMAN", "hello there", None),
    ("WOMAN", "could i start by taking your name please", None),
    ("MAN", "teacher", "Q1"),
    ("WOMAN", "have you visited the new museum", "Q2/3"),
    ("MAN", "no but the roof needs repairing and its too small for everyone", None),
    ("MAN", "cheap", "Q4"),
    ("WOMAN", "next", None),
    ("MAN", "river", "Q5"),
    ("WOMAN", "next", None),
    ("MAN", "lake", "Q6"),
    ("WOMAN", "next", None),
    ("MAN", "forest", "Q7"),
    ("WOMAN", "next", None),
    ("MAN", "desert", "Q8"),
    ("WOMAN", "next", None),
    ("MAN", "island", "Q9"),
    ("WOMAN", "next", None),
    ("MAN", "valley", "Q10"),
]
REASSIGN_SHARED_KEYS = dict(REASSIGN_KEYS)
REASSIGN_SHARED_FIXTURE = "zzfix-t11-s1"


def run_reassign_shared_fixture() -> dict:
    """Same out-of-order move as :func:`run_reassign_fixture` -- Q4's own
    marker turn dragged inside Q2/3's reply turn -- so this fixture still
    proves the ceiling holds even once the shared span is widening. Without
    it, an unbounded widen and a self-ceilinged one look identical: both
    "pass" a test that never gives the widen anywhere to overreach into.
    """
    work = write_section(REASSIGN_SHARED_FIXTURE, REASSIGN_SHARED_ENTRIES,
                         [gap_group(REASSIGN_SHARED_KEYS)])
    try:
        aligned = json.loads((work / "aligned.json").read_text())
        reply_words = [w for w in aligned if w["turn"] == 4]  # Q2/3's reply
        cheap = next(w for w in aligned if w["turn"] == 5)  # Q4's own turn
        mid = reply_words[len(reply_words) // 2]
        cheap["start_ms"] = mid["start_ms"]
        cheap["end_ms"] = mid["start_ms"] + 380
        (work / "aligned.json").write_text(json.dumps(aligned))

        rc = bq.build(REASSIGN_SHARED_FIXTURE)
        assert rc == 0, f"build() refused the fixture (exit {rc})"
        return json.loads((work / "questions.json").read_text())
    finally:
        shutil.rmtree(work)


def test_shared_marker_pair_still_widens_into_the_reply() -> None:
    """The regression itself: with `spans[2] == spans[3]`, the OLD ceiling
    read 3's start as 2's own -- blocking Q2's widen outright, which is what
    happened to `cam18-t3-s3` Q21/22 (Q3's widen alone still succeeded here,
    because its OWN next distinct number, 4, was never equal to its span --
    the same asymmetry that let the bug hide). 8580ms is Q2/Q3's raw marked
    turn's own end, unwidened; the fix has to carry both past it into the
    reply."""
    built = by_number(run_reassign_shared_fixture())
    q2, q3 = built[2], built[3]
    assert q2["replay_end_ms"] > 9_000, (
        "Q2 should still widen past its own raw marked turn and into the "
        f"reply; got {q2}")
    assert q3["replay_end_ms"] > 9_000, (
        "Q3 should still widen past its own raw marked turn and into the "
        f"reply; got {q3}")


def test_shared_marker_pair_does_not_widen_past_the_next_distinct_question(
        ) -> None:
    """...and never so far that either one reaches the next DISTINCT
    question's own marked evidence -- the same ceiling `in_order`'s
    out-of-order case (`cam12-t3-s4`) already needs, still honoured once the
    question doing the widening is one half of a shared pair."""
    built = by_number(run_reassign_shared_fixture())
    q2, q3, q4 = built[2], built[3], built[4]
    assert q2["replay_end_ms"] <= q4["replay_start_ms"], (
        "Q2's widened span reached Q4's own marked evidence; got "
        f"Q2={q2} Q4={q4}")
    assert q3["replay_end_ms"] <= q4["replay_start_ms"], (
        "Q3's widened span reached Q4's own marked evidence; got "
        f"Q3={q3} Q4={q4}")


CASES = [
    test_dominant_speaker_needs_a_majority_and_enough_data,
    test_spelling_finds_a_letter_by_letter_confirmation,
    test_spelled_out_regex_does_not_fire_on_ordinary_hyphenation,
    test_next_marker_start,
    test_next_marker_start_skips_a_shared_choose_two_span,
    test_interviewer_turn_widens_to_the_reply_that_answers_it,
    test_name_widens_to_where_it_is_spelled,
    test_ordinary_answers_are_not_touched,
    test_reassign_widen_stops_at_the_next_marked_question,
    test_shared_marker_pair_still_widens_into_the_reply,
    test_shared_marker_pair_does_not_widen_past_the_next_distinct_question,
]


if __name__ == "__main__":
    failures = 0
    for case in CASES:
        try:
            case()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {case.__name__}: {exc}")
        else:
            print(f"ok   {case.__name__}")
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    raise SystemExit(1 if failures else 0)
