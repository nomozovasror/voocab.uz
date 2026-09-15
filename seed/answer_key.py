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
import unicodedata

#: A separator with space around it alternates whole PHRASES:
#: "(£)115 / a hundred (and) fifteen" is two ways of saying the amount.
#: A separator with space around it alternates whole PHRASES -- and space on
#: ONE side is the same thing typed or scanned imperfectly. "285/ two hundred
#: and eighty-five" is two ways of writing one number; read as a word-level
#: alternation it came out as the single answer "285 two hundred and eighty-
#: five", which is not a thing anybody would write. Nobody puts a space after
#: the slash in an intra-word alternation, so the asymmetry is the tell.
#:
#: A semicolon does the same without needing any space, and is how the
#: Official Cambridge Guide prints the two answers of a pair: "37&38 IN EITHER
#: ORDER ships; horses". No other book in this corpus uses one anywhere.
PHRASE_ALT = re.compile(r"\s*[/|]\s+|\s+[/|]\s*|\s*;\s*")
#: One with no space alternates a single WORD inside the phrase:
#: "urban centres/centers" is "urban centres" or "urban centers", never
#: "centers" on its own. Splitting on the separator regardless of spacing --
#: the first version of this -- silently dropped the "urban".
WORD_ALT = re.compile(r"[/|]")
OPTIONAL = re.compile(r"\(([^)]*)\)")
#: A branch that is only digits, with the separators a number is written with.
NUMERIC = re.compile(r"^[\d.,]+$")
#: A number said rather than written. Enough of them to recognise an amount;
#: this is a test for "is the other side of the slash this same number", not a
#: parser.
NUMBER_WORD = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thir|four|fif|six|seven|eigh|nine)(?:teen|ty)?\b|\b(?:hundred|thousand|"
    r"million|dozen)\b", re.I)
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


def alternates_whole(phrase: str, tokens: list[str]) -> bool:
    """Is an unspaced separator alternating the PHRASE rather than a word?

    This is the limit the module docstring predicted, and it turned up in
    fifteen keys. Two shapes, both of which expand to nonsense word by word.

    **Several branches are more than one word.** "13th May/13 May/thirteenth
    May/May 13/May 13th/May thirteenth" is six ways of writing one date;
    split token by token it produced sixteen strings beginning "13th May May
    May". "5/five km/kilometres/kilometers" is NOT that -- only one of its
    four branches has a space, and the two alternations in it really are
    independent: five km, 5 kilometres, and so on.

    **Two branches of one token are the same number.** "3000/3,000/three
    thousand" is one amount written three ways, and the trailing "thousand"
    belongs to the third alone; word by word it gave "3000 thousand", so the
    one thing a candidate would write -- 3,000 -- was marked WRONG. Telling it
    from "7/7th April", where the trailing word belongs to both, cannot be
    done by counting: it is done by noticing that 3000 and 3,000 are the same
    number and 7 and 7th are not.
    """
    branches = [part.strip() for part in WORD_ALT.split(phrase) if part.strip()]
    if sum(1 for branch in branches if " " in branch) >= 2:
        return True
    # A word-level expansion that puts a word next to a word containing it is
    # nonsense: "website/web site" is two spellings of one thing, and token by
    # token it gave "website site". Only one of its branches has a space, so
    # the rule above cannot see it; what gives it away is the result.
    for combination in _word_level(tokens):
        words = combination.split()
        if any(len(a) > 2 and len(b) > 2 and (a.lower() in b.lower()
                                              or b.lower() in a.lower())
               for a, b in zip(words, words[1:])):
            return True
    for token in tokens:
        numbers = [branch.replace(",", "") for branch in WORD_ALT.split(token)
                   if NUMERIC.match(branch)]
        if len(numbers) != len(set(numbers)):
            return True
    # **One separator, a number on one side and the same number in words on
    # the other.** "125|one hundred and twenty-five" is one amount written
    # twice, and the trailing words belong to the second alone -- word by word
    # it gave "125 hundred and twenty-five". The count of separators is what
    # keeps this off "5/five km/kilometres/kilometers", where there are three
    # and the two alternations really are independent: five km, 5 kilometres.
    if sum(len(WORD_ALT.split(token)) - 1 for token in tokens) == 1:
        if (any(NUMERIC.match(branch) for branch in branches)
                and any(NUMBER_WORD.search(branch) for branch in branches)):
            return True
    return False


def expand_word_alternatives(phrase: str) -> list[str]:
    """Every combination of the word-level alternations in one phrase.

    ``urban centres/centers`` -> ``urban centres``, ``urban centers``. The
    words that carry no separator are shared by every result, which is the
    whole point of the distinction."""
    tokens = phrase.split()
    if not any(WORD_ALT.search(token) for token in tokens):
        return [phrase]
    if alternates_whole(phrase, tokens):
        return [part.strip() for part in WORD_ALT.split(phrase) if part.strip()]
    return _word_level(tokens)


def _word_level(tokens: list[str]) -> list[str]:
    """Every combination, treating each separator as alternating one word."""
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


#: A name the recording spells out and the key prints the same way:
#: "M-A-U-G-H-A-N". The candidate writes MAUGHAN. Left as it is, the only
#: accepted answer is a string with six hyphens in it, which nobody types.
SPELLED_OUT = re.compile(r"^[A-Za-z](?:\s*-\s*[A-Za-z]){2,}$")


def spelled(text: str) -> str | None:
    """The word a spelled-out answer spells, if that is what it is."""
    return re.sub(r"[\s-]", "", text) if SPELLED_OUT.match(text.strip()) else None


#: What decomposition leaves behind that a keyboard still does not have.
#: "½" decomposes to "1", U+2044 FRACTION SLASH, "2" -- three characters,
#: every one of them printable, and the middle one no more typeable than the
#: fraction was. Every character in this table has turned up in a printed key
#: or in the decomposition of one.
TYPEABLE = str.maketrans({"\u2044": "/", "\u2019": "'", "\u2018": "'",
                          "\u201c": '"', "\u201d": '"',
                          "\u2013": "-", "\u2014": "-", "\u00a0": " "})


def plain(text: str) -> str | None:
    """The same answer written with characters a keyboard has.

    A learner types on the keyboard in front of them. "café" is what the book
    prints and "cafe" is what gets typed, and `normalize_answer` in the
    backend is deliberately dumb -- trim, collapse, lowercase -- so the two do
    not compare equal. Every accepted phrasing has to be in the list, and this
    is one.

    Decomposing is not enough on its own. Cambridge 19 prints "½" among the
    accepted answers for a time, and NFKD turns that into "1", a FRACTION
    SLASH and "2" -- which reads as "1/2" and is not: the slash is U+2044 and
    a learner typing 1/2 still gets it wrong. Whatever survives the
    decomposition is translated to the character it looks like.
    """
    bare = "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c)).translate(TYPEABLE)
    return bare if bare != text else None


#: A hyphen between two words, which is a keystroke a candidate may or may not
#: make. "self-employed", "twenty-five", "bar-code".
JOINED = re.compile(r"(?<=[A-Za-z0-9])-(?=[A-Za-z0-9])")
#: A number read out in groups -- a phone number, a reference. "021 785 6361".
IN_GROUPS = re.compile(r"^\d+(?:\s+\d+)+$")


def unhyphenated(text: str) -> str | None:
    """The same answer with its hyphens typed as spaces, if it has any.

    "two hundred and eighty-five" is how the book prints it and "eighty five"
    is how half the people who hear it will type it. A space rather than
    nothing, because the other way round breaks the words that are genuinely
    two: "self-employed" is "self employed", never "selfemployed". Where a
    book means the joined-up form it says so in its own notation --
    "bar(-)code" -- and that already expands to both.
    """
    # Not a name the book spells out: "M-A-U-G-H-A-N" is already accepted as
    # the word it spells, and the hyphens there join letters rather than
    # words -- which is what this rule is about.
    if spelled(text):
        return None
    bare = JOINED.sub(" ", text)
    return bare if bare != text else None


def ungrouped(text: str) -> str | None:
    """A number written in groups, with the groups closed up.

    A phone number is dictated "oh two one, seven eight five, six three six
    one" and the book prints "021 785 6361"; a candidate writes it either way
    and neither is a different number.
    """
    return text.replace(" ", "") if IN_GROUPS.match(text.strip()) else None


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
                # The word a spelled-out name spells comes FIRST, because it
                # is both the answer a candidate writes and the one the review
                # page shows them afterwards.
                for form in ([spelled(variant)] if spelled(variant) else []) + [variant]:
                    if form and form not in out:
                        out.append(form)
    # The forms nobody printed but somebody will type, appended after every
    # form that IS printed so the review page still shows the book's own
    # wording first.
    for variant in list(out):
        for also in (plain(variant), unhyphenated(variant), ungrouped(variant)):
            if also and also not in out:
                out.append(also)
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
    # A number against a word alternates the whole phrase: "3000 thousand" is
    # not an answer anybody would write, and leaving it in marked "3,000" wrong.
    ("3000/3,000/three thousand", ["3000", "3,000", "three thousand"]),
    # And the shapes it must NOT mistake for that.
    ("5/five km/kilometres/kilometers",
     ["5 km", "5 kilometres", "5 kilometers",
      "five km", "five kilometres", "five kilometers"]),
    ("7/7th April", ["7 April", "7th April"]),
    ("13th May/13 May/May 13", ["13th May", "13 May", "May 13"]),
    # Two spellings of one thing, which token by token gave "website site".
    ("website/web site", ["website", "web site"]),
    # A name the recording spells out. The candidate writes the word.
    ("M-A-U-G-H-A-N", ["MAUGHAN", "M-A-U-G-H-A-N"]),
    # A letter the learner's keyboard does not have.
    ("café", ["café", "cafe"]),
    # A separator with space on one side only, which is the same separator.
    ("285/ two hundred and eighty-five",
     ["285", "two hundred and eighty-five", "two hundred and eighty five"]),
    # A hyphen is a keystroke a candidate may not make.
    ("self-employed", ["self-employed", "self employed"]),
    # A number dictated in groups, typed either way.
    ("021 785 6361", ["021 785 6361", "0217856361"]),
    # One separator, a number on one side and the same number in words on the
    # other -- which word by word gave "125 hundred and twenty-five".
    ("125|one hundred and twenty-five",
     ["125", "one hundred and twenty-five", "one hundred and twenty five"]),
    ("23.50/twenty-three fifty",
     ["23.50", "twenty-three fifty", "twenty three fifty"]),
    # Cambridge 19 really does print this among the answers to a time, and
    # decomposition alone turns it into a fraction slash nobody can type.
    # The typeable forms are appended after the printed ones, which is why
    # "1/2" comes last rather than beside the "½" it stands in for.
    ("3.30 / three thirty / ½ / half 3", ["3.30", "three thirty", "½",
                                          "half 3", "1/2"]),
    ("(the) Fauré Room", ["Fauré Room", "the Fauré Room",
                          "Faure Room", "the Faure Room"]),
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
