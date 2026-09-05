"""Cambridge answer-key notation -> the accepted variants a gap is marked on.

The key prints one line per question in a shorthand that has to be expanded,
not stored: `app.services.answers.normalize_answer` is deliberately dumb --
trim, collapse whitespace, lowercase, and nothing else. No fuzzy matching, no
number-word conversion. So every phrasing a candidate may write has to be in
`correct_answers` as its own string, or a right answer is marked wrong.

Two marks do the work, and they compose:

* ``/`` separates alternatives -- ``floor/floors``
* ``(...)`` wraps optional words -- ``(£)115`` is right with or without the
  sign, ``a hundred (and) fifteen`` with or without the "and"

`(£)115 / a hundred (and) fifteen` is therefore four accepted answers, and
getting that wrong in either direction is a bug a learner meets rather than a
test does: too few variants marks correct answers wrong, too many marks wrong
ones right.

Cambridge 20 prints the same idea with different marks -- `|` for alternatives
rather than `/` -- which `ALT_SEPARATORS` covers.

Not handled here, because it is not a fact about one question: `21&22 IN
EITHER ORDER`, where two question numbers share one pair of answers. That is a
statement about how the questions are grouped, and it belongs to whatever
builds the QuestionGroup -- see `question_marks()` in the backend.

**Known limit.** The unspaced separator is read at word level, which is right
for every instance in this corpus so far (`urban centres/centers` is "urban
centres" or "urban centers", never "centers" alone). A key writing `car
park/carpark` would mean the whole phrase and would come out of here as "car
carpark", because the left side of the alternation spans a space that the
notation does not mark. No such line has turned up yet, so there is no rule
here for it: guessing at data we have not seen is how the two rules above get
quietly wrong. Check for the shape when reviewing a flagged section, and add a
case here with the real line when one appears.
"""

import itertools
import re

#: A separator with space around it alternates whole PHRASES:
#: "(£)115 / a hundred (and) fifteen" is two ways of saying the amount.
PHRASE_ALT = re.compile(r"\s+[/|]\s+")
#: One with no space alternates a single WORD inside the phrase:
#: "urban centres/centers" is "urban centres" or "urban centers", never
#: "centers" on its own. Splitting on the separator regardless of spacing --
#: the first version of this -- silently dropped the "urban".
WORD_ALT = re.compile(r"[/|]")
OPTIONAL = re.compile(r"\(([^)]*)\)")
WHITESPACE = re.compile(r"\s+")


def expand_optional(text: str) -> list[str]:
    """Every combination of the optional groups in one alternative.

    ``a hundred (and) fifteen`` -> ``a hundred fifteen``, ``a hundred and
    fifteen``. Order is kept stable -- longest first would look tidier and
    would also make the diffs between two runs meaningless.
    """
    parts: list[str] = []
    choices: list[tuple[str, ...]] = []
    cursor = 0
    for match in OPTIONAL.finditer(text):
        parts.append(text[cursor:match.start()])
        choices.append(("", match.group(1)))
        cursor = match.end()
    parts.append(text[cursor:])

    if not choices:
        return [WHITESPACE.sub(" ", text).strip()]

    out: list[str] = []
    for combination in itertools.product(*choices):
        joined = "".join(a + b for a, b in itertools.zip_longest(
            parts, combination, fillvalue=""))
        cleaned = WHITESPACE.sub(" ", joined).strip()
        if cleaned and cleaned not in out:
            out.append(cleaned)
    return out


def expand_word_alternatives(phrase: str) -> list[str]:
    """Every combination of the word-level alternations in one phrase.

    ``urban centres/centers`` -> ``urban centres``, ``urban centers``. The
    words that carry no separator are shared by every result, which is the
    whole point of the distinction."""
    tokens = phrase.split()
    if not any(WORD_ALT.search(token) for token in tokens):
        return [phrase]
    choices = [WORD_ALT.split(token) if WORD_ALT.search(token) else [token]
               for token in tokens]
    return [" ".join(combination) for combination in itertools.product(*choices)]


def parse_answer(text: str) -> list[str]:
    """One printed key line -> every accepted answer, de-duplicated.

    Three expansions, applied outside in: phrase alternatives, then word
    alternatives within each phrase, then the optional groups within those.
    """
    out: list[str] = []
    for phrase in PHRASE_ALT.split(text.strip()):
        for worded in expand_word_alternatives(phrase):
            for variant in expand_optional(worded):
                if variant and variant not in out:
                    out.append(variant)
    return out


CASES = [
    ("Charlton", ["Charlton"]),
    ("floor/floors", ["floor", "floors"]),
    ("decoration/decorations", ["decoration", "decorations"]),
    ("(£)115 / a hundred (and) fifteen",
     ["115", "£115", "a hundred fifteen", "a hundred and fifteen"]),
    ("(lifting) frame", ["frame", "lifting frame"]),
    ("oxygen/O2", ["oxygen", "O2"]),
    ("4.30 (pm) / half past four", ["4.30", "4.30 pm", "half past four"]),
    ("30|thirty", ["30", "thirty"]),                      # Cambridge 20's mark
    ("urban centres/centers", ["urban centres", "urban centers"]),
    ("(stacked) trays", ["trays", "stacked trays"]),
]

if __name__ == "__main__":
    failures = 0
    for source, expected in CASES:
        got = parse_answer(source)
        ok = got == expected
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {source!r:<36} -> {got}")
        if not ok:
            print(f"     expected {expected}")
    print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
    raise SystemExit(1 if failures else 0)
