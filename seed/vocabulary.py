"""Which words in a passage are worth teaching, decided without a model.

A nine-hundred-word passage holds around four hundred distinct lemmas and a
reader knows most of them. Glossing four hundred words would cost four hundred
words' worth of tokens to produce a list nobody reads; the value is entirely in
the sixty or eighty that a band 5-6 candidate actually stumbles on.

Deciding WHICH sixty is a frequency question, and frequency questions have
frequency answers. That makes this stage deterministic: the same passage gives
the same candidates every run, for free, and a model is only asked about words
that have already survived it.

## The two lists

`wordlists/` carries the New General Service List and the New Academic Word
List, both 1.2 (see the README there for the licence, which requires
attribution). They are a matched pair, built by the same people from the same
corpus with the same method, which is why they can be used together without
the contradictions that GSL-plus-AWL produced: the older pair are from 1953 and
2000, were built independently, and disagree about what counts as general.

NGSL is ~2 800 lemmas covering about 92% of running text. NAWL is ~960 more
that are rare in general English and common in academic English — which is
precisely what an IELTS reading passage is written in, and precisely why the
academic list is KEPT rather than dropped. The two are disjoint but for a
single word.

## Two lines, not one

The cut below is a FREQUENCY cut, and frequency answers a different question
from the one that matters. See :data:`ASK_RANK`: words between the two lines
are asked about and kept only if the model calls them B2 or higher, because
`appropriate` is NGSL rank 1019 and is nevertheless the kind of word that
stops a band 5-6 reader.

## Where the line is drawn, and why it is not at the edge of the list

The obvious rule -- in the NGSL, so the reader knows it -- is wrong, and
measurably so. `phenomenon` is NGSL rank 2096, `undertake` 2036, `constitute`
2357. Those are the words that stop people. What NGSL membership really says
is "in the most frequent 2 809 lemmas of English", and the bottom third of
that is already B2 vocabulary.

So the cut is at **rank 2000**, not at 2809. Measured over Cambridge 11 Test 1
Passage 1 -- 320 distinct lemmas -- the cuts give:

    rank 1000   135 candidates      too many; `urban`, `crop`, `spring`
    rank 1500   109 candidates
    rank 2000    91 candidates      ~70 after proper nouns and possessives
    rank 2809    74 candidates      loses `phenomenon`, `undertake`

The first two thousand are the words a passage is READ with. Past that a
candidate is meeting a word rather than using one.

## Lemmatisation without a parser

The lists ship lemmatised -- `absorb,absorbs,absorbed,absorbing` -- so most
surface forms map straight home by lookup, and that map is better than a
guess because it was made by the people who counted the corpus.

What it does not carry is derivation: `vertically` is not filed under
`vertical`, because it is a different word rather than a form of one. Those
fall through to :func:`stripped`, a handful of suffix rules whose answer is
only accepted when it lands on a lemma the lists already know. A rule that
invents `outdoor` from `outdoors` and finds nothing there has not proved
anything, so `outdoors` stays as it is and is counted off-list -- which is
true: it is not in either list.

That acceptance test is what makes the rules safe enough to be this crude. No
spaCy, no model download, no Python-version gamble on a compiled wheel, and
nothing to install in a venv that already carries Torch.

## What this file does not decide

Multi-word phrases -- `give rise to`, `account for`, `in light of` -- are the
other half of what makes academic prose hard, and no frequency list sees them:
each of their words is separately common. They come from the model in
`read_vocabulary.py`, which reads the whole passage and can see that the three
words are one thing. This file's candidates are single words only, and saying
so plainly is better than a phrase list that would be a guess at the ten most
famous ones.
"""

import functools
import pathlib
import re

WORDLISTS = pathlib.Path(__file__).resolve().parent / "wordlists"

#: Below this NGSL rank a word is offered without argument. See the
#: measurement in the module docstring: the number is the third of the NGSL
#: where meeting a word stops being the same thing as using one.
KNOWN_RANK = 2000

#: And below THIS rank a word is not offered at all. Between the two it is
#: offered PROVISIONALLY -- asked about, and kept only if the model comes
#: back with B2 or higher.
#:
#: The second layer exists because frequency in a native corpus and
#: difficulty for a learner are not the same measurement, and the gap
#: between them has a shape: Latinate academic words are common in written
#: English and late for anybody learning it. `appropriate` is NGSL rank
#: 1019 -- squarely inside "the words a passage is read with" -- and it is
#: B2 vocabulary that stops band 5-6 readers. No threshold on rank can
#: rescue it, because by rank it is not a hard word.
#:
#: The judge is the MODEL rather than a graded word list, and that was a
#: decision made against the alternative rather than for want of one. A
#: CEFR-graded list was fetched and measured: the openly licensed one
#: (CEFR-J plus the Octanove C1/C2 extension) grades `appropriate` A2,
#: `significant` A2 and `establish` A2, because it profiles what a Japanese
#: learner is expected to know and that curve is not this curve. It would
#: have rescued 349 words and not the one the rule was written for. The
#: list that grades these correctly is Oxford's 3000/5000, which is not
#: published under a licence this repository can vendor a copy under.
#:
#: The model is also the better judge on the merits, and for the reason
#: this whole module already rests on: it reads the word IN THIS PASSAGE'S
#: SENSE. A list grades a headword once, for every text in English.
#:
#: 800 rather than lower because the cost is one extra request a passage at
#: this width -- measured on Cambridge 10 Test 1 Passage 1, where the cut
#: takes the candidate count from 106 to 161 -- and because below it the
#: words are the first eight hundred of English, where a B2 reading is the
#: model being agreeable rather than right.
ASK_RANK = 800

#: What the frequency evidence says about one lemma, coarsest first. An
#: ORDERED scale, because the difficulty projection wants to compare passages
#: and a set of unordered names cannot be averaged.
#:
#: `academic` sits beside `wider` rather than above it on purpose: a NAWL word
#: is not rarer than the NGSL tail, it is rare in a different place. What
#: separates them is where a learner would have met it, which is a fact about
#: the learner and not about the corpus.
BANDS = ("core", "common", "wider", "academic", "off-list")

#: A token has to be at least this long to be offered. Two letters is `ha`,
#: `km`, `pH` -- units and abbreviations, which are not vocabulary, and the
#: handful of real two-letter words are all rank 1.
SHORTEST = 3

#: Letters, and the two punctuation marks that live INSIDE English words. The
#: apostrophe is here in both its shapes because a passage read off a printed
#: page carries the typographic one and a passage typed by an author carries
#: the straight one, and `Earth's` has to come out the same either way.
TOKEN = re.compile(r"[A-Za-z][A-Za-z'’\-]*")

#: A sentence has just ended, so the next capital says nothing about whether
#: the word is a name. Deliberately blind to `Dr.` and `e.g.` -- over-counting
#: sentence starts costs a proper noun surviving into the candidate list,
#: which the model then declines to gloss; under-counting costs a real word
#: being thrown away as a name, which nothing recovers.
SENTENCE_END = re.compile(r"[.!?][\"'’”)\]]*\s+$")


class Lists:
    """The three files, read once and answered from memory.

    Held together rather than as three module globals because they are only
    meaningful together: a rank means nothing without knowing the word is in
    the NGSL, and a form means nothing without a lemma to reach.
    """

    def __init__(self) -> None:
        #: lemma -> SFI rank, 1 (`the`) to 2809. NGSL membership IS having a
        #: rank: every lemma in the list has one.
        self.ngsl: dict[str, int] = {}
        #: The academic list. No ranks published for it, and none needed --
        #: being on it is the whole of what it says.
        self.nawl: set[str] = set()
        #: Weekdays, months and the numbers. Part of the NGSL, published
        #: separately because they have no frequency: a corpus's count of
        #: `Tuesday` is a fact about the corpus. Without them `seventeen`
        #: reads as an off-list rare word, which is the opposite of true.
        self.supplementary: set[str] = set()
        #: surface form -> lemma, from both lemmatised lists at once. Built
        #: with `setdefault`, so where two lemmas claim one form the first
        #: file read keeps it; NGSL is read first because the commoner word
        #: is the likelier reading.
        self.form_of: dict[str, str] = {}

        for row in _rows("NGSL_12_lemmatized_for_research.csv"):
            self._take(row)
        for row in _rows("NAWL_12_lemmatized_for_research.csv", "latin-1"):
            self.nawl.add(row[0].lower())
            self._take(row)
        for row in _rows("SUP_lemmatized.csv"):
            self.supplementary.add(row[0].lower())
            self._take(row)
        for row in _rows("NGSL_12_stats.csv"):
            if row[0] == "Lemma":
                continue
            self.ngsl[row[0].lower()] = int(row[1])

    def _take(self, row: list[str]) -> None:
        lemma = row[0].lower()
        for form in row:
            self.form_of.setdefault(form.lower(), lemma)

    def knows(self, lemma: str) -> bool:
        """Whether either list has this lemma as a headword.

        The test :func:`stripped` accepts an answer by. A suffix rule that
        produces a string nothing has ever heard of has not found a lemma,
        it has damaged a word.
        """
        return lemma in self.ngsl or lemma in self.nawl or lemma in self.supplementary


def _rows(name: str, encoding: str = "utf-8-sig") -> list[list[str]]:
    """One vendored CSV, comment lines and blank lines dropped.

    The files are kept exactly as downloaded -- CRLF endings, a byte-order
    mark on the supplementary list, Latin-1 bytes in the academic one, six
    lines of `##` preamble on the NGSL -- so every quirk is absorbed here
    rather than by editing a file somebody may later want to diff against its
    source.

    `csv` is not used because these are not really CSV: the rows are ragged
    by design (a lemma has as many forms as it has) and no field is ever
    quoted.
    """
    text = (WORDLISTS / name).read_bytes().decode(encoding, "replace")
    return [[cell.strip() for cell in line.split(",")]
            for line in text.splitlines()
            if line.strip() and not line.startswith("##")]


@functools.cache
def lists() -> Lists:
    return Lists()


#: Suffix rules, tried in order, each a (ending, replacements) pair. The
#: replacements are tried in turn and the first that lands on a known lemma
#: wins; `""` means simply drop the ending.
#:
#: Longest endings first, because `-ies` has to be tried before `-s` and
#: `-ally` before `-ly`. Beyond that the order is the order of how often the
#: ending is the thing in the way.
SUFFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ies", ("y",)),
    ("ied", ("y",)),
    ("ily", ("y",)),
    ("ially", ("ial", "y")),
    ("ally", ("al", "")),
    ("iest", ("y",)),
    ("ier", ("y",)),
    ("ing", ("", "e")),
    ("ed", ("", "e")),
    ("es", ("", "e")),
    ("ly", ("", "le")),
    ("est", ("", "e")),
    ("er", ("", "e")),
    ("s", ("",)),
)

#: A doubled final consonant before `-ed` or `-ing`: `stopped`, `running`,
#: `occurring`. Undone only after the plain rules have failed, because
#: `pressed` and `stressing` also end in a doubled consonant and there the
#: doubling belongs to the word.
DOUBLED = re.compile(r"([bcdfghjklmnpqrstvwxz])\1(ed|ing)$")

#: A plural of a word neither list has heard of: `rooftops`, `ecosystems`,
#: `hectares`. The rules above cannot reduce these, because their test is
#: landing on a KNOWN lemma and the singular is as unknown as the plural --
#: so without this the same thing arrives twice, as `tray` and `trays`, and
#: gets glossed twice.
#:
#: Accepted untested, which is why the shape is narrow:
#:
#: * `-ss`, `-us`, `-is`, `-as` never reduce. That is where the damage lives
#:   -- `analysis`, `apparatus`, `species`, `bias`, `canvas` are singular
#:   words ending in s, and cutting one produces a string that is not a word
#:   in any language.
#: * `-es` only comes off after a sibilant or an `o`, where English actually
#:   spells a plural that way: `matches`, `boxes`, `tomatoes`. Everywhere
#:   else the `e` belongs to the word and `hectares` is `hectare`, not
#:   `hectar`.
#: * The stem has to be four letters. A three-letter singular that neither
#:   list has heard of barely exists, and requiring the fourth saves `lens`.
#:
#: Two patterns rather than one clever one, because one clever one has to
#: decide whether the `e` of `hectares` belongs to the stem or the ending,
#: and a regex that can go either way goes the wrong way.
SIBILANT_PLURAL = re.compile(r"^(.{2,}(?:ch|sh|[oxz]))es$")
PLURAL = re.compile(r"^(?!.*(?:ss|us|is|as)$)(.{4,})s$")


def stripped(word: str) -> str:
    """`word` reduced to a lemma the lists know, or `word` unchanged.

    The rules are crude and that is safe, because an answer is only accepted
    when the lists recognise it. Every wrong guess lands on a string nothing
    knows and is discarded; the cost of being crude is therefore a missed
    reduction, never a wrong one.
    """
    known = lists()
    for ending, replacements in SUFFIXES:
        if not word.endswith(ending) or len(word) - len(ending) < 2:
            continue
        stem = word[: -len(ending)]
        for replacement in replacements:
            if known.knows(stem + replacement):
                return stem + replacement
    undoubled = DOUBLED.sub(r"\1\2", word)
    if undoubled != word:
        for ending in ("ed", "ing"):
            if undoubled.endswith(ending):
                for candidate in (undoubled[: -len(ending)],
                                  undoubled[: -len(ending)] + "e"):
                    if known.knows(candidate):
                        return candidate
    plural = SIBILANT_PLURAL.match(word) or PLURAL.match(word)
    return plural.group(1) if plural else word


def lemma_for(word: str) -> str:
    """The dictionary form of one surface word.

    Three steps, cheapest first: strip the possessive, ask the published map,
    and only then guess. `Earth's` is `earth` by the first step alone, which
    matters more than it sounds -- possessives are common in prose and every
    one of them would otherwise arrive as its own off-list rarity.
    """
    lowered = word.lower().strip("-'’")
    for possessive in ("'s", "’s", "s'", "s’"):
        if lowered.endswith(possessive) and len(lowered) > len(possessive) + 1:
            lowered = lowered[: -len(possessive)] + ("s" if possessive[0] == "s" else "")
            break
    return lists().form_of.get(lowered) or stripped(lowered)


def band(lemma: str) -> str:
    """Which of :data:`BANDS` this lemma falls in.

    Deterministic, identical across the whole catalogue, and never shown to a
    learner: `NGSL rank 2 400` is a fact about a corpus, and what a learner
    can act on is the CEFR level the model assigns in the next stage. This one
    is for arithmetic -- comparing two passages, which a CEFR average cannot
    do because it drifts from material to material.
    """
    known = lists()
    if lemma in known.supplementary:
        return "core"
    rank = known.ngsl.get(lemma)
    if rank is not None:
        return "core" if rank <= 1000 else "common" if rank <= 2000 else "wider"
    return "academic" if lemma in known.nawl else "off-list"


class Occurrence:
    """One place a lemma stands in the passage.

    A lemma can appear five times; what the gloss and the highlight need is
    ONE of them, and the first is the right one -- it is where a reader meets
    the word, and the sentence around it is the sentence that taught them.
    """

    __slots__ = ("index", "start", "end", "surface", "capitalised", "sentence_start")

    def __init__(self, index: int, start: int, end: int, surface: str,
                 capitalised: bool, sentence_start: bool) -> None:
        #: Which paragraph, by position. The passage coordinate system is the
        #: one the reading highlights already use -- paragraph index plus two
        #: character offsets into that paragraph's plain text -- so a marked
        #: word and a glossed word are anchored the same way and the review
        #: can draw both from one set of rules.
        self.index = index
        self.start = start
        self.end = end
        self.surface = surface
        self.capitalised = capitalised
        self.sentence_start = sentence_start


def scan(paragraphs: list[dict]) -> dict[str, list[Occurrence]]:
    """Every lemma in the passage, with every place it stands.

    Paragraphs come in as the `passage.json` shape: a list of
    `{"label": "A" | None, "text": "..."}`.
    """
    found: dict[str, list[Occurrence]] = {}
    for index, paragraph in enumerate(paragraphs):
        text = paragraph.get("text") or ""
        for match in TOKEN.finditer(text):
            surface = match.group(0)
            lemma = lemma_for(surface)
            if not lemma:
                continue
            before = text[: match.start()]
            found.setdefault(lemma, []).append(Occurrence(
                index, match.start(), match.end(), surface,
                capitalised=surface[0].isupper(),
                sentence_start=not before.strip() or bool(SENTENCE_END.search(before)),
            ))
    return found


def is_name(places: list[Occurrence]) -> bool:
    """Whether this lemma is a proper noun rather than a word.

    Capitalisation alone does not say: every sentence starts with one. What
    says it is capitalisation somewhere a sentence did NOT start -- `Brazil`
    mid-sentence -- together with never appearing in lower case anywhere in
    the passage. A word that is sometimes `Spring` and sometimes `spring` is
    a word; one that is always `Brazil` is a name.

    What this cannot see: a name that only ever OPENS a sentence ("Alan
    Macfarlane, professor of...", "Google and a number of other...") --
    about a hundred of them reached the lexicon that way. They are left to
    the gloss prompt (`read_vocabulary.WORDS_PROMPT` answers a name with an
    empty lemma, which drops it) rather than widened here, because a real
    word that only opens a sentence looks exactly the same to this test.
    """
    return (all(place.capitalised for place in places)
            and any(not place.sentence_start for place in places))


def candidates(paragraphs: list[dict],
               claimed: set[tuple[int, int, int]] | None = None) -> list[dict]:
    """The words in this passage worth asking a model about.

    In passage order: a list ordered by where the reader meets each word
    reads as a walk through the text, which is also the order the review
    shows them in.

    ``claimed`` is the spans a MULTI-WORD term has already taken, and what
    it does is decide WHERE a word is offered from -- and, for one class of
    word, whether it is offered at all.

    Every lemma prefers an occurrence outside every claimed span, so a
    passage that says `machine learning` in paragraph 1 and `children learn
    quickly` in paragraph 4 teaches `learn` from paragraph 4. What happens
    when there is no such occurrence depends on the word:

    * A **provisional** word -- one the frequency lists call known, below
      `KNOWN_RANK` -- belongs to the term and is dropped. It was only ever
      here on suspicion, and a common word whose single appearance is
      inside `climate change` or `ice age` is not teaching anybody
      anything on its own.
    * Any **other** word keeps its place inside the term. It is a word the
      frequency filter offers outright, and it is the half of the term the
      reader actually cannot read: `sedentary lifestyle`, `righteous
      indignation`, `genetic algorithm`, `high-fructose corn syrup`. The
      phrase is transparent the moment the word is known, and dropping the
      word to keep the phrase teaches the collocation to somebody who
      cannot read either half of it.

    Measured before the split was put in: claiming every span cost 745
    lemmas across the corpus, and 485 of them were `wider`, `academic` or
    off-list -- `sedentary`, `indignation`, `algorithm`, `hormone`,
    `spectrum`, `stimulus`, `deficiency`. The 260 that were `core` or
    `common` are the ones worth losing, and they are exactly the ones this
    rule still loses.

    The word's entry standing beside the term's is the shape this feature
    has always had -- `rise` and `give rise to` are two entries over
    overlapping spans, and a tap inside both offers the phrase first with
    the word underneath. What must never happen is the word's entry
    carrying the TERM's meaning, and that is a rule about the prompt (see
    `read_vocabulary.WORDS_PROMPT`) rather than about which words exist.
    """
    taken = claimed or set()

    def free(place: "Occurrence") -> bool:
        return not any(index == place.index
                       and place.start < end and start < place.end
                       for index, start, end in taken)

    keep: list[dict] = []
    for lemma, places in scan(paragraphs).items():
        if len(lemma) < SHORTEST or is_name(places):
            continue
        rank = lists().ngsl.get(lemma)
        if rank is not None and rank <= ASK_RANK:
            continue
        if lemma in lists().supplementary:
            continue
        provisional = rank is not None and rank <= KNOWN_RANK
        standing = [place for place in places if free(place)]
        if not standing:
            if provisional:
                continue
            standing = places
        where = standing[0]
        keep.append({
            "lemma": lemma,
            "surface": where.surface,
            "index": where.index,
            "start": where.start,
            "end": where.end,
            # Everywhere ELSE the same word stands, so the passage can mark
            # every occurrence rather than only the first. A reader who
            # meets `solutionism` twice and sees one of them marked does
            # not conclude that the second is a different word; they
            # conclude the list is incomplete.
            #
            # Measured before this was carried: 17% of word entries appear
            # more than once in their passage, and 8 864 occurrences across
            # the corpus had no mark on them.
            "again": [[place.index, place.start, place.end]
                      for place in standing[1:]],
            "frequency_band": band(lemma),
            "occurrences": len(standing),
            # Asked about on suspicion rather than on evidence. The caller
            # keeps a provisional entry only where the model answers B2 or
            # higher -- see ASK_RANK. Never a reason to skip the ASK: the
            # cost of asking is a line in a batch, and the cost of not
            # asking is the word being invisible for ever.
            "provisional": provisional,
        })
    keep.sort(key=lambda entry: (entry["index"], entry["start"]))
    return keep


def profile(paragraphs: list[dict]) -> dict:
    """How hard this passage's vocabulary is, in figures that compare.

    Running-word counts rather than distinct-lemma counts, because what makes
    a passage heavy going is how often the reader is stopped, and a rare word
    used six times stops them six times.

    The one figure worth quoting is `off_list_share`: the proportion of the
    passage that is outside both lists. It is measurable, it is the same
    measurement on every passage in the catalogue, and it is what "this one is
    harder than that one" can honestly mean before anybody has sat either.
    """
    counts = dict.fromkeys(BANDS, 0)
    for lemma, places in scan(paragraphs).items():
        counts[band(lemma)] += len(places)
    total = sum(counts.values())
    return {
        "words": total,
        "bands": counts,
        "off_list_share": round(counts["off-list"] / total, 4) if total else 0.0,
    }
