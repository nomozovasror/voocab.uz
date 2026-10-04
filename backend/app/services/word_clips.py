"""Word clips: the learner hears the word as it is really spoken.

The first rule of vocabulary stage 3 (brief §1): where a word occurs in a
listening material, its audio is CUT from that recording rather than
synthesised -- real speech, a real speaker, the word the way it arrives in an
exam. We already have word-level timestamps for every recording
(``audio_segment.words``), so the audio is free. This module is the whole
pipeline from those timestamps to a servable file, in three separate steps
because they run in three separate places:

1. **Index** (:func:`index_clips`) -- find the places in the transcripts where
   a lexicon form is spoken and keep the best few. Pure database work, cheap,
   idempotent; runs in the worker for blobs that become ready later and in the
   seed script for the whole library.
2. **Cut** (:func:`cut_clips`) -- decode the recording around each candidate
   and store two small files: the word, and the word with its neighbours.
   Needs PyAV (a main dependency) and the recording's bytes; runs in the
   worker and in the seed script.
3. **Verify** (:func:`verify_clips`) -- transcribe the cut word with an ASR
   model and keep it only if the word is heard. Seed only: the model is
   faster-whisper on a GPU and has no place in a request or in the worker
   image. **Only ``verified`` clips are ever served** (see
   :mod:`app.services.word_audio`).

## The rules, and why each one is here

* **Exact form** (decision 1). A candidate is an occurrence of a lexeme's
  lemma in EXACTLY that form -- normalised case- and punctuation-insensitively
  (:func:`normalise_word`), nothing else. ``played`` is not a clip of ``play``:
  in `listen` the learner types what they hear, and a clip of the wrong form
  would make the correct answer wrong. A phrase is a consecutive run of words.
* **Never the first or last word of a segment.** The ASR cuts a segment at a
  breath or a pause and the boundary word is the one most often clipped,
  swallowed or glued to its neighbour. The brief says to avoid it; a phrase is
  skipped if its run touches either end. It also guarantees the context clip
  has a neighbour on each side.
* **A corrected segment is never a source.** An owner's correction
  (``audio_asset.transcript_overrides``) rewrites a segment's TEXT, not its
  timings -- the words and their timestamps no longer describe what the text
  says. Any asset over the blob correcting a segment disqualifies it.
* **Heteronyms are never indexed** (decision 2). The transcript has no part of
  speech, so a `record` clip might be the verb; every heteronym is always TTS
  with the sense's own pronunciation (:mod:`app.services.pronunciation`).
* **At most three candidates per form**, preferring distinct recordings
  (variety, and one bad recording cannot poison a word) and longer words (a
  word the ASR gave time to is usually a clearly spoken one). The count is
  TOTAL, not new: a form with three rejected clips is not offered a fourth --
  after three tries the answer is the TTS voice, and re-running the index must
  converge rather than keep digging.
* **Plausible timings only.** A word shorter than 60 ms or longer than 1.5 s
  per word is an alignment artefact (ASR "words" can swallow a pause), not a
  word, and the verifier would only spend GPU time rejecting it.
* **Not from a recording only private materials use.** A clip is a derivative
  served to everyone, so a blob that is attached to materials and to NONE
  that is public is not a source. A blob attached to no material at all (the
  owner's seeded library, before it is published) is.

## Padding

The cut runs 150 ms before the word's first timestamp to 150 ms after its
last (brief §1): in real speech sounds run into each other, and a word cut
exactly on its timestamps sounds synthetic. The window is clamped to the
recording (:func:`padded_range`). The context clip is the word plus two words
either side inside the same segment, padded the same way.
"""

import asyncio
import logging
import uuid
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import exists, or_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.audio_asset import AudioAsset
from app.models.audio_blob import AudioBlob, TranscriptStatus
from app.models.audio_segment import AudioSegment
from app.models.lexicon import Lexeme
from app.models.material import Material
from app.models.word_clip import ClipStatus, WordClip
from app.services import audio_pcm, pronunciation
from app.services.storage import MediaStorage, get_storage, sha256_hex

logger = logging.getLogger(__name__)

PAD_MS = 150
CONTEXT_WORDS = 2
MAX_PER_FORM = 3
MIN_WORD_MS = 60
MAX_MS_PER_WORD = 1500

CLIP_MIME = "audio/mp4"


def clip_storage_key(data: bytes) -> str:
    """``clips/{sha256}.m4a`` -- content-addressed like every other key."""
    return f"clips/{sha256_hex(data)}.m4a"


# --- Normalisation ------------------------------------------------------------


def normalise_word(raw: str) -> str | None:
    """One transcript token as a comparable word, or ``None`` if it is not a
    word at all (a stray dash, a lone quote).

    Lower-cased; every character that is not a letter or digit is dropped,
    EXCEPT an apostrophe or hyphen BETWEEN two letters/digits (``don't``,
    ``e-mail``) -- those are part of the word, and dropping them would turn
    ``don't`` into ``dont`` and ``well-known`` into one lump nobody wrote.
    Curly apostrophes are straightened first."""
    text = raw.replace("’", "'").replace("‘", "'").strip().lower()
    out: list[str] = []
    for index, char in enumerate(text):
        if char.isalnum():
            out.append(char)
        elif char in "'-" and 0 < index < len(text) - 1:
            before, after = text[index - 1], text[index + 1]
            if before.isalnum() and after.isalnum():
                out.append(char)
    word = "".join(out)
    return word or None


def normalise_form(text: str) -> str:
    """A lemma or phrase as its form: each word normalised, joined by a single
    space. ``"Give  rise to"`` -> ``"give rise to"``."""
    words = (normalise_word(part) for part in text.split())
    return " ".join(w for w in words if w)


def heard_contains(form: str, heard: str) -> bool:
    """Whether the verifier's transcription contains ``form`` as consecutive
    words (so ``"Well, hello there."`` contains ``hello``). Hyphens compare as
    spaces on both sides: an ASR may write ``e-mail`` as ``e mail``."""
    target = normalise_form(form).replace("-", " ").split()
    if not target:
        return False
    tokens: list[str] = []
    for part in heard.split():
        word = normalise_word(part)
        if word:
            tokens.extend(word.replace("-", " ").split())
    size = len(target)
    return any(tokens[i : i + size] == target for i in range(len(tokens) - size + 1))


def padded_range(
    start_ms: int, end_ms: int, limit_ms: int | None, pad_ms: int = PAD_MS
) -> tuple[int, int]:
    """``start_ms``..``end_ms`` widened by ``pad_ms`` each way and clamped to
    the recording: never before 0, never past ``limit_ms`` (the blob's
    duration, when known)."""
    start = max(0, start_ms - pad_ms)
    end = end_ms + pad_ms
    if limit_ms is not None:
        end = min(end, limit_ms)
        start = min(start, end)
    return start, end


# --- Finding occurrences (pure) ------------------------------------------------


@dataclass(frozen=True)
class Occurrence:
    """One place a form is spoken, with everything a ``word_clips`` row needs."""

    form: str
    blob_id: uuid.UUID
    segment_order_index: int
    word_start_index: int
    word_end_index: int
    start_ms: int
    end_ms: int
    context_start_index: int
    context_end_index: int
    context_start_ms: int
    context_end_ms: int

    @property
    def word_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def place(self) -> tuple[uuid.UUID, int, int, int]:
        return (
            self.blob_id,
            self.segment_order_index,
            self.word_start_index,
            self.word_end_index,
        )


def forms_index(forms: Iterable[str]) -> dict[str, list[tuple[str, ...]]]:
    """``{first word: [every form's word tuple starting with it]}``, longest
    first, so a scan checks the few forms that can start at a word instead of
    all of them. Heteronyms are dropped here (decision 2); forms with no
    words are ignored."""
    index: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for form in set(forms):
        words = tuple(form.split())
        if not words or pronunciation.is_heteronym(form):
            continue
        index[words[0]].append(words)
    for runs in index.values():
        runs.sort(key=len, reverse=True)
    return index


def find_occurrences(
    blob_id: uuid.UUID,
    segment_order_index: int,
    words: Sequence[dict],
    index: dict[str, list[tuple[str, ...]]],
    *,
    blob_duration_ms: int | None = None,
) -> list[Occurrence]:
    """Every occurrence of an indexed form in one segment's words, subject to
    the module docstring's rules (not first/last in the segment, plausible
    timings). The segment must NOT be an overridden one -- the caller decides
    that, because only it knows the assets.

    Matching is on the normalised tokens; a token that is not a word at all
    breaks a run, so ``"give, rise"`` still matches ``give rise`` (the comma is
    stripped) but ``"give — rise"`` does not (the dash is a token of its own)."""
    tokens = [normalise_word(str(w.get("word", ""))) for w in words]
    found: list[Occurrence] = []
    count = len(words)
    for i, token in enumerate(tokens):
        if token is None or i == 0:
            continue
        for run in index.get(token, ()):
            j = i + len(run) - 1
            if j >= count - 1:  # the run touches the segment's end
                continue
            if tuple(tokens[i : j + 1]) != run:
                continue
            try:
                start = int(words[i]["start_ms"])
                end = int(words[j]["end_ms"])
                ctx_i = max(0, i - CONTEXT_WORDS)
                ctx_j = min(count - 1, j + CONTEXT_WORDS)
                ctx_start = int(words[ctx_i]["start_ms"])
                ctx_end = int(words[ctx_j]["end_ms"])
            except (KeyError, TypeError, ValueError):
                continue
            span = end - start
            if span < MIN_WORD_MS or span > MAX_MS_PER_WORD * len(run):
                continue
            padded_start, padded_end = padded_range(start, end, blob_duration_ms)
            ctx_padded_start, ctx_padded_end = padded_range(
                ctx_start, ctx_end, blob_duration_ms
            )
            found.append(
                Occurrence(
                    form=" ".join(run),
                    blob_id=blob_id,
                    segment_order_index=segment_order_index,
                    word_start_index=i,
                    word_end_index=j,
                    start_ms=padded_start,
                    end_ms=padded_end,
                    context_start_index=ctx_i,
                    context_end_index=ctx_j,
                    context_start_ms=ctx_padded_start,
                    context_end_ms=ctx_padded_end,
                )
            )
    return found


def choose_candidates(
    occurrences: Iterable[Occurrence],
    *,
    taken_places: Collection[tuple[uuid.UUID, int, int, int]] = (),
    taken_blobs: Collection[uuid.UUID] = (),
    slots: int = MAX_PER_FORM,
) -> list[Occurrence]:
    """Up to ``slots`` of one form's occurrences: longest words first, a
    recording not yet represented before one that is, then (if slots remain)
    the longest of what is left.

    ``taken_*`` are the form's rows that already exist, so a re-run neither
    duplicates nor reshuffles them: the caller passes ``slots = 3 - existing``.
    Deterministic -- ties break on the place -- because "idempotent" includes
    "the same answer twice"."""
    ranked = sorted(
        (o for o in occurrences if o.place not in taken_places),
        key=lambda o: (-o.word_ms, str(o.blob_id), o.segment_order_index, o.word_start_index),
    )
    chosen: list[Occurrence] = []
    used_blobs = set(taken_blobs)
    for occurrence in ranked:
        if len(chosen) >= slots:
            break
        if occurrence.blob_id in used_blobs:
            continue
        chosen.append(occurrence)
        used_blobs.add(occurrence.blob_id)
    for occurrence in ranked:
        if len(chosen) >= slots:
            break
        if occurrence not in chosen:
            chosen.append(occurrence)
    return chosen


# --- Index (database) ---------------------------------------------------------


async def lexicon_forms(session: AsyncSession) -> set[str]:
    """Every non-proper-noun lexeme's normalised lemma. Exact forms only: no
    lemmatisation of the transcript, no inflection of the lemma."""
    lemmas = (
        await session.exec(select(Lexeme.lemma).where(Lexeme.is_proper_noun.is_(False)))
    ).all()
    return {form for form in (normalise_form(lemma) for lemma in lemmas) if form}


def _eligible_blob_clause():
    """Ready, and not used only by private materials (see the module
    docstring)."""
    has_material = exists().where(
        AudioAsset.blob_id == AudioBlob.id, Material.audio_asset_id == AudioAsset.id
    )
    has_public = exists().where(
        AudioAsset.blob_id == AudioBlob.id,
        Material.audio_asset_id == AudioAsset.id,
        Material.visibility == "public",
    )
    return (
        AudioBlob.transcript_status == TranscriptStatus.READY,
        or_(~has_material, has_public),
    )


async def _overridden_segments(
    session: AsyncSession, blob_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, set[int]]:
    """``{blob id: order_index values any asset corrects}``."""
    rows = (
        await session.exec(
            select(AudioAsset.blob_id, AudioAsset.transcript_overrides).where(
                AudioAsset.blob_id.in_(blob_ids)
            )
        )
    ).all()
    out: dict[uuid.UUID, set[int]] = defaultdict(set)
    for blob_id, overrides in rows:
        for key in (overrides or {}):
            try:
                out[blob_id].add(int(key))
            except ValueError:
                continue
    return out


@dataclass
class IndexReport:
    blobs: int = 0
    candidates_seen: int = 0
    inserted: int = 0


async def index_clips(
    session: AsyncSession,
    *,
    blob_ids: Sequence[uuid.UUID] | None = None,
    forms: Iterable[str] | None = None,
    blob_batch: int = 25,
) -> IndexReport:
    """Write ``candidate`` rows for the best places each form is spoken.

    ``blob_ids`` limits the scan (the worker passes the blobs it has not
    looked at; tests pass their own); ``forms`` replaces the lexicon (tests).
    Commits once per batch of blobs. Idempotent: running it again changes
    nothing, because what it would add is chosen against what exists (see
    :func:`choose_candidates`)."""
    wanted = set(forms) if forms is not None else await lexicon_forms(session)
    index = forms_index(wanted)
    report = IndexReport()
    if not index:
        return report

    query = select(AudioBlob.id, AudioBlob.duration_ms).where(*_eligible_blob_clause())
    if blob_ids is not None:
        query = query.where(AudioBlob.id.in_(list(blob_ids)))
    blobs = (await session.exec(query.order_by(AudioBlob.created_at, AudioBlob.id))).all()

    # What already exists, per form: which places and which recordings.
    taken_places: dict[str, set[tuple[uuid.UUID, int, int, int]]] = defaultdict(set)
    taken_blobs: dict[str, set[uuid.UUID]] = defaultdict(set)
    existing = (
        await session.exec(
            select(
                WordClip.form,
                WordClip.blob_id,
                WordClip.segment_order_index,
                WordClip.word_start_index,
                WordClip.word_end_index,
            )
        )
    ).all()
    for form, blob_id, seg, i, j in existing:
        taken_places[form].add((blob_id, seg, i, j))
        taken_blobs[form].add(blob_id)

    found: dict[str, list[Occurrence]] = defaultdict(list)
    for offset in range(0, len(blobs), blob_batch):
        batch = blobs[offset : offset + blob_batch]
        ids = [blob_id for blob_id, _ in batch]
        durations = dict(batch)
        overridden = await _overridden_segments(session, ids)
        segments = (
            await session.exec(
                select(AudioSegment)
                .where(AudioSegment.blob_id.in_(ids))
                .order_by(AudioSegment.blob_id, AudioSegment.order_index)
            )
        ).all()
        for segment in segments:
            if segment.order_index in overridden.get(segment.blob_id, ()):
                continue
            for occurrence in find_occurrences(
                segment.blob_id,
                segment.order_index,
                segment.words,
                index,
                blob_duration_ms=durations.get(segment.blob_id),
            ):
                found[occurrence.form].append(occurrence)
                report.candidates_seen += 1
        report.blobs += len(batch)

    rows: list[dict] = []
    now = datetime.now(timezone.utc)
    for form, occurrences in found.items():
        slots = MAX_PER_FORM - len(taken_places.get(form, ()))
        if slots <= 0:
            continue
        for o in choose_candidates(
            occurrences,
            taken_places=taken_places.get(form, set()),
            taken_blobs=taken_blobs.get(form, set()),
            slots=slots,
        ):
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "form": o.form,
                    "blob_id": o.blob_id,
                    "segment_order_index": o.segment_order_index,
                    "word_start_index": o.word_start_index,
                    "word_end_index": o.word_end_index,
                    "start_ms": o.start_ms,
                    "end_ms": o.end_ms,
                    "context_start_index": o.context_start_index,
                    "context_end_index": o.context_end_index,
                    "context_start_ms": o.context_start_ms,
                    "context_end_ms": o.context_end_ms,
                    "status": ClipStatus.CANDIDATE,
                    "created_at": now,
                }
            )
    for offset in range(0, len(rows), 500):
        result = await session.execute(
            pg_insert(WordClip).values(rows[offset : offset + 500]).on_conflict_do_nothing(
                constraint="uq_word_clip_place"
            )
        )
        report.inserted += result.rowcount or 0
    await session.commit()
    return report


async def unindexed_blob_ids(
    session: AsyncSession, seen: set[uuid.UUID]
) -> list[uuid.UUID]:
    """Eligible blobs the caller has not indexed yet -- what the worker's clip
    step feeds :func:`index_clips`, so a blob that became ready after startup
    is picked up without rescanning the whole library every interval."""
    ids = (await session.exec(select(AudioBlob.id).where(*_eligible_blob_clause()))).all()
    return [blob_id for blob_id in ids if blob_id not in seen]


# --- Cut ----------------------------------------------------------------------

def cut_window(data: bytes, start_ms: int, end_ms: int) -> bytes:
    """One window of ``data`` as a levelled 24 kHz mono AAC m4a. Raises
    ``ValueError`` if the window decodes to nothing (a timestamp past the end
    of a truncated file)."""
    samples = audio_pcm.decode_range(data, start_ms, end_ms)
    if len(samples) < audio_pcm.SAMPLE_RATE // 100:  # under 10 ms
        raise ValueError(f"nothing to cut at {start_ms}-{end_ms} ms")
    return audio_pcm.encode_m4a(audio_pcm.normalise_rms(samples))


@dataclass
class CutReport:
    cut: int = 0
    failed: int = 0


async def cut_clips(
    session: AsyncSession,
    *,
    storage: MediaStorage | None = None,
    limit: int | None = None,
    blob_ids: Sequence[uuid.UUID] | None = None,
    form_whitelist: Iterable[str] | None = None,
) -> CutReport:
    """Cut every ``candidate`` clip (up to ``limit``): the word, and the word
    in its context, stored content-addressed; the row goes to ``cut``.

    Grouped by recording so each blob's bytes are fetched once however many
    clips come from it. A clip that cannot be cut goes to ``failed`` with the
    reason, and the rest carry on -- one truncated recording must not stop a
    library-wide run. Rows are claimed ``FOR UPDATE SKIP LOCKED`` so the seed
    script and the worker can overlap without cutting twice."""
    storage = storage or get_storage()
    report = CutReport()
    query = (
        select(WordClip)
        .where(WordClip.status == ClipStatus.CANDIDATE)
        .order_by(WordClip.blob_id, WordClip.segment_order_index, WordClip.word_start_index)
    )
    if blob_ids is not None:
        query = query.where(WordClip.blob_id.in_(list(blob_ids)))
    if form_whitelist is not None:
        query = query.where(WordClip.form.in_(list(form_whitelist)))
    if limit is not None:
        query = query.limit(limit)
    clips = (await session.exec(query.with_for_update(skip_locked=True))).all()

    by_blob: dict[uuid.UUID, list[WordClip]] = defaultdict(list)
    for clip in clips:
        by_blob[clip.blob_id].append(clip)

    for blob_id, group in by_blob.items():
        blob = await session.get(AudioBlob, blob_id)
        try:
            if blob is None:
                raise ValueError("recording is gone")
            data = await storage.get(blob.storage_key)
        except Exception as exc:  # noqa: BLE001 - recorded on each row below
            for clip in group:
                clip.status, clip.error = ClipStatus.FAILED, f"{type(exc).__name__}: {exc}"[:500]
                session.add(clip)
                report.failed += 1
            await session.commit()
            continue
        for clip in group:
            try:
                word = await asyncio.to_thread(cut_window, data, clip.start_ms, clip.end_ms)
                context = await asyncio.to_thread(
                    cut_window, data, clip.context_start_ms, clip.context_end_ms
                )
                word_key, context_key = clip_storage_key(word), clip_storage_key(context)
                await storage.put(word_key, word, CLIP_MIME)
                await storage.put(context_key, context, CLIP_MIME)
            except Exception as exc:  # noqa: BLE001 - one bad clip must not stop the run
                logger.warning("clip %s (%r) failed to cut: %s", clip.id, clip.form, exc)
                clip.status, clip.error = ClipStatus.FAILED, f"{type(exc).__name__}: {exc}"[:500]
                report.failed += 1
            else:
                clip.storage_key, clip.context_storage_key = word_key, context_key
                clip.status, clip.error = ClipStatus.CUT, None
                clip.cut_at = datetime.now(timezone.utc)
                report.cut += 1
            session.add(clip)
        await session.commit()
    if not by_blob:
        await session.rollback()  # release the (empty) FOR UPDATE transaction
    return report


# --- Verify (seed only) --------------------------------------------------------

#: Bytes of a word clip -> what an ASR model heard. Synchronous; the caller
#: runs it off the event loop. faster-whisper in the seed script, a fake in
#: tests.
Transcribe = Callable[[bytes], str]


@dataclass
class VerifyReport:
    verified: int = 0
    rejected: int = 0
    forms_done: int = 0


async def verify_clips(
    session: AsyncSession,
    transcribe: Transcribe,
    *,
    storage: MediaStorage | None = None,
    limit_forms: int | None = None,
    form_whitelist: Iterable[str] | None = None,
    stop_at_first: bool = True,
) -> VerifyReport:
    """Transcribe each form's ``cut`` word clips and mark them ``verified``
    (the normalised transcription contains the form, :func:`heard_contains`) or
    ``rejected``. With ``stop_at_first`` (decision 3's run) a form is finished
    at its first verified clip: the remaining candidates stay ``cut``, unused,
    which costs nothing and spends no GPU time on a word that is already
    covered. Longest clips are tried first.

    Forms that already have a verified clip are skipped, so a re-run after new
    materials only works on what is new."""
    storage = storage or get_storage()
    report = VerifyReport()
    already = set(
        (
            await session.exec(
                select(WordClip.form).where(WordClip.status == ClipStatus.VERIFIED)
            )
        ).all()
    )
    query = select(WordClip).where(WordClip.status == ClipStatus.CUT)
    if form_whitelist is not None:
        query = query.where(WordClip.form.in_(list(form_whitelist)))
    clips = (await session.exec(query.order_by(WordClip.form))).all()

    by_form: dict[str, list[WordClip]] = defaultdict(list)
    for clip in clips:
        by_form[clip.form].append(clip)

    for form, group in by_form.items():
        if stop_at_first and form in already:
            continue
        if limit_forms is not None and report.forms_done >= limit_forms:
            break
        group.sort(key=lambda c: -(c.end_ms - c.start_ms))
        for clip in group:
            assert clip.storage_key is not None
            try:
                data = await storage.get(clip.storage_key)
                heard = await asyncio.to_thread(transcribe, data)
            except Exception as exc:  # noqa: BLE001 - leave the clip `cut`, try the next
                logger.warning("verifying clip %s (%r) failed: %s", clip.id, form, exc)
                continue
            clip.heard = heard[:500]
            if heard_contains(form, heard):
                clip.status = ClipStatus.VERIFIED
                clip.verified_at = datetime.now(timezone.utc)
                report.verified += 1
            else:
                clip.status = ClipStatus.REJECTED
                report.rejected += 1
            session.add(clip)
            await session.commit()
            if clip.status == ClipStatus.VERIFIED and stop_at_first:
                break
        report.forms_done += 1
    return report
