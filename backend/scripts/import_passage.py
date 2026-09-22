"""Write a seeded reading passage into the app database.

    uv run python -m scripts.import_passage cam11-t1-p2 --owner <user-uuid>
    uv run python -m scripts.import_passage --all --owner <uuid> --evidence-only

The reading half of ``import_section``. It writes far less, because a paper
you read has far less: there is no recording, so no blob, no transcript, no
segments and no replay spans -- what is left is a material, one part carrying
the passage, and the questions answered from it.

What it writes, for one passage:

* a ``Material`` of type ``reading`` with no audio asset at all. That column
  is nullable and a reading material is the reason it is: publishing asks for
  a recording only of a paper that is heard
  (``_paper_blockers`` in ``app/services/publishing.py``).
* one ``Part`` whose ``passage`` column holds the text -- title, source line,
  and the paragraphs with the letters the book prints beside them.
* its question groups, through the same ``import_questions`` the listening
  importer uses and therefore through the same schemas. A seed script that
  inserted rows behind those would be the one caller allowed to write a
  material the editor could never have produced.
* where in the passage each answer is found, from ``read_evidence.py``. The
  one thing written outside the authoring schemas, and the docstring on
  ``import_evidence`` says why: it is the only part of a re-import that has
  to reach a material somebody has already sat.

``--evidence-only`` does that last one and nothing else, which is how a stage
that did not exist before goes out across a corpus that is already in use:
evidence changes no score, no text and no answer key, so it is the version of
the change that cannot break anything. See ``place_evidence``.

Private, like every other seeded material, and for the same reason: this is
copyrighted source, and it is in the database to prove the pipeline works.
``publish_seeded.py`` is where that decision is made, once, for everything.
"""

import argparse
import asyncio
import json
import logging
import pathlib
import sqlite3
import sys
import uuid

from sqlmodel import select

from app.core.database import async_session_factory
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_group import FIXED_CHOICE_OPTIONS, QuestionGroup
from app.models.user import User
from app.services import difficulty as difficulty_service
from app.services import vocabulary as vocabulary_service

from scripts.import_section import book_code, import_questions

logger = logging.getLogger("scripts.import_passage")

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
SEED = REPO / "seed"

#: The tasks a paragraph's LETTER is the answer to.
#:
#: A book letters its paragraphs when, and only when, something asks the
#: candidate to name one. So the questions say whether the letters on a
#: passage are the book's -- and four of this corpus's 191 carry letters no
#: question uses, every one of them invented by a reader that was told not
#: to: "The psychology of innovation" came back lettered A to K off a page
#: whose margin is empty.
#:
#: Dropped rather than kept, because a letter nothing is answered with is
#: either decoration or a lie, and there is no way to tell which from here.
#: A passage the book really does letter and never asks about loses nothing
#: a learner can act on.
#: Matching FEATURES is not one of them: its answers are letters from its
#: own box -- "A Dr Helmut Fischer, B Anthony Berwick" -- naming a person or
#: a study rather than a paragraph.
BY_LETTER = {"matching_information", "matching_headings"}

#: The number this passage's first question carries on the whole paper. An
#: Academic Reading paper runs 1 to 40 straight through its three passages,
#: in a shape the exam fixes rather than the book -- so a seeded Passage 2
#: numbered from 1 would print "Question 1" where the answer key says 14.
FIRST_NUMBER = {1: 1, 2: 14, 3: 27}


def read_passage(passage_id: str) -> tuple[dict, dict, str, str]:
    """The catalogue row, the passage text, its reference and its title."""
    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT p.*, b.title AS book_title FROM passage p "
        "JOIN book b ON b.number = p.book_number WHERE p.id = ?",
        (passage_id,)).fetchone()
    conn.close()
    if row is None:
        raise SystemExit(f"{passage_id} is not in the catalogue")

    path = SEED / "work" / passage_id / "passage.json"
    if not path.exists():
        raise SystemExit(
            f"{passage_id}: no passage text. Run seed/read_passages.py first.")
    held = json.loads(path.read_text())
    if not held.get("paragraphs"):
        raise SystemExit(f"{passage_id}: the passage text is empty")

    # Whether anything on this paper is answered by naming a paragraph. See
    # BY_LETTER.
    built = SEED / "work" / passage_id / "questions.json"
    asks_by_letter = False
    if built.exists():
        asks_by_letter = any(
            group.get("type") in BY_LETTER
            for group in json.loads(built.read_text()).get("groups", []))

    # Exactly the shape `Part.passage` documents, and nothing else: the
    # faults the reader recorded are its own bookkeeping and have no business
    # in the app's database.
    passage = {
        "title": held.get("title"),
        "subtitle": held.get("subtitle"),
        "source": held.get("source"),
        "paragraphs": [
            {"label": one.get("label") if asks_by_letter else None,
             "text": one["text"]}
            for one in held["paragraphs"]
        ],
    }
    # "An Introduction to Film Sound — C11 T4 P2".
    #
    # The passage's OWN name first, because that is what a reader picks by
    # and what survives truncation in a list of a hundred and ninety-one.
    # The book and the test after it, short: the book's full name is in the
    # collection, one course per book, and repeating it on every card is
    # thirty-odd characters saying the same thing twelve times over.
    #
    # Where a passage has no title of its own the code stands alone rather
    # than a blank leading a dash. Every passage in this corpus has one --
    # `read_passages.py` goes to the sheet before to find it -- so this is
    # for a book that has not been read yet, not for one of these.
    # Two things, in two columns. The reference says which test in which
    # book; the title is what the book calls the passage. They used to be run
    # together -- "An Introduction to Film Sound — C11 T4 P2" -- and the card
    # printed the pair as one heading, the importers used the pair as a key,
    # and `seed_status` picked the reference back out with a regular
    # expression. See the `b3e91a7c40d2` migration.
    reference = (f"{book_code(row['book_number'])} T{row['test_no']}"
                 f" P{row['passage_no']}")
    # Every passage in this corpus prints a title. A book that did not would
    # leave the reference standing as the name, which is honest: it is the
    # only thing anybody knows to call it.
    title = (passage.get("title") or "").strip() or reference
    return dict(row), passage, reference, title


async def import_vocabulary(session, material_id: uuid.UUID,
                            part_id: uuid.UUID, passage_id: str) -> int:
    """The passage's glossed words, where `read_vocabulary.py` has left any.

    Optional, and silent when there is nothing: `vocab` is an optional stage
    in `run_reading.py` for the reason written there -- a passage with no
    glosses is still a passage worth sitting -- so an import that insisted on
    finding the file would turn a loss of help into a loss of the paper.

    Re-run on every import, like the passage text and the questions. A
    passage re-read is a passage whose offsets have moved, and glosses left
    over from the previous reading would point at the wrong words. What
    survives is anything an author has touched, which the service decides
    from the `source` column rather than this script.
    """
    path = SEED / "work" / passage_id / "vocabulary.json"
    if not path.exists():
        return 0
    read = json.loads(path.read_text())
    written, kept = await vocabulary_service.replace_extracted(
        session, material_id=material_id, part_id=part_id,
        rows=read.get("entries") or [])
    if kept:
        logger.info("kept %d author-edited entries", kept)

    # And the words somebody has already put on their own list. A saved
    # context copies its gloss and is deliberately never refreshed, but a
    # FIELD that did not exist when it was saved is a gap rather than a
    # change -- see `vocabulary.enrich_saved_contexts`, which fills the
    # empty ones and writes over nothing.
    filled = await vocabulary_service.enrich_saved_contexts(
        session, material_id=material_id)
    if filled:
        logger.info("filled the usual meaning on %d saved contexts", filled)

    # How much of the passage is outside the frequency lists. Measured while
    # the text was being read and recoverable from nowhere else -- the lists
    # live in the seed venv, not the backend's -- so this is the one chance
    # to record it. It gives a material nobody has sat a difficulty band
    # instead of "New", until twenty answers replace the guess.
    share = (read.get("profile") or {}).get("off_list_share")
    if share is not None:
        await difficulty_service.set_vocabulary_load(
            session, material_id, float(share))
    return written


async def import_evidence(session, part_id: uuid.UUID, passage_id: str) -> int:
    """Where each answer is found in the passage, from `read_evidence.py`.

    ## Why this is its own pass and not part of the question payload

    Everything else a question has goes in through `QuestionGroupIn`, and
    that rule is worth keeping: a seed script writing rows behind the
    authoring schemas would be the one caller allowed to produce a material
    the editor could never have made. Evidence is the exception, on purpose,
    and for a reason that is about learners rather than about tidiness.

    `import_questions` REFUSES to rewrite the questions of a material anybody
    has already answered -- Postgres will not delete a row
    `question_attempts` points at, and a learner's answer is worth more than
    a re-run's tidiness. A material somebody has sat is exactly the material
    whose review page this feature exists for. Threading evidence through the
    question payload would mean the marking never reached a single paper that
    had been used.

    So it is applied on its own, by matching the group's `order_index` and
    the question's `number` -- and that is safe in a way a re-import of the
    questions is not, because evidence changes no score. It is feedback about
    a paper, not the paper.

    Matched only where the shape still agrees: a group of a different type,
    or with a different number of questions, is a passage that has been read
    again into something else, and a span measured against the old text would
    point at the wrong words. Skipped quietly in that case -- a missing mark
    is missing help, and a mark in the wrong place is a bug the reader can
    see.

    The offsets are checked back against the paragraph they claim to be in.
    `read_evidence.py` has already guaranteed it -- a span there is a real
    substring's real position, because it was found by searching for the text
    -- and this checks again because the passage may have been READ again
    since, and a re-read passage is one whose offsets have moved.
    """
    path = SEED / "work" / passage_id / "evidence.json"
    if not path.exists():
        return 0
    read = json.loads(path.read_text())

    part = await session.get(Part, part_id)
    paragraphs = ((part.passage or {}).get("paragraphs") or []) if part else []

    groups = (await session.exec(
        select(QuestionGroup).where(QuestionGroup.part_id == part_id)
        .order_by(QuestionGroup.order_index))).all()
    by_index = {group.order_index: group for group in groups}

    entries = read.get("entries") or []
    if not entries:
        return 0

    # A re-import REPLACES what the extraction produced, exactly as the
    # passage text and the glosses are replaced. A question the new run did
    # not place is a question whose old spans were measured against a
    # reading of the passage that no longer stands, and leaving them is how
    # a corrected passage silently keeps pointing at the wrong words.
    #
    # Only the groups the file covers, so a part carrying a group the seed
    # knows nothing about is left alone.
    placed = {(entry.get("group"), entry.get("number")) for entry in entries}
    for order_index, group in by_index.items():
        for question in (await session.exec(
                select(Question).where(Question.group_id == group.id))).all():
            if (order_index, question.number) in placed:
                continue
            if question.evidence is not None:
                question.evidence = None
                session.add(question)
            stale = {"option_evidence", "key_words"} & set(question.config or {})
            if stale:
                question.config = {key: value
                                   for key, value in question.config.items()
                                   if key not in stale}
                session.add(question)

    written = 0
    for entry in entries:
        group = by_index.get(entry.get("group"))
        if group is None:
            continue
        question = (await session.exec(
            select(Question).where(Question.group_id == group.id,
                                   Question.number == entry.get("number")))).first()
        if question is None:
            continue
        spans = [span for span in (entry.get("spans") or [])
                 if fits(paragraphs, span)]

        # Where each WRONG option came from, for a multiple choice. Beside
        # the question's own presentation rather than in a column of its
        # own, exactly where ``option_replay`` sits for the listening half
        # of the same idea -- see the Question model.
        #
        # MERGED into the config rather than assigned over it: the questions
        # were written moments ago by ``import_questions`` and carry their
        # prompt and their options in there. A fresh dict, because SQLAlchemy
        # does not watch a JSONB column for mutation in place and a key added
        # to the existing one would never be written.
        options = {
            str(letter).strip().lower(): kept
            for letter, given in (entry.get("options") or {}).items()
            if (kept := [one for one in (given or []) if fits(paragraphs, one)])
        }

        # A NOT GIVEN statement's trap goes in the same place, under every
        # answer that is not the right one.
        #
        # It belongs there because it IS a distractor — the sentence that
        # made somebody answer TRUE — and because both wrong answers are
        # pulled by the same sentence: whether they said TRUE or FALSE, what
        # they read was this. Filing it as evidence instead is what the
        # first run did, and a review then drew it green under "the answer
        # was here", which is the opposite of what NOT GIVEN means.
        near = [one for one in (entry.get("near") or []) if fits(paragraphs, one)]
        if near:
            right = {str(one).strip().lower() for one in question.correct_answers}
            for word in FIXED_CHOICE_OPTIONS.get(group.type, ()):
                if word.strip().lower() not in right:
                    options[word.strip().lower()] = near

        # The word or two the statement turns on, inside the sentence that
        # settles it. Not a span of its own: it is drawn INSIDE the answer's
        # mark, which is the only place it means anything.
        keys = [one for one in (entry.get("keys") or []) if fits(paragraphs, one)]
        # A re-run that placed nothing where it once placed something is a
        # correction, not a gap to preserve — so both keys are written or
        # cleared on every import.
        config = {key: value for key, value in (question.config or {}).items()
                  if key not in ("option_evidence", "key_words")}
        if options:
            config["option_evidence"] = options
        if keys:
            config["key_words"] = keys
        question.config = config

        if not spans and not options:
            continue
        # Set either way: a question the run placed but whose spans all
        # failed the offset check has no evidence any more, and saying so is
        # the point of the sweep above.
        question.evidence = spans or None
        session.add(question)
        written += 1
    return written


def fits(paragraphs: list[dict], span: object) -> bool:
    """Whether a span really lands on text that is there.

    Empty spans are refused as well as out-of-range ones: a zero-width
    highlight draws nothing and reads, to anybody debugging it later, as a
    mark that failed to render rather than as a mark that was never meant.
    """
    if not isinstance(span, dict):
        return False
    try:
        index, start, end = span["index"], span["start"], span["end"]
    except (KeyError, TypeError):
        return False
    if not all(isinstance(n, int) for n in (index, start, end)):
        return False
    if not 0 <= index < len(paragraphs):
        return False
    text = paragraphs[index].get("text") or ""
    return 0 <= start < end <= len(text)


async def place_evidence(passage_id: str, owner_id: uuid.UUID) -> None:
    """Put this passage's evidence on a material that is already imported.

    The whole of ``--evidence-only``, and it exists because rolling a new
    stage out across a corpus that is being USED is a different act from
    importing a passage.

    A full re-import rewrites the passage text, the title, the vocabulary and
    the questions. All of that is correct after a passage has been READ
    again, which is what a re-import normally follows — and all of it is
    beside the point when the only thing that has changed is that a stage
    which did not exist before has now run. Evidence changes no score, no
    text and no answer key: it is a note about where the answer was. It can
    go out on its own, and going out on its own is the version of the change
    that cannot break anything.
    """
    reference = read_passage(passage_id)[2]
    async with async_session_factory() as session:
        material = (await session.exec(
            select(Material).where(Material.author_id == owner_id,
                                   Material.type == "reading",
                                   Material.reference == reference))).first()
        if material is None:
            print(f"{passage_id} -> not imported yet; nothing to place on")
            return
        part = (await session.exec(
            select(Part).where(Part.material_id == material.id)
            .order_by(Part.order_index))).first()
        if part is None:
            print(f"{passage_id} -> material {material.id} has no part")
            return
        marked = await import_evidence(session, part.id, passage_id)
        await session.commit()
    print(f"{passage_id} -> material {material.id} ({marked} placed)")


async def place_vocabulary(passage_id: str, owner_id: uuid.UUID) -> None:
    """Re-import this passage's glossed words, and nothing else.

    ``--vocabulary-only``, and the same argument as ``--evidence-only`` one
    stage over: rolling a new stage out across a corpus that is being USED
    is a different act from importing a passage.

    The second candidate layer (``seed/vocabulary.py``, ``ASK_RANK``) adds
    twenty-odd words to a passage already glossed. Those words change no
    score, no text and no answer key — they are help beside a passage — so
    they can go out on their own, and going out on their own is the version
    of the change that cannot break anything. A full re-import would rewrite
    the questions, which the importer refuses to do to a paper somebody has
    already answered.

    It goes through ``replace_extracted`` like every other import, so an
    author's correction survives and a learner's own review lookup does not:
    see that function on why the second of those is the pipeline's to
    replace.
    """
    reference = read_passage(passage_id)[2]
    async with async_session_factory() as session:
        material = (await session.exec(
            select(Material).where(Material.author_id == owner_id,
                                   Material.type == "reading",
                                   Material.reference == reference))).first()
        if material is None:
            print(f"{passage_id} -> not imported yet; nothing to gloss")
            return
        part = (await session.exec(
            select(Part).where(Part.material_id == material.id)
            .order_by(Part.order_index))).first()
        if part is None:
            print(f"{passage_id} -> material {material.id} has no part")
            return
        glossed = await import_vocabulary(session, material.id, part.id,
                                          passage_id)
        await session.commit()
    print(f"{passage_id} -> material {material.id} ({glossed} glossed)")


async def import_passage(passage_id: str, owner_id: uuid.UUID) -> None:
    row, passage, reference, title = read_passage(passage_id)
    first_number = FIRST_NUMBER[row["passage_no"]]

    async with async_session_factory() as session:
        if await session.get(User, owner_id) is None:
            raise SystemExit(f"no user {owner_id}")

        # Re-running must not leave a second copy behind, and the REFERENCE is
        # what it looks itself up by -- the same bargain import_section makes.
        # It used to be the title, which meant the key was a display string:
        # renaming the corpus had to be done as a migration rather than a
        # re-import, twice, because a re-import would not have recognised its
        # own work.
        # WITH the type. "C10 T1 P1" is Cambridge 10's first test, first
        # paper -- and every test has two of those, a listening Part 1 and a
        # reading Passage 1. The reference names a place in a book; which of
        # the two papers is the material's own type, and looking one up
        # without saying which finds the other one half the time.
        material = (await session.exec(
            select(Material).where(Material.author_id == owner_id,
                                   Material.type == "reading",
                                   Material.reference == reference))).first()
        if material is None:
            material = Material(
                author_id=owner_id, type="reading", title=title,
                reference=reference,
                audio_asset_id=None,
                visibility="private",  # copyrighted source; never public from here
            )
            session.add(material)
            await session.flush()
            part = Part(material_id=material.id, order_index=0,
                        title=f"Reading Passage {row['passage_no']}",
                        passage=passage, first_number=first_number)
            session.add(part)
            await session.flush()
            logger.info("created material %s", material.id)
        else:
            part = (await session.exec(
                select(Part).where(Part.material_id == material.id)
                .order_by(Part.order_index))).first()
            if part is None:
                raise SystemExit(
                    f"{passage_id}: material {material.id} has no part; it was "
                    "not written by this script")
            logger.info("material %s already existed", material.id)

        # Written on EVERY import, not only on creation. A re-import is what
        # happens after the passage was read again -- a transcription that
        # stopped early, a lettering fixed -- and keeping the old text because
        # the material already existed is how a corrected passage silently
        # fails to reach the page. Same rule as the listening importer's
        # transcript.
        # The title too, for the same reason: a passage re-read with its
        # opening recovered is a passage whose printed title has only just
        # been found.
        material.title = title
        session.add(material)

        part.passage = passage
        part.title = f"Reading Passage {row['passage_no']}"
        part.first_number = first_number
        session.add(part)

        glossed = await import_vocabulary(session, material.id, part.id,
                                          passage_id)

        written = await import_questions(session, part.id, passage_id)
        # After the questions, always, and whether or not they were rewritten
        # -- see import_evidence on why this is the one thing that reaches a
        # material somebody has already sat.
        marked = await import_evidence(session, part.id, passage_id)
        if written:
            # Every authoring write bumps the counter the editor checks
            # against.
            material.version += 1
            session.add(material)

        await session.commit()
        material_id = str(material.id)
        # What it IS, not what a fresh one would be. Re-importing does not
        # withdraw a published material -- publishing is publish_seeded's
        # decision and this script does not take it back -- so saying
        # "private" unconditionally was a line that told the operator the
        # opposite of what had happened.
        seen = material.visibility

    words = sum(len(one["text"].split()) for one in passage["paragraphs"])
    print(f"{passage_id} -> material {material_id} "
          f"({len(passage['paragraphs'])} paragraphs, {words} words, "
          f"{written} questions, {glossed} glossed, {marked} placed, {seen})")


async def run_all(ids: list[str], owner_id: uuid.UUID, *,
                  evidence_only: bool, vocabulary_only: bool) -> list[str]:
    """Every passage, in ONE event loop, reporting what could not be done.

    One loop and not one per passage, which is what this was. ``asyncio.run``
    closes the loop it opened; the database engine is module-level and its
    pooled connections are not, so the second passage got a connection bound
    to a loop that no longer existed and asyncpg said "cannot perform
    operation: another operation is in progress" — about two hundred times,
    having imported the first passage perfectly.

    It went unseen because the runner drives this a passage at a time, one
    PROCESS each (``run_reading.py``), where a per-passage loop is the only
    loop there is. ``--all`` is the path that has more than one.

    A failure is caught per passage and named at the end rather than stopping
    the run: two hundred passages is not a thing to restart because the
    hundred and ninth has no questions on disk.
    """
    failed: list[str] = []
    for passage_id in ids:
        try:
            if evidence_only:
                await place_evidence(passage_id, owner_id)
            elif vocabulary_only:
                await place_vocabulary(passage_id, owner_id)
            else:
                await import_passage(passage_id, owner_id)
        except (Exception, SystemExit) as failure:  # noqa: BLE001
            print(f"{passage_id} FAILED  {failure}", file=sys.stderr)
            failed.append(passage_id)
    return failed


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("passage_id", nargs="?")
    ap.add_argument("--book", type=int,
                    help="every passage of one book that has been read")
    ap.add_argument("--all", action="store_true",
                    help="every passage that has a text and questions on disk")
    ap.add_argument("--owner", required=True, type=uuid.UUID)
    ap.add_argument("--evidence-only", action="store_true",
                    help="place the evidence spans on materials that are "
                         "already imported, and change nothing else")
    ap.add_argument("--vocabulary-only", action="store_true",
                    help="re-import the glossed words onto materials that "
                         "are already imported, and change nothing else")
    args = ap.parse_args()

    if args.passage_id:
        ids = [args.passage_id]
    else:
        conn = sqlite3.connect(SEED / "catalogue.db")
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id FROM passage"
            + (" WHERE book_number = ?" if args.book else "")
            + " ORDER BY book_number, test_no, passage_no",
            (args.book,) if args.book else ()).fetchall()
        conn.close()
        # Only what is actually ready. A passage whose text or questions have
        # not been read is not a failure to report here -- it is a stage that
        # has not run, and the readers' own --report says so.
        ids = [row["id"] for row in rows
               if (SEED / "work" / row["id"] / "passage.json").exists()
               and (SEED / "work" / row["id"] / "questions.json").exists()]
        if not ids:
            print("nothing ready to import; run seed/read_passages.py, "
                  "seed/read_passage_questions.py and seed/build_questions.py",
                  file=sys.stderr)
            return 1

    failed = asyncio.run(run_all(ids, args.owner,
                                 evidence_only=args.evidence_only,
                                 vocabulary_only=args.vocabulary_only))
    if failed:
        print(f"\n{len(failed)} passage(s) failed: {', '.join(failed)}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
