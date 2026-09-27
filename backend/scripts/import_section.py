"""Write an aligned seed section into the app database.

    uv run python -m scripts.import_section cam11-t1-s1 --owner <user-uuid>

The other half of the seed pipeline. Extraction lives in ``seed/`` because it
needs torch and no database; this lives here because it needs the database and
no torch, and because the rows it writes have to go through the same services
the API uses rather than around them.

What it writes, for one section:

* an ``AudioBlob`` for the recording, content-addressed and deduped exactly as
  an upload would be -- a file already ingested is recognised by its SHA-256
  and not stored twice;
* one ``AudioSegment`` per **speaker turn**, with the word timings forced
  alignment produced. The turn is the segment because the book prints it as
  one: a change of speaker is the only boundary in the source that means
  anything, and it is the one the review page's transcript lines want;
* an ``AudioAsset`` claiming the blob for the owner;
* a ``Material`` and its single ``Part``.

The material is created **private**, and there is no option here to make it
public: this is copyrighted source, and it is in the database to prove the
pipeline works rather than to be practised by anybody.

Questions are written too, when `seed/work/<id>/questions.json` exists. They go
in through `FormCompletionGroupIn` rather than straight into the tables: that
schema is where "the template's gaps must match the question numbers" and "an
answer may not be blank" actually live, and a seed script that inserted rows
behind it would be the one caller allowed to write a material the editor could
never have produced.
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
from app.models.attempt import Attempt
from app.models.audio_segment import AudioSegment
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_attempt import QuestionAttempt
from app.models.question_group import QuestionGroup, same_question_kind
from app.models.user import User
from pydantic import TypeAdapter

from app.schemas.listening import QuestionGroupIn
from app.services import audio as audio_service
from app.services import difficulty as difficulty_service
from app.services import grading as grading_service
from app.services import images as image_service
from app.services import listening as listening_service
from app.services.asr import TranscriptResult, TranscriptSegment, WordTiming
from app.services.image_codec import read_image
from app.services.storage import (
    AUDIO_CONTENT_TYPES,
    audio_storage_key,
    get_storage,
    image_storage_key,
    sha256_hex,
)

logger = logging.getLogger("scripts.import_section")

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
SEED = REPO / "seed"
MATERIALS = REPO / "Materials"


def read_alignment(
    section_id: str, offset_ms: int = 0
) -> tuple[dict, list[TranscriptSegment], str, str]:
    """The catalogue row, the turns as segments, the reference and the title.

    ``offset_ms`` is how much was cut off the front of the recording. Every
    timestamp here was measured against the untrimmed file, so all of them
    move by it -- a transcript that still points at the original moments would
    run three minutes late against the audio actually being served.

    A turn with no aligned words is dropped rather than written empty: the
    aligner skips what it could not place, and a segment with no timing is a
    row the review page cannot draw.
    """
    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT s.*, b.title AS book_title FROM section s "
        "JOIN book b ON b.number = s.book_number WHERE s.id = ?",
        (section_id,)).fetchone()
    conn.close()
    if row is None:
        raise SystemExit(f"{section_id} is not in the catalogue")

    work = SEED / "work" / section_id
    turns = json.loads((work / "turns.json").read_text())
    aligned = json.loads((work / "aligned.json").read_text())

    by_turn: dict[int, list[dict]] = {}
    for word in aligned:
        by_turn.setdefault(word["turn"], []).append(word)

    segments: list[TranscriptSegment] = []
    for index in sorted(by_turn):
        words = by_turn[index]
        speaker = turns[index]["speaker"]
        segments.append(
            TranscriptSegment(
                order_index=len(segments),
                start_ms=words[0]["start_ms"] - offset_ms,
                end_ms=words[-1]["end_ms"] - offset_ms,
                # Built FROM the words, not from the book's line. `text` and
                # `words` are two renderings of the same thing and the editor
                # swaps between them -- it draws `text` normally and rebuilds
                # the line from `words` on the line being spoken -- so any
                # difference between them makes the text visibly change as the
                # audio arrives.
                #
                # Two things therefore do not survive into the transcript. The
                # speaker name, because AudioSegment has nowhere to put one and
                # a fake entry in `words` would be highlighted as speech and
                # would sit in the timings `marks.ts` searches. And the standalone
                # punctuation the book sets between clauses -- "..." and the
                # dashes -- which is printed, never spoken, and so was never
                # aligned. Losing them costs a little prose; keeping them costs
                # the invariant.
                text=" ".join(w["word"] for w in words),
                words=[WordTiming(word=w["word"], start_ms=w["start_ms"] - offset_ms,
                                  end_ms=w["end_ms"] - offset_ms) for w in words],
            )
        )

    # The invariant the editor relies on, checked here rather than discovered
    # on the page: joining a segment's words must give back its text.
    for segment in segments:
        rebuilt = " ".join(w.word for w in segment.words)
        if " ".join(segment.text.split()) != " ".join(rebuilt.split()):
            raise SystemExit(
                f"{section_id} segment {segment.order_index}: text and words "
                f"disagree, which makes the line change as the audio reaches "
                f"it.\n  text:  {segment.text!r}\n  words: {rebuilt!r}")

    test, section = row["test_no"], row["section_no"]
    # The book's own title, not one built from its number. "Cambridge IELTS
    # {number}" is right for the eleven numbered editions and gives book 101
    # -- IELTS Trainer -- the name "Cambridge IELTS 101". The catalogue holds
    # what each book is actually called, and for the numbered ones it holds
    # exactly the string this used to build, so no existing material's title
    # moves. That matters beyond tidiness: the title is the key this script
    # dedups on, and a changed one seeds a second copy instead of updating
    # the first.
    # Two things, in two columns -- see import_passage for the argument.
    # "C11 T4 P2". The book's own name is in the COLLECTION -- one course per
    # book per paper -- so repeating it on every one of its sixteen materials
    # is thirty-odd characters a card that say the same thing sixteen times.
    reference = f"{book_code(row['book_number'])} T{test} P{section}"
    # The book first, ours second, the code last. Three sources in the order
    # of how much they are worth.
    title = (printed_name(section_id)
             or derived_name(section_id)
             or reference)
    return dict(row), segments, reference, title


def printed_name(section_id: str) -> str | None:
    """What the book calls this section, or nothing.

    A reading passage prints its title at the top of the page and a listening
    part does not -- the book prints "Part 3" and plays a recording. So every
    listening material was called "C11 T4 · Part 2" and nothing else, a code
    where its reading neighbour on the same shelf has a name.

    But the name IS printed, over the first task on the sheet: "Oyster Bay
    Sailing Club Courses" above the table, "SELF-DRIVE TOURS IN THE USA"
    above the notes. It is a heading in the layout grammar, so it is already
    built and already exactly what the book printed. 156 of 266 sections have
    one.

    The rest are almost all Part 3 -- multiple choice and matching, which
    print questions and no heading at all -- and they keep the reference as
    their name. That is the honest answer and not a gap: the book did not
    name them, and a name taken from the transcript would be this app
    telling a learner the book said something it did not.

    The FIRST heading. A sheet's own title is printed above its first task; a
    later one belongs to a later task on the same sheet ("General
    information" over questions 7-10).
    """
    path = SEED / "work" / section_id / "questions.json"
    if not path.exists():
        return None
    for group in json.loads(path.read_text()).get("groups", []):
        # Inside `config`, where the group's layout lives -- not beside it.
        template = (group.get("config") or {}).get("template") or ""
        for line in template.splitlines():
            if line.startswith("#") and line[1:].strip():
                return line[1:].strip()
    return None


def derived_name(section_id: str) -> str | None:
    """What `seed/name_sections.py` decided the recording is about.

    Read only after :func:`printed_name` comes back empty, and kept in its own
    file for exactly that reason: this title is OURS, not the book's, and the
    two must not be able to be confused six months from now. `name.json`
    records the model that wrote it and the day it did.

    110 of the 272 sections need it -- the Part 2s and Part 3s answered by
    multiple choice and matching, which print questions and no heading at all.
    Leaving them named by their reference put "C10 T1 P2" on a shelf between
    "Joining the leisure club" and "THE SPIRIT BEAR", which is a row a learner
    cannot tell apart from the three under it.
    """
    path = SEED / "work" / section_id / "name.json"
    if not path.exists():
        return None
    return (json.loads(path.read_text()).get("title") or "").strip() or None


#: What each book is called in a material's title, short.
#:
#: The full name is too long to repeat on every card in a list of 447 --
#: "The Official Cambridge Guide to IELTS" is 37 characters before the test
#: number -- and the distinctive part of a reading title is the passage's own
#: name, which has to come first and survive truncation.
#:
#: Keyed by the catalogue's book NUMBER and not derived from the title,
#: because three of these books have no number in their name and the reading
#: ids call them 101, 102 and 103 -- which read as "Cambridge 101" and are
#: not that at all. A table says what each one is; a regex over the title
#: would have to guess.
BOOK_CODE = {
    10: "C10", 11: "C11", 12: "C12", 13: "C13", 14: "C14", 15: "C15",
    16: "C16", 17: "C17", 18: "C18", 19: "C19", 20: "C20", 21: "C21",
    101: "TR",    # IELTS Trainer
    102: "GD",    # The Official Cambridge Guide to IELTS
    103: "TR2",   # IELTS Trainer 2
}


def book_code(number: int) -> str:
    """This book's short code, or its number where it has none.

    A number is a poor label and a wrong one is worse: falling back to
    ``#22`` for a book nobody has coded yet is visibly unfinished, where
    guessing "C22" would quietly claim it is a Cambridge volume.
    """
    return BOOK_CODE.get(number, f"#{number}")


def paper_first(section_no: int) -> int:
    """The number this part's first question carries on the whole paper.

    A Listening paper runs 1 to 40 straight through, ten to a part, and says
    so out loud: "now turn to questions thirty-one to forty". A seeded
    material is one part of such a paper, so Part 4 has to start at 31 or the
    page and the recording disagree in front of the learner.
    """
    return (section_no - 1) * 10 + 1


async def _picture_blob_id(session, section_id: str, order_index: int,
                           picture: dict) -> uuid.UUID:
    """Store a group's picture (or dedup one already stored) and hand back its
    blob id, ready to drop into ``config.image``.

    A labelling group is unpublishable without the picture its letters sit
    on, and the picture is the one thing on the page a vision model cannot
    hand back -- extract_image.py cuts it out and names it here. Split out of
    the two callers below so the fresh-material path and the re-import path
    read a picture the same way rather than two copies that could drift.
    """
    data = (SEED / "work" / section_id / picture["path"]).read_bytes()
    sha = sha256_hex(data)
    sized = read_image(data)
    if sized is None:
        raise SystemExit(
            f"{section_id}: group {order_index}'s picture is not a PNG, "
            "JPEG or WebP the server will take")
    mime, width, height = sized
    key = image_storage_key(sha, mime)
    blob, created = await image_service.get_or_create_blob(
        session, sha256=sha, storage_key=key, size_bytes=len(data),
        mime_type=mime, width=width, height=height)
    if created:
        await get_storage().put(key, data, mime)
    logger.info("group %d: picture %dx%d (%s)", order_index, width, height,
                "new" if created else "dedup")
    return blob.id


def _question_columns(
    question, offset_ms: int
) -> tuple[int | None, int | None, dict | None]:
    """The three columns a question's own presentation lands in --
    ``replay_start_ms``, ``replay_end_ms``, ``config`` -- shifted by the trim
    exactly as a fresh import always has. Pulled out so the re-import path
    below computes them the same way rather than a second copy that could
    disagree about it.
    """
    # Shifted with the transcript: a replay span is a moment in the same
    # recording, and half of them moving is worse than none.
    start = question.replay_start_ms
    end = question.replay_end_ms
    # A gap has nothing of its own; a choice question carries its stem and
    # its options; a matching item carries its stem and answers from the
    # group's box. Same division as the group's config, one level down -- see
    # the Question model.
    config = None
    prompt = getattr(question, "prompt", None)
    if prompt is not None:
        config = {"prompt": prompt}
        options = getattr(question, "options", None)
        if options:
            config["options"] = list(options)
        # Shifted like every other timestamp: a choice question's moments
        # live in the same recording the trim moved.
        replay = getattr(question, "option_replay", None) or {}
        if replay:
            config["option_replay"] = {
                letter: [max(0, at[0] - offset_ms), max(0, at[1] - offset_ms)]
                for letter, at in replay.items()
            }
    return (
        None if start is None else max(0, start - offset_ms),
        None if end is None else max(0, end - offset_ms),
        config,
    )


async def import_questions(session, part_id: uuid.UUID, section_id: str,
                           offset_ms: int = 0) -> int:
    """Write this part's question groups from what the seed built.

    A first import creates them outright. A RE-import updates the existing
    rows IN PLACE instead of replacing them -- matching an old group to a new
    one by its position, and an old question to a new one by ``number`` --
    because ``question_attempts.question_id`` is a plain FK with no ON DELETE
    and Postgres refuses to drop a question anyone has answered. Matching
    means a correction (a widened replay span, a fixed spelling in the key)
    reaches a question that has already been sat: the row's id survives, so
    does the attempt pointing at it, and that attempt is RE-GRADED against
    the corrected row (see :func:`_regrade`) rather than frozen at whatever
    the book said before the mistake was found -- the decision this
    implements is in the ``voocab-reimport-regrade`` memory note and in
    ``seed/README.md``'s "A marker's turn is not always its evidence".

    Refuses, loudly, and leaves the existing questions untouched, only where
    the shape has genuinely changed: a group added or removed, a group
    retyped into a different KIND of question (:func:`same_question_kind`),
    or a group's own question numbers no longer matching. Everything else
    about the import -- title, transcript, audio -- still lands either way,
    exactly as it did when the only fallback here was "leave the questions
    alone".
    """
    path = SEED / "work" / section_id / "questions.json"
    if not path.exists():
        return 0
    payload = json.loads(path.read_text())

    # Validated before anything is written, so a bad payload leaves the
    # material exactly as it was rather than half-rewritten. Through the
    # discriminated union rather than one member of it: a section is as
    # likely to be multiple choice or matching as a gap-fill, and validating
    # everything as a completion group refused the first choice section
    # outright.
    adapter = TypeAdapter(QuestionGroupIn)
    groups = [adapter.validate_python(g) for g in payload["groups"]]

    existing_groups = (await session.exec(
        select(QuestionGroup).where(QuestionGroup.part_id == part_id)
        .order_by(QuestionGroup.order_index))).all()

    if existing_groups:
        return await _update_questions_in_place(
            session, part_id, section_id, existing_groups, groups, payload,
            offset_ms)

    written = 0
    for order_index, group in enumerate(groups):
        picture = payload["groups"][order_index].get("picture")
        if picture:
            group.config.image = await _picture_blob_id(
                session, section_id, order_index, picture)

        row = QuestionGroup(
            part_id=part_id, order_index=order_index, type=group.type,
            instructions=group.instructions, word_limit=group.word_limit,
            config=group.config.model_dump(mode="json", exclude_none=True),
        )
        session.add(row)
        await session.flush()
        for question in group.questions:
            start, end, config = _question_columns(question, offset_ms)
            session.add(Question(
                group_id=row.id, number=question.number,
                correct_answers=question.correct_answers,
                config=config, replay_start_ms=start, replay_end_ms=end,
            ))
            written += 1
    return written


async def _update_questions_in_place(
    session, part_id: uuid.UUID, section_id: str,
    existing_groups: list[QuestionGroup], groups: list, payload: dict,
    offset_ms: int,
) -> int:
    """The re-import half of :func:`import_questions`.

    Every check below runs BEFORE any row is touched, so a refusal leaves the
    part exactly as it was -- never half rewritten -- the same guarantee the
    old delete-then-recreate path had by construction.
    """
    if len(existing_groups) != len(groups):
        logger.warning(
            "%s: questions NOT rewritten -- %d group(s) in this import, %d "
            "already there. A group was added or removed, which is a shape "
            "change this can't match through. Everything else was updated.",
            section_id, len(groups), len(existing_groups))
        return 0

    plan: list[tuple[QuestionGroup, object, dict[int, Question]]] = []
    for old_group, group in zip(existing_groups, groups):
        if not same_question_kind(old_group.type, group.type):
            logger.warning(
                "%s: questions NOT rewritten -- group %d changed from %s to "
                "%s, and that is not the same question wearing a new label. "
                "Everything else was updated.",
                section_id, old_group.order_index, old_group.type, group.type)
            return 0
        old_questions = {
            q.number: q for q in (await session.exec(
                select(Question).where(
                    Question.group_id == old_group.id))).all()
        }
        new_numbers = {q.number for q in group.questions}
        if set(old_questions) != new_numbers:
            logger.warning(
                "%s: questions NOT rewritten -- group %d's question numbers "
                "changed (%s -> %s). Everything else was updated.",
                section_id, old_group.order_index,
                sorted(old_questions), sorted(new_numbers))
            return 0
        plan.append((old_group, group, old_questions))

    written = 0
    changed_ids: list[uuid.UUID] = []
    for order_index, (old_group, group, old_questions) in enumerate(plan):
        picture = payload["groups"][order_index].get("picture")
        if picture:
            group.config.image = await _picture_blob_id(
                session, section_id, order_index, picture)

        old_group.type = group.type
        old_group.instructions = group.instructions
        old_group.word_limit = group.word_limit
        old_group.config = group.config.model_dump(mode="json", exclude_none=True)
        session.add(old_group)

        for question in group.questions:
            start, end, config = _question_columns(question, offset_ms)
            row = old_questions[question.number]
            row.correct_answers = question.correct_answers
            row.config = config
            row.replay_start_ms = start
            row.replay_end_ms = end
            session.add(row)
            changed_ids.append(row.id)
            written += 1

    await session.flush()
    await _regrade(session, part_id, section_id, changed_ids)
    return written


async def _regrade(
    session, part_id: uuid.UUID, section_id: str, question_ids: list[uuid.UUID]
) -> None:
    """Recompute ``is_correct`` for every attempt already made against these
    questions, and the score of every attempt that owns one of them.

    The ``voocab-reimport-regrade`` decision: an attempt survives a rewritten
    question, and its score CHANGES rather than staying frozen at whatever
    the uncorrected key said. Silent -- and cheap, one query that returns
    nothing -- for every question nobody has ever answered, which is every
    question in most re-imports; the real work only happens where a real
    attempt exists.
    """
    if not question_ids:
        return
    rows = (await session.exec(
        select(QuestionAttempt, Question, QuestionGroup)
        .join(Question, Question.id == QuestionAttempt.question_id)  # type: ignore[arg-type]
        .join(QuestionGroup, QuestionGroup.id == Question.group_id)  # type: ignore[arg-type]
        .where(QuestionAttempt.question_id.in_(question_ids)))).all()  # type: ignore[attr-defined]
    if not rows:
        return

    touched: set[uuid.UUID] = set()
    for question_attempt, question, group in rows:
        correct = grading_service.grade_question(
            question, question_attempt.given_answer, group)
        if correct != question_attempt.is_correct:
            question_attempt.is_correct = correct
            session.add(question_attempt)
        touched.add(question_attempt.attempt_id)

    for attempt_id in touched:
        attempt = await session.get(Attempt, attempt_id)
        if attempt is None:
            continue
        # The FULL set of this attempt's rows, not only the ones a changed
        # question touched -- the score is a sum over the whole paper (or the
        # whole drill), the same arithmetic `_grade_into` in grading.py runs
        # at submit time.
        all_rows = (await session.exec(
            select(QuestionAttempt, QuestionGroup)
            .join(Question, Question.id == QuestionAttempt.question_id)  # type: ignore[arg-type]
            .join(QuestionGroup, QuestionGroup.id == Question.group_id)  # type: ignore[arg-type]
            .where(QuestionAttempt.attempt_id == attempt_id))).all()  # type: ignore[attr-defined]
        earned = total = 0
        for row, row_group in all_rows:
            marks = listening_service.question_marks(row_group)
            total += marks
            if row.is_correct:
                earned += marks
        attempt.score = float(earned)
        attempt.total_questions = total
        session.add(attempt)

    await session.flush()
    logger.info(
        "%s: re-graded %d question-attempt row(s) across %d attempt(s)",
        section_id, len(rows), len(touched))

    part = await session.get(Part, part_id)
    if part is not None:
        # Scoped to the one material just touched, not the whole library --
        # the same narrowed form `difficulty.recompute` keeps for a
        # submit-time refresh of the one material just answered.
        await difficulty_service.recompute(session, [part.material_id])


async def import_section(section_id: str, owner_id: uuid.UUID) -> None:
    work = SEED / "work" / section_id
    trim_path = work / "trim.json"
    trim = json.loads(trim_path.read_text()) if trim_path.exists() else None
    offset_ms = trim["offset_ms"] if trim else 0

    row, segments, reference, title = read_alignment(section_id, offset_ms)

    # The source is checked even when a trimmed copy is what gets stored: a
    # changed source means the alignment, and therefore the cut, was measured
    # against different audio.
    source = MATERIALS / row["rel_path"]
    if sha256_hex(source.read_bytes()) != row["sha256"]:
        raise SystemExit(
            f"{section_id}: the source audio has changed since the manifest was "
            f"built. Re-run seed/manifest.py, re-align, and re-trim before importing.")

    path = (work / "audio.mp3") if trim else source
    mime_type = AUDIO_CONTENT_TYPES.get(path.suffix.lower())
    if mime_type is None:
        raise SystemExit(f"{path.name}: unsupported extension {path.suffix}")

    data = path.read_bytes()
    sha256 = sha256_hex(data)
    duration_ms = trim["duration_ms"] if trim else row["duration_ms"]
    if trim:
        logger.info("using the trimmed copy: %ds cut from the front, %ds from the end",
                    trim["cut_head_ms"] // 1000, trim["cut_tail_ms"] // 1000)

    result = TranscriptResult(duration_ms=duration_ms, segments=segments)
    key = audio_storage_key(sha256, mime_type)

    async with async_session_factory() as session:
        if await session.get(User, owner_id) is None:
            raise SystemExit(f"no user {owner_id}")

        blob, created = await audio_service.get_or_create_blob(
            session, sha256=sha256, storage_key=key,
            size_bytes=len(data), mime_type=mime_type,
        )
        if created:
            await get_storage().put(key, data, mime_type)
        else:
            logger.info("dedup: blob %s already stored", blob.id)

        # The transcript is rewritten every run, not only on a new blob. A
        # re-import is what happens after the ALIGNMENT was corrected, and
        # keeping the old segments because the audio bytes had not changed is
        # how a fixed alignment silently fails to reach the page.
        existing = (await session.exec(
            select(AudioSegment).where(AudioSegment.blob_id == blob.id))).all()
        for old in existing:
            await session.delete(old)
        await session.flush()
        await audio_service.persist_transcript_result(session, blob, result)
        logger.info("blob %s: wrote %d segment(s) (replaced %d)",
                    blob.id, len(segments), len(existing))

        asset = await audio_service.get_or_create_asset(
            session, owner_id, blob.id, title=title)

        # Re-running must not leave a second copy behind, and the REFERENCE is
        # what it looks itself up by. It used to be the title, which meant the
        # key was a display string: renaming the corpus had to be done as a
        # migration rather than a re-import, twice, because a re-import would
        # not have recognised its own work.
        # WITH the type. "C10 T1 P1" is Cambridge 10's first test, first
        # paper -- and every test has two of those, a listening Part 1 and a
        # reading Passage 1. The reference names a place in a book; which of
        # the two papers is the material's own type, and looking one up
        # without saying which finds the other one half the time.
        material = (
            await session.exec(
                select(Material).where(
                    Material.author_id == owner_id,
                    Material.type == "listening",
                    Material.reference == reference,
                )
            )
        ).first()
        if material is None:
            material = Material(
                author_id=owner_id, type="listening", title=title,
                reference=reference,
                audio_asset_id=asset.id,
                visibility="private",  # copyrighted source; never public from here
            )
            session.add(material)
            await session.flush()
            part = Part(
                material_id=material.id, order_index=0,
                title=f"Part {row['section_no']}",
                # NULL/NULL: this part IS the whole recording, because the book's
                # audio was already published one section per file.
                audio_start_ms=None, audio_end_ms=None,
                first_number=paper_first(row["section_no"]),
            )
            session.add(part)
            await session.flush()
            logger.info("created material %s", material.id)
        else:
            material.audio_asset_id = asset.id
            # The title too, for the same reason the transcript is rewritten
            # below: a section rebuilt after its first task was read properly
            # is a section whose printed heading has only just been found.
            material.title = title
            session.add(material)
            part = (await session.exec(
                select(Part).where(Part.material_id == material.id)
                .order_by(Part.order_index))).first()
            logger.info("material %s already existed, re-pointed at the asset", material.id)

        # The seeded part IS the whole recording -- the book published one
        # section per file and the trim removed everything that was not it. So
        # the bounds are cleared on EVERY import, not only when the part is
        # created: a stray end mark left in the editor bounds playback to it,
        # and one at 6.1s is indistinguishable from "the audio is broken".
        # Set on every import, like the bounds below and for the same reason:
        # it is a fact about which part of a paper this is, not an editorial
        # choice somebody might have made in the studio since.
        if part.first_number != paper_first(row["section_no"]):
            part.first_number = paper_first(row["section_no"])
            session.add(part)

        if part.audio_start_ms is not None or part.audio_end_ms is not None:
            logger.info("clearing part bounds %s-%s: the part is the whole recording",
                        part.audio_start_ms, part.audio_end_ms)
            part.audio_start_ms = None
            part.audio_end_ms = None
            session.add(part)

        written = await import_questions(session, part.id, section_id, offset_ms)
        if written:
            # Every authoring write bumps the counter the editor checks against.
            material.version += 1
            session.add(material)
            logger.info("wrote %d question(s)", written)

        await session.commit()
        material_id = str(material.id)

    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.execute(
        """UPDATE stage SET status = 'done', attempts = attempts + 1,
               error = NULL, meta = ?, updated_at = datetime('now')
           WHERE section_id = ? AND name = 'import'""",
        (json.dumps({"material_id": material_id, "segments": len(segments),
                     "questions": written, "visibility": "private",
                     "trimmed_ms": offset_ms}), section_id))
    conn.commit()
    conn.close()
    # "0 questions" reads as a material with none, which is not what
    # happened and is the wrong thing to leave in a log that somebody scans
    # for failures.
    said = (f"{written} questions" if written
            else "no questions written (none extracted yet, or see the log above)")
    print(f"{section_id} -> material {material_id} "
          f"({len(segments)} transcript lines, {said}, private)")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("section_id")
    ap.add_argument("--owner", required=True, type=uuid.UUID)
    args = ap.parse_args()
    asyncio.run(import_section(args.section_id, args.owner))
    return 0


if __name__ == "__main__":
    sys.exit(main())
