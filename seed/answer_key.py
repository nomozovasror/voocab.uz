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
#: A semicolon does the same without needing spaces around it, and is how the
#: Official Cambridge Guide prints the two answers of a pair: "37&38 IN EITHER
#: ORDER ships; horses". No other book in this corpus uses one anywhere.
PHRASE_ALT = re.compile(r"\s+[/|]\s+|\s*;\s*")
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


#: Editorial asides, which are not notation and must not become answers.
#: IELTS Trainer writes them into the key line itself: "route [alterations =
#: changes]" explains how the question paraphrased the recording, and
#: "ballantyne (you can write this in small or capital letters)" is advice to
#: the candidate. Left in, the first marks a learner who writes "route" WRONG,
#: because the only accepted string would be the whole line.
#:
#: Square brackets are unambiguous -- Cambridge notation has no use for them,
#: and no line in the 176 sections read before this book contains one.
NOTE_BRACKETED = re.compile(r"\s*\[[^\]]*\]")
#: A parenthesis is not, because parentheses ARE notation: "(£)115", "(and)",
#: "(swimming) pool". What separates a note from an optional word is length --
#: every optional group in this corpus is one to three words, and an aside is
#: a sentence. Four is the line, and it is drawn above the longest real group
#: seen rather than at the shortest aside, because marking a right answer
#: wrong is the worse failure of the two.
#: `[^()]*` so a group cannot run from one parenthesis to the NEXT one's
#: closer: "(£)115 / a hundred (and) fifteen" spans five words between its
#: first "(" and its last ")", and a pattern that allowed that ate the answer.
NOTE_PARENTHESISED = re.compile(r"\s*\(([^()]*)\)")
#: Above the longest real optional group in the corpus, below the shortest
#: aside.
NOTE_WORDS = 4


def strip_notes(text: str) -> str:
    """The key line without the editor talking to the reader."""
    plain = NOTE_BRACKETED.sub("", text)
    plain = NOTE_PARENTHESISED.sub(
        lambda group: "" if len(group.group(1).split()) > NOTE_WORDS else group.group(0),
        plain)
    return plain.strip()


def parse_answer(text: str) -> list[str]:
    """One printed key line -> every accepted answer, de-duplicated.

    Three expansions, applied outside in: phrase alternatives, then word
    alternatives within each phrase, then the optional groups within those --
    after any editorial note is taken out of the line.
    """
    out: list[str] = []
    for phrase in PHRASE_ALT.split(strip_notes(text)):
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
    ("ships; horses", ["ships", "horses"]),           # the Guide's pair notation
    # IELTS Trainer's asides. The first is why this exists: without stripping,
    # the one accepted answer is the whole line and "route" is marked wrong.
    ("route [alterations = changes]", ["route"]),
    ("ballantyne (you can write this in small or capital letters)", ["ballantyne"]),
    # And the notation it must not mistake for one.
    ("(no more than) two", ["two", "no more than two"]),
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
