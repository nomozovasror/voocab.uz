"""Classifying a wrong answer (app/services/mistakes.py).

Pure functions and no database: what is worth pinning down here is the
judgement each rule makes, and the interesting cases are the ones where two
rules could both fire.

The distinction the whole panel rests on is the first two tests: writing
`accomodation` for `accommodation` is a spelling problem and writing nothing
at all is a listening problem, and no amount of "you got 62%" tells anybody
which of those they have.
"""

import pytest

from app.services.mistakes import classify, edit_distance


@pytest.mark.parametrize(
    "given,accepted,expected",
    [
        # Heard it, wrote it badly.
        ("accomodation", ["accommodation"], "spelling"),
        ("recieve", ["receive"], "spelling"),
        ("Whitfield", ["whitfeild"], "spelling"),
        # Didn't hear it at all.
        ("", ["accommodation"], "missed"),
        ("   ", ["accommodation"], "missed"),
        # Heard the word, missed the number of it.
        ("ticket", ["tickets"], "plural"),
        ("tickets", ["ticket"], "plural"),
        ("buses", ["bus"], "plural"),
        # The right value, written a way the marker won't take.
        ("£23.70", ["23.70"], "format"),
        ("September 12", ["12 september"], "format"),
        ("1,200", ["1200"], "format"),
        # Something else entirely.
        ("library", ["swimming pool"], "wrong"),
        ("north", ["south"], "wrong"),
    ],
)
def test_each_kind_of_wrongness(given, accepted, expected) -> None:
    assert classify(given, accepted, None) == expected


def test_a_short_word_is_not_a_misspelling_of_another_short_word() -> None:
    """"van" and "man" are one edit apart and nobody misspelled anything.

    Without the length floor the commonest three-letter mix-up in the exam
    would be filed as a spelling problem and the candidate told to proof-read,
    when what they did was mishear a consonant.
    """
    assert classify("van", ["man"], None) == "wrong"
    assert classify("cat", ["hat"], None) == "wrong"


def test_the_word_limit_beats_being_nearly_right() -> None:
    """A rubric says two words; the candidate wrote four.

    It is checked before spelling on purpose: an answer that contains the
    right words plus two more is not a typing slip, and telling somebody to
    watch their spelling when the problem is that they ignored the rubric
    sends them to fix the wrong thing.
    """
    assert classify("the main train station", ["station"], 2) == "word_limit"
    # Inside the limit, the ordinary rules apply again.
    assert classify("statoin", ["station"], 2) == "spelling"


def test_the_kindest_reading_of_several_accepted_answers_wins() -> None:
    """A gap with variants is one gap. An answer a letter away from one of
    them and unrecognisable against another is a slip, because the candidate
    was plainly reaching for the first."""
    assert classify("bicyle", ["bicycle", "bike"], None) == "spelling"


def test_a_blank_is_missed_even_where_a_limit_would_also_fail() -> None:
    """Nothing typed is nothing heard, whatever the rubric said."""
    assert classify("", ["station"], 1) == "missed"


def test_an_answer_with_no_key_at_all_is_only_ever_wrong() -> None:
    """An unfinished question — no accepted answers — can't be measured
    against anything, and guessing at a kind would be inventing one."""
    assert classify("something", [], None) == "wrong"
    assert classify("something", ["  "], None) == "wrong"


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("", "", 0),
        ("station", "station", 0),
        # Two neighbouring letters swapped: one edit under Damerau, which is
        # the whole reason the distance here isn't plain Levenshtein.
        ("statoin", "station", 1),
        ("accomodation", "accommodation", 1),
        ("cat", "dog", 3),
    ],
)
def test_edit_distance(a, b, expected) -> None:
    assert edit_distance(a, b, cap=5) == expected


def test_edit_distance_gives_up_early() -> None:
    """The caller only ever asks "within two?", so a full matrix over two long
    strings that share nothing is work nobody reads. Past the cap the answer
    is only ever "further than that"."""
    assert edit_distance("a" * 40, "b" * 40, cap=2) == 3
    assert edit_distance("short", "a much longer answer entirely", cap=2) == 3
