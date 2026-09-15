"""What kind of mistake a wrong answer was.

A percentage tells a candidate they lost marks. It does not tell them why, and
"why" is the only part they can act on. Two wrong answers to the same question
can mean opposite things:

    heard "accommodation", wrote "accomodation"   -> a spelling problem
    heard nothing, wrote nothing                  -> a listening problem

The first is fixed by proof-reading, the second by listening again. A panel
that files both under "wrong" has thrown away the difference.

This is possible at all because ``QuestionAttempt.given_answer`` stores what
the candidate actually typed, unmodified — grading normalizes only for the
comparison and never writes the normalized form back. Every classification
below is a comparison between that raw string and the answers the author
accepted.

**Text answers only.** A multiple-choice answer is a letter: there is no
spelling in "b", and the interesting question there is which distractor pulls
this candidate — a different analysis, for the full statistics page. Groups
answered by letter are excluded before anything here runs.
"""

import re
from typing import Literal

from app.services.answers import normalize_answer

#: The kinds, in the order a tie between two of them is broken. The order is
#: from most specific to least: a blank answer is only ever "missed", a
#: one-letter difference is only "spelling" if it isn't the plural rule, and
#: "wrong" is what is left when nothing else fits.
MistakeKind = Literal[
    "missed",
    "word_limit",
    "plural",
    "format",
    "spelling",
    "wrong",
]

#: What each kind is called in the interface, and the sentence that says what
#: it means about the candidate. The label lives here rather than in the UI so
#: the name and the rule that produces it cannot drift apart.
MISTAKE_LABEL: dict[str, str] = {
    "spelling": "Spelling",
    "missed": "Missed entirely",
    "plural": "Singular / plural",
    "word_limit": "Over word limit",
    "format": "Number / date format",
    "wrong": "Wrong answer",
}

MISTAKE_MEANING: dict[str, str] = {
    "spelling": "You heard the answer correctly but wrote it wrong.",
    "missed": "You left these blank — the answer went past you.",
    "plural": "The word was right; the singular or plural wasn't.",
    "word_limit": "The answer was there, but longer than the rubric allows.",
    "format": "The right value, written a way the marker doesn't accept.",
    "wrong": "A different answer entirely — these are the ones to listen for again.",
}

#: How far apart two strings may be and still count as the same word typed
#: badly — and it depends on how long the word is, because that is what
#: separates a slip from a different word.
#:
#: One edit is allowed from five letters up: "bicyle" for "bicycle" is a
#: dropped letter, and a transposition ("recieve") counts as one edit rather
#: than two, which is why the distance below is Damerau's and not plain
#: Levenshtein.
#:
#: Two edits are allowed only from nine letters up. "north" and "south" are
#: two edits apart and nobody misspelled anything; "accomodaton" and
#: "accommodation" are two edits apart and obviously the same word being
#: reached for.
#:
#: None of this is exact and it cannot be: "hotel" and "hostel" are one edit
#: apart and are two words. The rule leans towards NOT claiming spelling,
#: because the claim the panel makes on the back of it — "you heard the
#: answer correctly" — is a strong one, and sending somebody to proof-read
#: when their problem is hearing is worse than the reverse.
MIN_SPELLING_LENGTH = 5
LONG_WORD_LENGTH = 9
MAX_SPELLING_EDITS = 2

_WORD_RE = re.compile(r"\S+")
#: A number, with or without a currency mark, thousands separators or a
#: decimal part: 23, £23.70, 1,200, 23%.
_NUMBER_RE = re.compile(r"^[£$€]?\s*\d[\d,]*(?:\.\d+)?\s*%?$")
_DIGITS_RE = re.compile(r"\d+")
_MONTHS = (
    "january february march april may june july august september october "
    "november december"
).split()


def edit_distance(a: str, b: str, cap: int = 3) -> int:
    """Damerau-Levenshtein distance, abandoned once it passes ``cap``.

    Damerau rather than plain Levenshtein because of one very common slip:
    "recieve" for "receive" is two neighbouring letters swapped, which
    Levenshtein scores as two edits and every typist knows to be one. Counting
    it as one is the difference between recognising the commonest misspelling
    in English and filing it as a different word.

    The cap keeps it cheap: the caller only ever asks "is this within two",
    and a full matrix over two long answers to learn that they are eleven
    apart is work nobody reads.
    """
    if abs(len(a) - len(b)) > cap:
        return cap + 1

    # Two rows back, because a transposition looks at i-2 and j-2.
    before_previous: list[int] = []
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            cost = min(
                previous[j] + 1,  # deletion
                current[j - 1] + 1,  # insertion
                previous[j - 1] + (ca != cb),  # substitution
            )
            if (
                i > 1
                and j > 1
                and ca == b[j - 2]
                and a[i - 2] == cb
            ):
                cost = min(cost, before_previous[j - 2] + 1)  # transposition
            current.append(cost)
        if min(current) > cap:
            return cap + 1
        before_previous, previous = previous, current
    return previous[-1]


def _differs_by_plural(given: str, accepted: str) -> bool:
    """Whether the only difference is a trailing plural.

    Both directions: writing "ticket" for "tickets" is the same slip as
    writing "tickets" for "ticket", and a candidate who does either heard the
    word correctly.
    """
    for short, long in ((given, accepted), (accepted, given)):
        if long == short + "s" or long == short + "es":
            return True
    return False


def _looks_numeric(text: str) -> bool:
    return bool(_NUMBER_RE.match(text)) or any(month in text for month in _MONTHS)


def _same_value_different_shape(given: str, accepted: str) -> bool:
    """Whether two answers carry the same number or date, written differently.

    "£23.70" against "23.70", "12 September" against "September 12". Compared
    on the digits alone, plus the month name where there is one — everything
    else in those strings is presentation, which is exactly what this kind of
    mistake is about.
    """
    if not (_looks_numeric(given) and _looks_numeric(accepted)):
        return False

    given_digits = _DIGITS_RE.findall(given.replace(",", ""))
    accepted_digits = _DIGITS_RE.findall(accepted.replace(",", ""))
    if given_digits != accepted_digits:
        return False

    given_months = [m for m in _MONTHS if m in given]
    accepted_months = [m for m in _MONTHS if m in accepted]
    if given_months != accepted_months:
        return False

    # Same digits and the same month, so if the strings still differ, what
    # differs is how they are written.
    return given != accepted


def classify(
    given_answer: str,
    correct_answers: list[str],
    word_limit: int | None,
) -> MistakeKind:
    """What kind of mistake this wrong answer was.

    Only ever called for answers grading already marked wrong — this does not
    decide right from wrong, only what shape the wrongness had.

    Tested against every accepted variant and the *kindest* verdict wins: an
    answer one edit from one accepted phrasing and unrecognisable against
    another is a spelling slip, because the candidate was plainly reaching for
    the first.
    """
    given = normalize_answer(given_answer)
    if not given:
        return "missed"

    if word_limit is not None and len(_WORD_RE.findall(given)) > word_limit:
        return "word_limit"

    accepted_all = [normalize_answer(a) for a in correct_answers if a.strip()]
    if not accepted_all:
        return "wrong"

    if any(_differs_by_plural(given, accepted) for accepted in accepted_all):
        return "plural"

    if any(_same_value_different_shape(given, accepted) for accepted in accepted_all):
        return "format"

    for accepted in accepted_all:
        if len(accepted) < MIN_SPELLING_LENGTH:
            continue
        allowed = (
            MAX_SPELLING_EDITS
            if len(accepted) >= LONG_WORD_LENGTH
            else 1
        )
        if edit_distance(given, accepted, cap=allowed) <= allowed:
            return "spelling"

    return "wrong"
