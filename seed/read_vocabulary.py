"""Gloss a passage's hard words, once, in the passage's own sense.

    seed/.venv/bin/python seed/read_vocabulary.py cam11-t1-p1
    seed/.venv/bin/python seed/read_vocabulary.py --book 11
    seed/.venv/bin/python seed/read_vocabulary.py --report

`vocabulary.py` has already decided WHICH words, from frequency alone and for
nothing. This asks a model the part frequency cannot answer: what the word
means HERE.

## Why the meaning has to be contextual, and why that settles the architecture

An IELTS passage is full of words with several senses -- `spring`, `bank`,
`figure`, `address`, `subject`, `constitute` -- and a dictionary answers with
all of them. A reader at band 5-6 then picks one, and picks wrong often
enough that the help is worse than none. The sense a passage uses is not a
property of the word; it is a property of the word AND the passage, and only
something that has read the passage can say it.

That is also why this runs at seed time rather than when a learner taps a
word. The expensive derivative is made once and used for ever, exactly like
the transcript: it works offline, it costs nothing per reader, the price is
known in advance, and the site does not stop teaching vocabulary on a morning
when Groq is down.

## Thirty words at a time, because eighty-five did not come back

The first shape of this stage asked one question covering the whole candidate
list. It does not work, and the way it fails is worth writing down: the reply
is not refused and not malformed, it simply STOPS -- eighteen thousand
characters in, mid-string, three times at three temperatures. Eighty-five
entries of six fields each is more output than the model will produce in one
turn, and `ask_json`'s retry cannot help with a ceiling.

So the words go in batches of thirty, and the passage goes with each one.
That repeats about 1 200 input tokens per batch, which at Groq's rates is a
tenth of a cent for the whole corpus -- the input side of this stage was
never where the money was. What it buys is a question the model finishes, and
finishing is the only property that matters.

The phrases are their own call for the same reason they are their own task:
they are not drawn from the candidate list, they are found in the passage,
and a question that is answered from a different source deserves to be asked
on its own.

Multi-word phrases are the half `vocabulary.py` is blind to. `give rise to`,
`account for`, `in light of`, `bring about`: every word in them is NGSL rank
one hundred, so no frequency filter will ever see them, and they are what
actually stops a reader who knows every word separately. Each is its own
entry with its own span, so `rise` and `give rise to` stand side by side and
a tap on `rise` can offer both.

## The third question: common words meaning something else

`bank` is NGSL rank 627 and `spring` is 1332, so the frequency filter drops
both -- correctly, by its own rule, and wrongly for this passage, where one
is the side of a river and the other is a coil. These are not rare words
being met for the first time; they are FAMILIAR words doing something a
reader does not expect, which is a different and nastier problem: nothing
signals that there is anything to look up.

No frequency list can find them, because frequency is exactly what makes
them invisible. Only something that has read the passage can say that this
`bank` is not the one the reader knows. So it is asked, in the same shape as
the phrases: one question over the whole text, a small number of answers,
each located in the text rather than placed by offset.

Those entries are marked `unusual`, and that mark is the whole point. It is
the one thing neither measure can report on its own -- the frequency says
easy, the CEFR says C1, and the disagreement between them is the finding.
"Six words in this passage are used in a sense you would not expect" is
something a candidate can act on.

## What is NOT asked for

**The example sentence.** It is cut out of the passage here, by
:func:`sentence_at`, because the passage is on disk and exact. Asking the
model to copy a sentence back costs thirty output tokens an entry -- a third
of this stage's bill -- to get a copy that may differ from the original by a
comma, and the one thing an example sentence must be is the sentence that is
actually there.

**The offsets.** A model asked for character positions produces plausible
numbers, and plausible numbers are the worst possible failure here: a
highlight two words off looks like a bug in the highlighting. Single words
already have exact offsets from the deterministic scan. Phrases are LOCATED
-- the model returns the string as it stands in the text and
:func:`locate` finds it, and a phrase that cannot be found is dropped rather
than placed approximately.

## Cost

Measured on Cambridge 11 Test 1 Passage 1 -- 84 candidates, four requests,
5 800 tokens in and 7 600 out -- **$0.0062**. The whole reading corpus is
about **$1.20**, paid once. The estimate made before running it said two
cents a passage, so the seed pipeline's oldest lesson holds again: the only
honest number is the one in `work/usage.jsonl`, which `spend.py` adds up.
"""

import argparse
import datetime
import json
import pathlib
import re
import sqlite3
import sys

import vision
import vocabulary

SEED = pathlib.Path(__file__).resolve().parent
WORK = SEED / "work"

#: The three CEFR levels this is allowed to answer. Below B1 a word would not
#: have survived the frequency filter, and C2 is a judgement no two sources
#: agree on -- a scale with a disputed top band is a scale that reads as
#: noise at the top. Anything else the model says is refused rather than
#: rounded, because a level nobody asked for is a level nobody can trust.
LEVELS = ("B1", "B2", "C1")

#: Parts of speech, in the abbreviations a learner's dictionary prints.
#: Closed, because "transitive verb" and "v." and "verb (used with object)"
#: are three spellings of one fact and a panel cannot lay out all three.
PARTS = ("n", "v", "adj", "adv", "prep", "conj", "phr")

#: How long a one-line meaning may be. The panel shows it in a 320px column
#: at 12px; past this it wraps to four lines and stops being a glance.
MEANING = 120

#: A phrase is between two and five words. One word is not a phrase, and past
#: five the model has started quoting the passage back rather than naming an
#: expression in it.
PHRASE_WORDS = (2, 5)

#: How many common-word-unusual-sense entries a passage may have. Small on
#: purpose: a model asked for twenty will find twenty, and the twentieth will
#: be an ordinary word used ordinarily. The finding is only worth anything
#: while it is rare.
SENSES = 6

#: How many words one request may cover. See the module docstring: eighty-five
#: is more than the model will finish, and the reply arrives cut off mid-string
#: rather than short and well-formed. Thirty leaves room to spare under any
#: provider's output ceiling.
BATCH = 30

#: How many candidates may go unglossed before the stage asks again for the
#: ones it missed. Even inside a batch a model occasionally skips one, and a
#: second pass over the handful it skipped is cheap; a second pass over a
#: whole batch to recover one word is not.
MISSING_TOLERANCE = 3

PASSAGE = """You are preparing vocabulary help for an IELTS Reading passage.
The learners are Uzbek speakers at IELTS band 5 to 6.

Here is the passage. Paragraphs are numbered for reference only.

{passage}
"""

WORDS_PROMPT = PASSAGE + """
For each word in the list below, write ONE entry. The list is given as
`id | word as it appears in the passage`. Use the id EXACTLY as given so the
entries can be matched back.

{candidates}

Each entry:
- "id": the id, copied exactly
- "lemma": the dictionary form of the word (undertaken -> undertake,
  phenomena -> phenomenon)
- "pos": one of {parts}
- "meaning_en": what the word means IN THIS PASSAGE. One short line, under
  {meaning} characters, in simpler English than the word itself. Not a
  dictionary entry with several senses -- the one sense used here. If the
  passage uses a common word in an unusual sense, that unusual sense is the
  one to give.
- "meaning_uz": the Uzbek for that same sense. Natural Uzbek, latin script.
  Not a transliteration of the English word.
- "cefr": one of {levels}, for the word in THIS sense. A common word used in
  an unusual sense is harder than the same word used ordinarily.

Answer for every word in the list and for no other word.

Reply with JSON only, and nothing else:

{{"words": [{{"id": "...", "lemma": "...", "pos": "...", "meaning_en": "...",
"meaning_uz": "...", "cefr": "..."}}]}}
"""

PHRASES_PROMPT = PASSAGE + """
Find the multi-word expressions in the passage that a band 5-6 reader would
not understand from the separate words: phrasal verbs and fixed academic
expressions such as "give rise to", "account for", "in light of", "bring
about", "in the wake of", "at the expense of".

Only expressions that are actually in the passage. Between {low} and {high}
words each. At most {most} of them -- the strongest ones. If the passage has
none, return an empty list.

Each entry:
- "surface": the expression EXACTLY as it is written in the passage,
  character for character, including its inflection ("gives rise to" if that
  is what is written). It must be findable in the text above by exact search.
- "lemma": its dictionary form ("give rise to")
- "meaning_en": what it means here. One short line, under {meaning}
  characters, in simpler English.
- "meaning_uz": the Uzbek for that same sense. Natural Uzbek, latin script.
- "cefr": one of {levels}

Reply with JSON only, and nothing else:

{{"phrases": [{{"surface": "...", "lemma": "...", "meaning_en": "...",
"meaning_uz": "...", "cefr": "..."}}]}}
"""

SENSES_PROMPT = PASSAGE + """
Find the COMMON words in this passage that are used in a sense a band 5-6
reader would not expect.

Not rare words -- those are handled elsewhere. Everyday words carrying an
unfamiliar meaning here: "bank" as the side of a river, "spring" as a coil
or a source of water, "figure" as a person of importance, "address" as
"deal with", "subject" as "make undergo", "sound" as a body of water.

This is the hardest kind of word to spot, because nothing about it looks
difficult. Only include a word where the passage's sense is genuinely not
the first one a learner would think of. At most {most}, and fewer is
better -- an ordinary word used ordinarily on this list makes the whole
list useless.

Each entry:
- "surface": the word EXACTLY as written in the passage, findable by exact
  search in the text above
- "lemma": its dictionary form
- "pos": one of {parts}
- "meaning_en": the sense it has HERE. One short line, under {meaning}
  characters
- "meaning_uz": the same sense in natural Uzbek, latin script
- "cefr": one of {levels}, for this sense -- which is harder than the
  everyday sense of the same word

Reply with JSON only, and nothing else:

{{"senses": [{{"surface": "...", "lemma": "...", "pos": "...",
"meaning_en": "...", "meaning_uz": "...", "cefr": "..."}}]}}
"""

#: Where one sentence ends and the next begins: a full stop, question mark or
#: exclamation, any closing quotes or brackets after it, then a space.
#:
#: It gets `Dr. Ito` and `e.g.` wrong, and that is the right trade. A split
#: too early gives an example sentence that is a fragment; no splitting at
#: all gives an example that is a paragraph. The first is occasionally ugly,
#: the second is always useless.
SENTENCE = re.compile(r"(?<=[.!?][\"'’”)\]])\s+|(?<=[.!?])\s+")


def sentence_at(text: str, start: int, end: int) -> str:
    """The sentence containing this span, cut from the passage itself.

    Not asked of the model, and not stored as a copy the model made: this is
    the passage's own words, which is the whole claim the example makes.
    """
    edges = [0]
    for split in SENTENCE.finditer(text):
        edges.append(split.end())
    edges.append(len(text))
    for left, right in zip(edges, edges[1:]):
        if left <= start < right:
            return text[left:max(right, end)].strip()
    return text[start:end]


def locate(paragraphs: list[dict], surface: str) -> tuple[int, int, int] | None:
    """Where a phrase stands: paragraph index and the two offsets, or nothing.

    Exact first, then case-insensitively, and never anything cleverer. A
    fuzzy match here would place a highlight over words the model did not
    mean, and an entry with no place is better than an entry in the wrong
    place -- one is missing help, the other is a bug the reader can see.
    """
    needle = surface.strip()
    if not needle:
        return None
    for matcher in (str.find, lambda hay, pin: hay.lower().find(pin.lower())):
        for index, paragraph in enumerate(paragraphs):
            text = paragraph.get("text") or ""
            at = matcher(text, needle)
            if at >= 0:
                return index, at, at + len(needle)
    return None


def one_line(value: object, limit: int) -> str:
    """A field the model wrote, flattened and trimmed, or empty."""
    text = " ".join(str(value or "").split())
    return text if 0 < len(text) <= limit else ""


def numbered(passage: dict) -> str:
    """The passage as the model sees it: paragraphs with their index.

    The indices are for the model's own reference while it reads -- nothing
    is joined on them. Where an entry lands comes from the scan for words and
    from :func:`locate` for phrases, both of which work on the text itself.
    """
    return "\n\n".join(f"[{index}] {paragraph.get('text') or ''}"
                       for index, paragraph in enumerate(passage["paragraphs"]))


def ask_words(passage: dict, batch: list[dict], *, model: str) -> dict:
    """One batch of candidates, glossed. Returns the raw reply."""
    prompt = WORDS_PROMPT.format(
        passage=numbered(passage),
        candidates="\n".join(f"{entry['lemma']} | {entry['surface']}"
                             for entry in batch),
        parts=", ".join(PARTS), levels=", ".join(LEVELS), meaning=MEANING)
    # Room for every entry in the batch and half as much again. A reply cut
    # off by the ceiling does not parse, and `ask_json` then spends two more
    # requests failing in exactly the same place -- which is how a batch of
    # thirty still managed to die at 8 581 characters: the model pretty-
    # printed six lines an entry where the estimate allowed for two.
    return vision.ask_json(prompt, [], model=model,
                           max_tokens=600 + 150 * len(batch)) or {}


def ask_phrases(passage: dict, *, model: str, most: int) -> dict:
    prompt = PHRASES_PROMPT.format(
        passage=numbered(passage), levels=", ".join(LEVELS), meaning=MEANING,
        low=PHRASE_WORDS[0], high=PHRASE_WORDS[1], most=most)
    return vision.ask_json(prompt, [], model=model,
                           max_tokens=600 + 150 * most) or {}


def ask_senses(passage: dict, *, model: str, most: int) -> dict:
    prompt = SENSES_PROMPT.format(
        passage=numbered(passage), parts=", ".join(PARTS),
        levels=", ".join(LEVELS), meaning=MEANING, most=most)
    return vision.ask_json(prompt, [], model=model,
                           max_tokens=600 + 150 * most) or {}


def glossed(reply: dict, candidates: list[dict], passage: dict) -> list[dict]:
    """The model's word entries, checked and joined back to their places.

    Joined on the id this stage gave out -- the deterministic lemma -- and
    not on anything the model wrote. The model's own `lemma` is KEPT, because
    it is the better one: the rule-based stripper in `vocabulary.py` leaves
    `sacrificed` alone when neither list has heard of `sacrifice`, and the
    model does not.
    """
    places = {entry["lemma"]: entry for entry in candidates}
    entries = []
    for said in reply.get("words") or []:
        where = places.get(str(said.get("id") or "").strip().lower())
        if where is None:
            continue
        entry = judged(said, where["frequency_band"])
        if entry is None:
            continue
        text = passage["paragraphs"][where["index"]].get("text") or ""
        entries.append({
            **entry,
            "surface": where["surface"],
            "index": where["index"],
            "start": where["start"],
            "end": where["end"],
            "example": sentence_at(text, where["start"], where["end"]),
            "is_phrase": False,
        })
    return entries


def phrased(reply: dict, passage: dict) -> list[dict]:
    """The model's phrases, each one found in the passage or dropped."""
    entries = []
    for said in reply.get("phrases") or []:
        surface = " ".join(str(said.get("surface") or "").split())
        words = len(surface.split())
        if not (PHRASE_WORDS[0] <= words <= PHRASE_WORDS[1]):
            continue
        found = locate(passage["paragraphs"], surface)
        if found is None:
            print(f"    phrase not in the passage, dropped: {surface!r}",
                  file=sys.stderr)
            continue
        index, start, end = found
        entry = judged(said, band_of(surface))
        if entry is None:
            continue
        text = passage["paragraphs"][index].get("text") or ""
        entries.append({
            **entry,
            "pos": "phr",
            "surface": text[start:end],
            "index": index,
            "start": start,
            "end": end,
            "example": sentence_at(text, start, end),
            "is_phrase": True,
        })
    return entries


def sensed(reply: dict, passage: dict, taken: set) -> list[dict]:
    """The common words the model says are doing something unexpected here.

    Located in the text like a phrase, and refused where the span is already
    somebody else's: a word the frequency filter already offered is by
    definition not a common word, and one inside a phrase's span is the
    phrase's business.

    Refused too where the word is genuinely rare -- if the frequency lists
    have never heard of it, it is not a COMMON word used unusually, it is
    just a hard word, and the candidate filter would have caught it. The
    finding this list exists for is the disagreement between the two
    measures, and an off-list word is not a disagreement.
    """
    entries = []
    for said in reply.get("senses") or []:
        surface = " ".join(str(said.get("surface") or "").split())
        if not surface or " " in surface:
            continue
        found = locate(passage["paragraphs"], surface)
        if found is None:
            print(f"    sense not in the passage, dropped: {surface!r}",
                  file=sys.stderr)
            continue
        index, start, end = found
        if (index, start) in taken:
            continue
        band = vocabulary.band(vocabulary.lemma_for(surface))
        if band in ("wider", "academic", "off-list"):
            continue
        entry = judged(said, band)
        if entry is None:
            continue
        text = passage["paragraphs"][index].get("text") or ""
        entries.append({
            **entry,
            "surface": text[start:end],
            "index": index,
            "start": start,
            "end": end,
            "example": sentence_at(text, start, end),
            "is_phrase": False,
            # The mark that makes this entry mean something. Frequency says
            # easy, the model says C1, and neither figure on its own can
            # report the disagreement.
            "unusual": True,
        })
    return entries


def band_of(surface: str) -> str:
    """A phrase's frequency band: the rarest of the words in it.

    A phrase has no frequency of its own -- no list counts them -- and the
    honest answer is the one thing that IS measured about it. Usually that is
    `core`, which is the point being made: `give rise to` is three of the
    commonest words in English and is nonetheless opaque. The band is for
    arithmetic over passages, and `core` is arithmetically true here.
    """
    bands = [vocabulary.band(vocabulary.lemma_for(word))
             for word in surface.split() if word]
    return max(bands, key=vocabulary.BANDS.index) if bands else "off-list"


def judged(said: dict, frequency_band: str) -> dict | None:
    """The fields every entry shares, or nothing where one of them is unusable.

    Refused rather than repaired. A missing Uzbek translation is the entry's
    reason for existing; a CEFR level outside the scale is a guess about what
    the model meant; a meaning that runs to a paragraph is a meaning nobody
    reads mid-paper. Dropping one entry of eighty-five costs the reader one
    word. Keeping a bad one costs them their trust in all of them.
    """
    level = str(said.get("cefr") or "").strip().upper()
    part = str(said.get("pos") or "").strip().lower().rstrip(".")
    meaning_en = one_line(said.get("meaning_en"), MEANING)
    meaning_uz = one_line(said.get("meaning_uz"), MEANING)
    lemma = one_line(said.get("lemma"), 60).lower()
    if not (lemma and meaning_en and meaning_uz):
        return None
    if level not in LEVELS:
        return None
    return {
        "lemma": lemma,
        "pos": part if part in PARTS else "",
        "meaning_en": meaning_en,
        "meaning_uz": meaning_uz,
        "cefr_level": level,
        "frequency_band": frequency_band,
    }


def read(passage_id: str, *, model: str, most: int,
         senses: int = SENSES) -> dict | None:
    path = WORK / passage_id / "passage.json"
    if not path.exists():
        print(f"{passage_id:16} no passage.json", file=sys.stderr)
        return None
    passage = json.loads(path.read_text())
    candidates = vocabulary.candidates(passage["paragraphs"])
    if not candidates:
        print(f"{passage_id:16} nothing worth glossing", file=sys.stderr)
        return None

    entries: list[dict] = []
    for start in range(0, len(candidates), BATCH):
        batch = candidates[start:start + BATCH]
        entries += glossed(ask_words(passage, batch, model=model),
                           batch, passage)

    # Even a batch this size comes back one or two short sometimes -- not
    # refused, not malformed, just skipped. Asked again, narrowly, for
    # exactly what is missing: the same medicine every other stage in this
    # pipeline takes when a reply covers less than the page did.
    #
    # By POSITION, not by lemma: the model's lemma is allowed to differ from
    # the one this stage sent out, and comparing the two would report every
    # correction (`sacrificed` -> `sacrifice`) as a word it had missed.
    answered = {(entry["index"], entry["start"]) for entry in entries}
    missing = [entry for entry in candidates
               if (entry["index"], entry["start"]) not in answered]
    if len(missing) > MISSING_TOLERANCE:
        print(f"    {len(missing)} of {len(candidates)} unanswered; asking again",
              file=sys.stderr)
        for start in range(0, len(missing), BATCH):
            batch = missing[start:start + BATCH]
            entries += glossed(ask_words(passage, batch, model=model),
                               batch, passage)

    if most:
        entries += phrased(ask_phrases(passage, model=model, most=most),
                           passage)
    if senses:
        taken = {(entry["index"], entry["start"]) for entry in entries}
        entries += sensed(ask_senses(passage, model=model, most=senses),
                          passage, taken)
    entries.sort(key=lambda entry: (entry["index"], entry["start"]))
    return {
        "passage": passage_id,
        "model": model,
        "at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        # Kept beside the entries because it is the input to a different
        # question -- how hard this passage is -- and because recomputing it
        # later would mean re-running the tokeniser over a passage that may
        # by then have been edited.
        "profile": vocabulary.profile(passage["paragraphs"]),
        "candidates": len(candidates),
        "entries": entries,
    }


def already_sensed(path: pathlib.Path) -> bool:
    return any(entry.get("unusual")
               for entry in json.loads(path.read_text()).get("entries", []))


def add_senses(passage_id: str, *, model: str, most: int) -> dict | None:
    """One extra question over a passage already glossed, folded back in.

    Here because the third question was written after the corpus had been
    read, and re-glossing two hundred passages to add six words each would
    cost the whole extraction again for a twentieth of its output. One
    request a passage, about a tenth of a cent.
    """
    path = WORK / passage_id / "vocabulary.json"
    passage_path = WORK / passage_id / "passage.json"
    if not path.exists() or not passage_path.exists():
        return None
    result = json.loads(path.read_text())
    passage = json.loads(passage_path.read_text())
    entries = [entry for entry in result.get("entries", [])
               if not entry.get("unusual")]
    taken = {(entry["index"], entry["start"]) for entry in entries}
    entries += sensed(ask_senses(passage, model=model, most=most),
                      passage, taken)
    entries.sort(key=lambda entry: (entry["index"], entry["start"]))
    result["entries"] = entries
    return result


def passages(conn: sqlite3.Connection, where: str, args: tuple) -> list[str]:
    return [row[0] for row in conn.execute(
        f"select id from passage where {where} "
        "order by book_number, test_no, passage_no", args)]


def report(ids: list[str]) -> None:
    done = words = phrases = 0
    for passage_id in ids:
        path = WORK / passage_id / "vocabulary.json"
        if not path.exists():
            continue
        done += 1
        for entry in json.loads(path.read_text()).get("entries", []):
            if entry.get("is_phrase"):
                phrases += 1
            else:
                words += 1
    print(f"{done}/{len(ids)} passages glossed | {words} words"
          f" | {phrases} phrases"
          + (f" | {words / done:.0f} words each" if done else ""))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("passage_id", nargs="?", help="one passage, like cam11-t1-p1")
    ap.add_argument("--book", type=int, help="every passage of one book")
    ap.add_argument("--report", action="store_true",
                    help="what is glossed, then stop")
    ap.add_argument("--force", action="store_true",
                    help="gloss again a passage already done")
    ap.add_argument("--phrases", type=int, default=8,
                    help="at most this many multi-word expressions")
    ap.add_argument("--senses", type=int, default=SENSES,
                    help="at most this many common words used unusually")
    ap.add_argument("--senses-only", action="store_true",
                    help="add the unusual senses to passages already glossed, "
                         "without asking about anything else again")
    ap.add_argument("--model", default=vision.DEFAULT_MODEL)
    args = ap.parse_args()

    conn = sqlite3.connect(SEED / "catalogue.db")
    if args.passage_id:
        ids = passages(conn, "id = ?", (args.passage_id,))
    elif args.book:
        ids = passages(conn, "book_number = ?", (args.book,))
    else:
        ids = passages(conn, "1=1", ())

    if args.report:
        report(ids)
        return 0

    done = skipped = failed = 0
    for passage_id in ids:
        out = WORK / passage_id / "vocabulary.json"
        if args.senses_only:
            # The opposite test: this arm has nothing to do for a passage
            # that was never glossed, and everything to do for one that was.
            if not out.exists() or (already_sensed(out) and not args.force):
                skipped += 1
                continue
        elif out.exists() and not args.force:
            skipped += 1
            continue
        # `vision.ask_json` gives up by raising SystemExit, which is right
        # for a script asking one question and wrong for a loop over two
        # hundred passages: one page the model will not answer cleanly used
        # to take the other hundred and sixty down with it. Caught here so
        # the run carries on and says at the end what it could not do.
        try:
            result = (add_senses(passage_id, model=args.model,
                                 most=args.senses)
                      if args.senses_only
                      else read(passage_id, model=args.model,
                                most=args.phrases, senses=args.senses))
        except SystemExit as stopped:
            print(f"{passage_id:16} FAILED  {stopped}", file=sys.stderr)
            failed += 1
            continue
        if result is None or not result["entries"]:
            failed += 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        kinds = sum(1 for entry in result["entries"] if entry["is_phrase"])
        print(f"{passage_id:16} {len(result['entries']) - kinds} words,"
              f" {kinds} phrases, of {result['candidates']} candidates")
        done += 1

    print(f"\n{done} glossed, {skipped} left alone, {failed} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
