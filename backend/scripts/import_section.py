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
from app.models.audio_segment import AudioSegment
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_group import QuestionGroup
from app.models.user import User
from app.schemas.listening import FormCompletionGroupIn
from app.services import audio as audio_service
from app.services.asr import TranscriptResult, TranscriptSegment, WordTiming
from app.services.storage import (
    AUDIO_CONTENT_TYPES,
    audio_storage_key,
    get_storage,
    sha256_hex,
)

logger = logging.getLogger("scripts.import_section")

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
SEED = REPO / "seed"
MATERIALS = REPO / "Materials"


def read_alignment(section_id: str, offset_ms: int = 0) -> tuple[dict, list[TranscriptSegment], str]:
    """The catalogue row, the turns as transcript segments, and a title.

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
    row = conn.execute("SELECT * FROM section WHERE id = ?", (section_id,)).fetchone()
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

    book, test, section = row["book_number"], row["test_no"], row["section_no"]
    title = f"Cambridge IELTS {book} — Test {test}, Part {section}"
    return dict(row), segments, title


async def import_questions(session, part_id: uuid.UUID, section_id: str,
                           offset_ms: int = 0) -> int:
    """Replace this part's question groups with what the seed built.

    Replace rather than merge: the groups have no natural key, and a re-run
    after a corrected answer key must not leave the old one beside the new.
    """
    path = SEED / "work" / section_id / "questions.json"
    if not path.exists():
        return 0
    payload = json.loads(path.read_text())

    # Validated before anything is deleted, so a bad payload leaves the
    # material exactly as it was rather than emptied.
    groups = [FormCompletionGroupIn.model_validate(g) for g in payload["groups"]]

    existing = (await session.exec(
        select(QuestionGroup).where(QuestionGroup.part_id == part_id))).all()
    for group in existing:
        for question in (await session.exec(
                select(Question).where(Question.group_id == group.id))).all():
            await session.delete(question)
        await session.delete(group)
    await session.flush()

    written = 0
    for order_index, group in enumerate(groups):
        row = QuestionGroup(
            part_id=part_id, order_index=order_index, type=group.type,
            instructions=group.instructions, word_limit=group.word_limit,
            config=group.config.model_dump(mode="json", exclude_none=True),
        )
        session.add(row)
        await session.flush()
        for question in group.questions:
            # Shifted with the transcript: a replay span is a moment in the
            # same recording, and half of them moving is worse than none.
            start = question.replay_start_ms
            end = question.replay_end_ms
            session.add(Question(
                group_id=row.id, number=question.number,
                correct_answers=question.correct_answers,
                replay_start_ms=None if start is None else max(0, start - offset_ms),
                replay_end_ms=None if end is None else max(0, end - offset_ms),
            ))
            written += 1
    return written


async def import_section(section_id: str, owner_id: uuid.UUID) -> None:
    work = SEED / "work" / section_id
    trim_path = work / "trim.json"
    trim = json.loads(trim_path.read_text()) if trim_path.exists() else None
    offset_ms = trim["offset_ms"] if trim else 0

    row, segments, title = read_alignment(section_id, offset_ms)

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

        # Re-running must not leave a second copy behind. There is no natural
        # key on a material, so the title this script generates is the key it
        # looks itself up by.
        material = (
            await session.exec(
                select(Material).where(
                    Material.author_id == owner_id, Material.title == title
                )
            )
        ).first()
        if material is None:
            material = Material(
                author_id=owner_id, type="listening", title=title,
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
            )
            session.add(part)
            await session.flush()
            logger.info("created material %s", material.id)
        else:
            material.audio_asset_id = asset.id
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
    print(f"{section_id} -> material {material_id} "
          f"({len(segments)} transcript lines, {written} questions, private)")


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
