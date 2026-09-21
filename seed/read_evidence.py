"""Find, for every reading question, where in the passage its answer is.

    seed/.venv/bin/python seed/read_evidence.py cam11-t1-p1
    seed/.venv/bin/python seed/read_evidence.py --book 11
    seed/.venv/bin/python seed/read_evidence.py --report

A listening question has carried `replay_start_ms`/`replay_end_ms` since the
first day, and on the review screen that one field turned out to be worth
more than the score printed above it: knowing you were wrong teaches nobody
anything, and being put back in front of the sentence you misread is the
whole of what a review is for.

Reading had no counterpart. Its review found a line by searching the passage
for the answer string, which works for a gap-fill -- the answer is literally
in the text -- and says nothing at all about a TRUE / FALSE / NOT GIVEN item
or a multiple choice, where the answer is a letter and the reasoning is three
clauses the candidate did not weigh. Those are exactly the questions somebody
most needs explained, and they were the ones the page had least to say about.

## The model is asked for QUOTES, never for offsets

The same rule `read_vocabulary.py` arrived at, for the same reason. A model
asked for character positions produces plausible numbers, and plausible
numbers are the worst possible failure here: a highlight two words off does
not read as an approximation, it reads as a broken program -- and a candidate
who thinks the highlighting is broken has been given a reason to distrust
every other mark on the page.

So the model returns the sentence AS IT STANDS in the passage, `locate` finds
it by exact search, and a quote that cannot be found is dropped. The offsets
are therefore never anything but a real substring's real position. That is
also the verification: there is no separate checking pass to write, because a
span that did not come back out of the text was never made.

## What is known without asking

Two of the tasks answer this question themselves and are done arithmetically:

* **matching headings** -- the question IS a paragraph ("Paragraph C"), so
  the evidence is that paragraph;
* **matching information** -- the ANSWER is a paragraph letter, so likewise.

They are still put to the model, because "which paragraph contains the
following information" is answered by one sentence inside a paragraph of
ninety words, and a highlight over all ninety says "it is somewhere in here",
which the question already said. What the known paragraph buys is better than
a saved request: the model's quote is REFUSED unless it falls inside it, and
the paragraph stands as the fallback where it does not. A free check on a
quarter of the corpus.

## How wide a span may be

One sentence, or a clause of one. Not a paragraph: pointing at ninety words
is not pointing. `LONGEST` refuses a quote that has started copying the
passage back, and `SHORTEST` refuses a two-word fragment, which is a highlight
the reader cannot read a reason out of.

Up to `MOST` spans a question, because the evidence really is scattered
sometimes -- a NOT GIVEN is often decided by a clause in one sentence and a
clause in another, and marking one of them marks half of why they were wrong.

## Cost

One request a passage, 14 questions together, about 1 500 tokens in and 900
out -- roughly the price of one `read_vocabulary` batch, and there are four
of those per passage. The whole reading corpus is well under a dollar. As
ever the only honest number is `work/usage.jsonl`, which `spend.py` adds up.
"""

import argparse
import datetime
import json
import pathlib
import re
import sqlite3
import sys

import vision

SEED = pathlib.Path(__file__).resolve().parent
WORK = SEED / "work"

#: How many questions may go in one request. A reading passage is thirteen or
#: fourteen, so this is "the whole passage" with a ceiling on the day one
#: turns out not to be -- and the ceiling matters for the reason the
#: vocabulary stage discovered: a reply past the model's output limit does not
#: arrive short and well-formed, it stops mid-string and does not parse.
BATCH = 14

#: The most spans one question may have. Three is already generous -- a fourth
#: is a model that has stopped answering the question and started summarising
#: the paragraph.
MOST = 3

#: How long a quote may be, in characters. About two sentences. Past this the
#: model has begun handing the passage back, and a mark over a third of a
#: paragraph tells the reader nothing they did not already know.
LONGEST = 320

#: And how short. A three-word fragment highlighted in a passage is a puzzle,
#: not evidence: there is no reasoning visible in it.
SHORTEST = 12

#: Which tasks know their own paragraph, and how they know it. See the module
#: docstring -- these are checked rather than trusted, and stand as the
#: fallback where the model's quote does not land inside them.
BY_PROMPT = "matching_headings"      # the QUESTION names the paragraph
BY_ANSWER = "matching_information"   # the ANSWER is the paragraph

#: "Paragraph C", as a matching-headings question writes itself.
NAMES_PARAGRAPH = re.compile(r"^\s*paragraph\s+([A-Z])\b", re.I)

#: A gap in a completion template: `{{3}}`.
GAP = re.compile(r"\{\{\s*(\d+)\s*\}\}")

#: How many of a multiple choice's wrong options may be placed. Three, which
#: is every option of a four-way choice bar the right one. Asked about in the
#: same request as everything else, because the passage is already in front
#: of the model and sending it twice is paying twice for the same reading.
DISTRACTORS = 3

PROMPT = """You are preparing review feedback for an IELTS Reading passage.
A candidate has answered these questions and is about to be shown which ones
they got wrong. For each question, show them WHERE IN THE PASSAGE the answer
is decided.

Here is the passage. Paragraphs are numbered for reference; where the book
letters a paragraph, the letter is given too.

{passage}

Here are the questions, with the correct answer to each. The format is
`id | question | correct answer`.

{questions}

For each question, quote the words in the passage that DECIDE that answer --
the evidence a teacher would underline when explaining it.

- Quote the text EXACTLY as it stands in the passage, character for
  character. It must be findable there by exact search. Do not correct,
  shorten with "...", paraphrase, or join two separate places into one quote.
- One sentence, or the part of a sentence that carries the point. Never a
  whole paragraph: a mark over ninety words says "it is somewhere in here",
  which the question already said. Between {shortest} and {longest}
  characters.
- Where the answer genuinely turns on two separate places, give both as two
  quotes. At most {most}.
- For a TRUE / FALSE / NOT GIVEN or YES / NO / NOT GIVEN question answered
  NOT GIVEN, quote the place that comes CLOSEST to the claim -- the sentence
  the candidate probably read and over-read. If the passage truly says
  nothing on the subject, give an empty list for that question.
- If you cannot find the evidence for a question, give an empty list for it.
  An empty list is a good answer; an invented quote is not.

Some questions are marked `[multiple choice]` and list their options. For
those, ALSO say where each WRONG option came from — the words in the passage
that a candidate choosing it would have been misled by. Same rules: quoted
exactly, findable by search, one sentence or less.

**Most wrong options have no source at all.** A distractor is usually
invented, or states the opposite of the passage, or is about something the
passage never mentions. Give it an empty list. Only quote where the passage
really does say something a reader could have taken for that option — a
mark over a sentence nobody was misled by teaches the reader the opposite of
what it is for.

Reply with JSON only, and nothing else:

{{"evidence": [{{"id": "...", "quotes": ["...", "..."],
"options": {{"A": ["..."], "B": [], "C": ["..."]}}}}]}}

`options` only for the questions marked `[multiple choice]`, and only for
their WRONG options — never for the correct one, which `quotes` already
answers.
"""


def numbered(passage: dict) -> str:
    """The passage as the model reads it: every paragraph with its index, and
    its letter where the book prints one.

    The letters are given because two of the tasks are answered by naming
    one, and a model asked to find the evidence for "which paragraph contains
    a mention of X" is doing the question's own work without them. Nothing is
    joined on either number -- where a quote lands comes from searching the
    text for it.
    """
    out = []
    for index, paragraph in enumerate(passage["paragraphs"]):
        label = (paragraph.get("label") or "").strip()
        head = f"[{index}{f' / Paragraph {label}' if label else ''}]"
        out.append(f"{head} {paragraph.get('text') or ''}")
    return "\n\n".join(out)


def line_for(template: str, number: int) -> str:
    """The line of a completion template that holds gap `number`.

    A gap-fill question has no prompt of its own -- what asks it is one line
    of the group's document -- and the model cannot find the evidence for
    "question 5" without being told what question 5 says. The gap is written
    back as `___`, which is how the review prints it too.
    """
    for line in template.splitlines():
        if any(int(found) == number for found in GAP.findall(line)):
            return GAP.sub("___", line).strip()
    return GAP.sub("___", template).strip()


def asked(group: dict, question: dict) -> str:
    """What this question says, whatever kind it is.

    Four shapes: a question with its own prompt (multiple choice, matching, a
    true/false statement), a gap in a template, and -- for multiple choice --
    the options, because the evidence for "B" is the evidence for what B
    SAYS, and a model shown only the stem is being asked to find the answer
    rather than to find where it is written.

    A multiple choice says so, because it is the one type this stage asks a
    second question about: where the options it did NOT answer came from.
    """
    prompt = " ".join(str(question.get("prompt") or "").split())
    if not prompt:
        template = (group.get("config") or {}).get("template") or ""
        prompt = line_for(template, question["number"]) if template else ""
    options = question.get("options") or (group.get("config") or {}).get("options")
    if options and group["type"] == "multiple_choice":
        letters = [f"{chr(97 + i).upper()}. {text}" for i, text in enumerate(options)]
        prompt = "[multiple choice] " + f"{prompt} / " + " / ".join(letters)
    return prompt or "(no text)"


def wrong_options(group: dict, question: dict) -> list[str]:
    """The option letters this question is NOT answered by, upper-cased.

    Empty for everything but a multiple choice: a matching item's options are
    the group's box, and where each of THOSE came from is the evidence of the
    item it actually answers -- arithmetic the app does for itself, with no
    request and no column. See ``app.services.grading._distractor``.
    """
    if group["type"] != "multiple_choice":
        return []
    options = question.get("options") or []
    right = {str(one).strip().lower() for one in question.get("correct_answers") or []}
    return [
        chr(97 + index).upper()
        for index in range(len(options))
        if chr(97 + index) not in right
    ][:DISTRACTORS]


def answer_of(group: dict, question: dict) -> str:
    """The correct answer, said the way the paper says it.

    `key` is what the book's answer key prints -- "(stacked) trays", "iv",
    "NOT GIVEN" -- and `correct_answers` is what the grader matches against.
    The key is the better thing to show a model: it is the answer as a human
    wrote it, and the grader's variants are an implementation detail that
    reads as a list of near-synonyms.
    """
    key = " ".join(str(question.get("key") or "").split())
    if key:
        return key
    return " / ".join(question.get("correct_answers") or []) or "(unknown)"


def paragraph_known(group: dict, question: dict,
                    letters: dict[str, int]) -> int | None:
    """Which paragraph this question is about, where that is arithmetic.

    See the module docstring. Returns an index into `paragraphs`, or None for
    every other task -- which is most of them.
    """
    if group["type"] == BY_PROMPT:
        found = NAMES_PARAGRAPH.match(str(question.get("prompt") or ""))
        return letters.get(found.group(1).upper()) if found else None
    if group["type"] == BY_ANSWER:
        key = " ".join(str(question.get("key") or "").split()).upper()
        return letters.get(key) if len(key) == 1 else None
    return None


def locate(paragraphs: list[dict], quote: str,
           within: int | None) -> dict | None:
    """Where a quote stands: a paragraph index and two offsets, or nothing.

    Exact first, then case-insensitively, and never anything cleverer --
    `read_vocabulary.locate`'s rule, and it holds harder here. A fuzzy match
    would put a red mark over words the model did not mean, under the heading
    "this is where the answer was", which is a review teaching somebody they
    misread a sentence they never read.

    `within` narrows the search to the one paragraph the task itself names.
    A quote that will not be found there is refused rather than looked for
    elsewhere: the paragraph is known from the answer key, so a quote outside
    it is the model being wrong, not the key.
    """
    needle = " ".join(quote.split())
    if not SHORTEST <= len(needle) <= LONGEST:
        return None
    where = ([within] if within is not None
             else range(len(paragraphs)))
    for matcher in (str.find, lambda hay, pin: hay.lower().find(pin.lower())):
        for index in where:
            text = paragraphs[index].get("text") or ""
            at = matcher(text, needle)
            if at >= 0:
                return {"index": index, "start": at, "end": at + len(needle)}
    return None


def whole(paragraphs: list[dict], index: int) -> dict:
    """The fallback for a task that names its own paragraph: all of it.

    Wider than this stage would ever choose -- see the module docstring on
    span size -- and still the right answer when the alternative is nothing.
    "The answer is in paragraph C" is what the task itself promises the
    candidate; a review that cannot even say that much has lost information
    the answer key was holding all along.
    """
    return {"index": index, "start": 0,
            "end": len(paragraphs[index].get("text") or "")}


def tidy(spans: list[dict]) -> list[dict]:
    """In reading order, without overlaps, at most `MOST`.

    Two quotes that overlap are one place said twice -- the model quoting a
    sentence and then a clause of it -- and drawn as two marks they leave a
    seam down the middle of one highlight. Merged rather than deduplicated,
    because the union is what the model meant both times.
    """
    out: list[dict] = []
    for span in sorted(spans, key=lambda s: (s["index"], s["start"])):
        last = out[-1] if out else None
        if last and last["index"] == span["index"] and span["start"] <= last["end"]:
            last["end"] = max(last["end"], span["end"])
        else:
            out.append(dict(span))
    return out[:MOST]


def ask(passage: dict, batch: list[dict], *, model: str) -> dict:
    prompt = PROMPT.format(
        passage=numbered(passage),
        questions="\n".join(
            f"{one['id']} | {one['asked']} | {one['answer']}" for one in batch),
        shortest=SHORTEST, longest=LONGEST, most=MOST)
    # Room for `MOST` quotes an entry at the length limit, and half as much
    # again. `ask_json`'s retry cannot rescue a reply cut off by the output
    # ceiling -- it asks the same question and dies in the same place.
    # Room for every entry in the batch and half as much again, plus the
    # distractors, which are up to three more quotes on a multiple choice.
    # `ask_json`'s retry cannot rescue a reply cut off by the output ceiling
    # -- it asks the same question and dies in the same place.
    choices = sum(1 for one in batch if one["wrong_options"])
    return vision.ask_json(prompt, [], model=model,
                           max_tokens=400 + 220 * len(batch)
                           + 200 * DISTRACTORS * choices) or {}


def questions_of(payload: dict, passage: dict) -> list[dict]:
    """Every question on this paper, flattened, with what it takes to ask
    about it and what it takes to write the answer back.

    The id put in front of the model is the PRINTED number -- what the paper
    calls the question -- because it is unique across the passage and because
    a model that has to invent a key invents a different one. What comes back
    is joined to `(group, number)`, which is what identifies the row.
    """
    letters = {(one.get("label") or "").strip().upper(): index
               for index, one in enumerate(passage["paragraphs"])
               if (one.get("label") or "").strip()}
    out = []
    for order_index, group in enumerate(payload.get("groups") or []):
        for question in group.get("questions") or []:
            out.append({
                "id": str(question.get("paper_number") or question["number"]),
                "group": order_index,
                "number": question["number"],
                "type": group["type"],
                "asked": asked(group, question),
                "answer": answer_of(group, question),
                "paragraph": paragraph_known(group, question, letters),
                "wrong_options": wrong_options(group, question),
            })
    return out


def read(passage_id: str, *, model: str) -> dict | None:
    work = WORK / passage_id
    passage_path, questions_path = work / "passage.json", work / "questions.json"
    if not passage_path.exists() or not questions_path.exists():
        print(f"{passage_id:16} needs passage.json and questions.json",
              file=sys.stderr)
        return None
    passage = json.loads(passage_path.read_text())
    payload = json.loads(questions_path.read_text())
    paragraphs = passage["paragraphs"]
    questions = questions_of(payload, passage)
    if not questions:
        print(f"{passage_id:16} no questions to place", file=sys.stderr)
        return None

    said: dict[str, list[str]] = {}
    options_said: dict[str, dict[str, list[str]]] = {}
    for start in range(0, len(questions), BATCH):
        batch = questions[start:start + BATCH]
        reply = ask(passage, batch, model=model)
        for answer in reply.get("evidence") or []:
            key = str(answer.get("id") or "").strip()
            quotes = answer.get("quotes")
            if isinstance(quotes, list):
                said[key] = [
                    str(quote) for quote in quotes if str(quote).strip()]
            options = answer.get("options")
            if isinstance(options, dict):
                options_said[key] = {
                    str(letter).strip().lower(): [
                        str(quote) for quote in (given or [])
                        if str(quote).strip()]
                    for letter, given in options.items()
                    if isinstance(given, list)
                }

    entries, dropped, fell_back, placed_options = [], 0, 0, 0
    for question in questions:
        spans = []
        for quote in said.get(question["id"], [])[: MOST * 2]:
            found = locate(paragraphs, quote, question["paragraph"])
            if found is None:
                dropped += 1
                continue
            spans.append(found)
        if not spans and question["paragraph"] is not None:
            # The task named the paragraph and the model did not manage a
            # sentence inside it. What the answer key knows is still true.
            spans = [whole(paragraphs, question["paragraph"])]
            fell_back += 1

        # Where each WRONG option came from, for the one type whose options
        # belong to the question. Located by the same search and dropped by
        # the same rule -- a distractor placed approximately is a red mark
        # over a sentence nobody was misled by, which is worse than none.
        #
        # NOT narrowed to the question's own paragraph: a distractor's whole
        # job is to come from somewhere else in the passage.
        options: dict[str, list[dict]] = {}
        for letter in question["wrong_options"]:
            found = []
            for quote in (options_said.get(question["id"], {})
                          .get(letter.lower()) or [])[:MOST]:
                at = locate(paragraphs, quote, None)
                if at is None:
                    dropped += 1
                    continue
                found.append(at)
            if found:
                options[letter.lower()] = tidy(found)
                placed_options += 1

        if not spans and not options:
            continue
        entry = {
            "group": question["group"],
            "number": question["number"],
            "id": question["id"],
            "spans": tidy(spans),
        }
        if options:
            entry["options"] = options
        entries.append(entry)

    return {
        "passage": passage_id,
        "model": model,
        "at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "questions": len(questions),
        "placed": len(entries),
        # Kept because they are the two numbers that say whether this stage is
        # working, and neither can be recovered from the output: a quote the
        # model invented leaves nothing behind once it has been dropped.
        "dropped_quotes": dropped,
        "fell_back_to_paragraph": fell_back,
        #: How many wrong multiple-choice options were placed. The other
        #: half of what this stage does, and worth counting separately: a
        #: run where it is zero has stopped answering the second question
        #: without failing at the first.
        "placed_options": placed_options,
        "entries": entries,
    }


def passages(conn: sqlite3.Connection, where: str, args: tuple) -> list[str]:
    return [row[0] for row in conn.execute(
        f"select id from passage where {where} "
        "order by book_number, test_no, passage_no", args)]


def report(ids: list[str]) -> None:
    done = placed = asked_for = wide = distractors = 0
    for passage_id in ids:
        path = WORK / passage_id / "evidence.json"
        if not path.exists():
            continue
        result = json.loads(path.read_text())
        done += 1
        placed += result.get("placed", 0)
        asked_for += result.get("questions", 0)
        wide += result.get("fell_back_to_paragraph", 0)
        distractors += result.get("placed_options", 0)
    print(f"{done}/{len(ids)} passages placed | {placed} of {asked_for} questions"
          + (f" ({placed / asked_for:.0%})" if asked_for else "")
          + f" | {distractors} distractors | {wide} whole-paragraph fallbacks")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("passage_id", nargs="?", help="one passage, like cam11-t1-p1")
    ap.add_argument("--book", type=int, help="every passage of one book")
    ap.add_argument("--report", action="store_true",
                    help="what is placed, then stop")
    ap.add_argument("--force", action="store_true",
                    help="place again a passage already done")
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
        out = WORK / passage_id / "evidence.json"
        if out.exists() and not args.force:
            skipped += 1
            continue
        # `vision.ask_json` gives up by raising SystemExit, which is right for
        # a script asking one question and wrong for a loop over two hundred
        # passages -- see the same guard in `read_vocabulary.py`.
        try:
            result = read(passage_id, model=args.model)
        except SystemExit as stopped:
            print(f"{passage_id:16} FAILED  {stopped}", file=sys.stderr)
            failed += 1
            continue
        if result is None or not result["entries"]:
            failed += 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"{passage_id:16} {result['placed']}/{result['questions']} placed,"
              f" {result['placed_options']} distractors,"
              f" {result['dropped_quotes']} quotes dropped,"
              f" {result['fell_back_to_paragraph']} whole paragraphs")
        done += 1

    print(f"\n{done} placed, {skipped} left alone, {failed} failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
