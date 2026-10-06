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
* **Only from a recording a PUBLIC material uses.** A clip is a derivative
  served to everyone, so eligibility is POSITIVE: a blob is a source only if at
  least one material with ``visibility = 'public'`` uses it (``materials
  .audio_asset_id`` -> ``audio_asset.blob_id``). A blob in no material at all
  is NOT a source -- an unattached upload is some Studio user's private file,
  and "nobody has said it is private" is not "its owner published it". The same
  test is made again when a clip is SERVED (:func:`servable_clip_clauses`): a
  material turned private after verification takes its clips out of service
  at once, and so does a correction (``transcript_overrides``) made after.
* **A failed clip does not hold a slot.** ``failed`` is a fault of the cut
  (an undecodable recording), not an answer about the word, so it does not
  count toward the three and the form may get a replacement -- from another
  recording: the blob that failed is not offered again for that form. A
  *transient* storage error is not a failure at all: the row stays
  ``candidate`` for the next pass (see :func:`cut_clips`).
* **A clip too quiet to level is unusable** (:data:`~app.services.audio_pcm
  .MIN_USABLE_DBFS`): levelling is capped, so a near-silent window would
  otherwise be served as noise. It goes ``failed`` with the reason, and TTS
  serves the word.

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
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import String, cast, exists, func
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
from app.services.infra_errors import InfrastructureError, guarded
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
    all of them. Heteronyms (in either accent) are dropped here (decision 2); forms with no
    words are ignored."""
    index: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for form in set(forms):
        words = tuple(form.split())
        if not words or pronunciation.is_heteronym_any_accent(form):
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


def _used_by_public_material(blob_id_column):
    """EXISTS: a material with ``visibility = 'public'`` plays this blob. The
    ONLY way a recording becomes a clip source -- no material, or only private
    ones, is not."""
    return exists().where(
        AudioAsset.blob_id == blob_id_column,
        Material.audio_asset_id == AudioAsset.id,
        Material.visibility == "public",
    )


def _eligible_blob_clause():
    """Ready, and used by at least one public material (see the module
    docstring). Clauses over ``AudioBlob``."""
    return (
        AudioBlob.transcript_status == TranscriptStatus.READY,
        _used_by_public_material(AudioBlob.id),
    )


def servable_clip_clauses():
    """Clauses over ``WordClip`` that must hold at SERVE time, on top of
    ``status = 'verified'``: the recording is STILL a source (ready, still in a
    public material) and the clip's segment is STILL uncorrected by any asset
    over that recording. Indexing checked both once; a material can be made
    private, or a segment corrected, any time after a clip was verified."""
    still_a_source = exists().where(
        AudioBlob.id == WordClip.blob_id,
        AudioBlob.transcript_status == TranscriptStatus.READY,
        _used_by_public_material(AudioBlob.id),
    )
    corrected = exists().where(
        AudioAsset.blob_id == WordClip.blob_id,
        func.jsonb_exists(
            AudioAsset.transcript_overrides, cast(WordClip.segment_order_index, String)
        ),
    )
    return (still_a_source, ~corrected)


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

    # What already exists, per form: which places and which recordings. A
    # `failed` row keeps its PLACE taken (it would only fail again) but not its
    # slot, and its recording is not offered again for the form: failing is a
    # fault of the cut, not an answer about the word, so the form may get a
    # replacement from elsewhere.
    taken_places: dict[str, set[tuple[uuid.UUID, int, int, int]]] = defaultdict(set)
    taken_blobs: dict[str, set[uuid.UUID]] = defaultdict(set)
    failed_blobs: dict[str, set[uuid.UUID]] = defaultdict(set)
    holding: dict[str, int] = defaultdict(int)
    existing = (
        await session.exec(
            select(
                WordClip.form,
                WordClip.blob_id,
                WordClip.segment_order_index,
                WordClip.word_start_index,
                WordClip.word_end_index,
                WordClip.status,
            )
        )
    ).all()
    for form, blob_id, seg, i, j, status in existing:
        taken_places[form].add((blob_id, seg, i, j))
        if status == ClipStatus.FAILED:
            failed_blobs[form].add(blob_id)
        else:
            taken_blobs[form].add(blob_id)
            holding[form] += 1

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
        slots = MAX_PER_FORM - holding.get(form, 0)
        if slots <= 0:
            continue
        for o in choose_candidates(
            (o for o in occurrences if o.blob_id not in failed_blobs.get(form, ())),
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

class UnusableClip(ValueError):
    """The window cannot become a clip: nothing there, or too quiet to level."""


def cut_window(data: bytes, start_ms: int, end_ms: int) -> bytes:
    """One window of ``data`` as a levelled 24 kHz mono AAC m4a. Raises
    :class:`UnusableClip` (a ``ValueError``) if the window decodes to nothing (a
    timestamp past the end of a truncated file) or is quieter than
    :data:`audio_pcm.MIN_USABLE_DBFS` -- levelling is capped, so a window like
    that would be served as amplified noise rather than a word."""
    samples = audio_pcm.decode_range(data, start_ms, end_ms)
    if len(samples) < audio_pcm.SAMPLE_RATE // 100:  # under 10 ms
        raise UnusableClip(f"nothing to cut at {start_ms}-{end_ms} ms")
    level = audio_pcm.rms_dbfs(samples)
    if level < audio_pcm.MIN_USABLE_DBFS:
        raise UnusableClip(
            f"too quiet at {start_ms}-{end_ms} ms ({level:.0f} dBFS, "
            f"floor {audio_pcm.MIN_USABLE_DBFS:.0f})"
        )
    return audio_pcm.encode_m4a(audio_pcm.normalise_rms(samples))


@dataclass
class CutReport:
    cut: int = 0
    failed: int = 0
    #: Left ``candidate`` because storage had a transient fault; the next pass
    #: tries again.
    deferred: int = 0


@dataclass
class _BlobOutcome:
    """What cutting one recording came to, gathered off the session so the
    cuts can run concurrently and the session still be touched by one task."""

    group: Sequence[WordClip]
    #: ``(clip, word key, context key)`` for each clip cut and stored.
    cut: list[tuple[WordClip, str, str]]
    failed: list[tuple[WordClip, Exception]]
    #: Clips left ``candidate`` by a transient fault, and its error.
    deferred: Sequence[WordClip] = ()
    deferred_error: Exception | None = None


async def count_candidates() -> int:
    """Clips still waiting to be cut (progress for the seed script)."""
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        return int(
            (
                await session.exec(
                    select(func.count()).select_from(WordClip).where(
                        WordClip.status == ClipStatus.CANDIDATE
                    )
                )
            ).one()
        )


async def _cut_blob(
    storage: MediaStorage, storage_key: str | None, group: Sequence[WordClip]
) -> _BlobOutcome:
    """Fetch one recording and cut every clip of it. Touches no session."""
    out = _BlobOutcome(group=group, cut=[], failed=[])
    try:
        if storage_key is None:
            raise ValueError("recording is gone")
        data = await storage.get(storage_key)
    except InfrastructureError as exc:
        out.deferred, out.deferred_error = group, exc
        return out
    except Exception as exc:  # noqa: BLE001 - recorded on each row
        out.failed = [(clip, exc) for clip in group]
        return out
    for position, clip in enumerate(group):
        try:
            word = await asyncio.to_thread(cut_window, data, clip.start_ms, clip.end_ms)
            context = await asyncio.to_thread(
                cut_window, data, clip.context_start_ms, clip.context_end_ms
            )
            word_key, context_key = clip_storage_key(word), clip_storage_key(context)
            await storage.put(word_key, word, CLIP_MIME)
            await storage.put(context_key, context, CLIP_MIME)
        except InfrastructureError as exc:
            out.deferred, out.deferred_error = group[position:], exc
            break
        except Exception as exc:  # noqa: BLE001 - one bad clip must not stop the run
            logger.warning("clip %s (%r) failed to cut: %s", clip.id, clip.form, exc)
            out.failed.append((clip, exc))
        else:
            out.cut.append((clip, word_key, context_key))
    return out


async def cut_clips(
    session: AsyncSession,
    *,
    storage: MediaStorage | None = None,
    limit: int | None = None,
    blob_ids: Sequence[uuid.UUID] | None = None,
    form_whitelist: Iterable[str] | None = None,
    concurrency: int = 1,
) -> CutReport:
    """Cut every ``candidate`` clip (up to ``limit``): the word, and the word
    in its context, stored content-addressed; the row goes to ``cut``.

    Grouped by recording so each blob's bytes are fetched once however many
    clips come from it. A clip that cannot be cut goes to ``failed`` with the
    reason, and the rest carry on -- one truncated recording must not stop a
    library-wide run. A TRANSIENT storage error (throttling, a disk blip --
    ``infra_errors.classify_error``) is not the clip's fault: its rows stay
    ``candidate`` for the next pass, and only a permanent error (an undecodable
    or missing recording, a window with nothing audible in it) marks ``failed``.
    Rows are claimed ``FOR UPDATE SKIP LOCKED`` so the seed
    script and the worker can overlap without cutting twice.

    ``concurrency`` recordings are fetched and cut at once (the storage round
    trips overlap the decoding); the rows are updated, and committed once per
    recording, by this task alone -- one session is not for concurrent use.
    Memory is bounded by ``concurrency`` recordings' bytes."""
    storage = guarded(storage or get_storage())
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
    if not by_blob:
        await session.rollback()  # release the (empty) FOR UPDATE transaction
        return report
    storage_keys = {
        blob.id: blob.storage_key
        for blob in (
            await session.exec(select(AudioBlob).where(AudioBlob.id.in_(list(by_blob))))
        ).all()
    }

    gate = asyncio.Semaphore(max(1, concurrency))

    async def run(blob_id: uuid.UUID, group: list[WordClip]) -> _BlobOutcome:
        async with gate:
            return await _cut_blob(storage, storage_keys.get(blob_id), group)

    tasks = [asyncio.create_task(run(blob_id, group)) for blob_id, group in by_blob.items()]
    try:
        for finished in asyncio.as_completed(tasks):
            outcome = await finished
            for clip, word_key, context_key in outcome.cut:
                clip.storage_key, clip.context_storage_key = word_key, context_key
                clip.status, clip.error = ClipStatus.CUT, None
                clip.cut_at = datetime.now(timezone.utc)
                session.add(clip)
                report.cut += 1
            for clip, exc in outcome.failed:
                clip.status, clip.error = ClipStatus.FAILED, f"{type(exc).__name__}: {exc}"[:500]
                session.add(clip)
                report.failed += 1
            if outcome.deferred:
                # Storage is having a bad time: not the clips' fault. Leave
                # them `candidate` (the error is noted, so an operator can see
                # why they wait) and give the rest of this recording up.
                logger.warning("clip cut deferred, storage fault: %s", outcome.deferred_error)
                for clip in outcome.deferred:
                    clip.error = f"deferred: {outcome.deferred_error}"[:500]
                    session.add(clip)
                report.deferred += len(outcome.deferred)
            await session.commit()
    finally:
        for task in tasks:
            task.cancel()
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
    #: Forms this run will look at (set once the plan is made); progress only.
    forms_total: int = 0


class VerifyAborted(RuntimeError):
    """Too many clips in a row could not be verified at all (not rejected --
    unreadable or untranscribable): the model or the storage is broken, and
    carrying on would walk the whole library past it, leaving every clip
    ``cut`` and a log of warnings."""


async def verify_clips(
    session: AsyncSession,
    transcribe: Transcribe,
    *,
    storage: MediaStorage | None = None,
    limit_forms: int | None = None,
    form_whitelist: Iterable[str] | None = None,
    stop_at_first: bool = True,
    concurrency: int = 1,
    report: VerifyReport | None = None,
    max_consecutive_failures: int = 10,
) -> VerifyReport:
    """Transcribe each form's ``cut`` word clips and mark them ``verified``
    (the normalised transcription contains the form, :func:`heard_contains`) or
    ``rejected``. With ``stop_at_first`` (decision 3's run) a form is finished
    at its first verified clip: the remaining candidates stay ``cut``, unused,
    which costs nothing and spends no GPU time on a word that is already
    covered. Longest clips are tried first.

    Forms that already have a verified, still-servable clip are skipped, so a re-run after new
    materials only works on what is new.

    **One transcription stream, the rest overlapped.** ``transcribe`` (one
    model, one GPU) always runs on a single dedicated thread; ``concurrency``
    forms are worked on at once, so while one waits on a storage read or its
    database write another is being transcribed. Each form is still tried
    clip by clip, longest first, so ``stop_at_first`` means what it did.
    Results are written one ``UPDATE`` per clip on its own session (``WHERE
    status = 'cut'``, so a clip somebody else already resolved is not
    overwritten); ``session`` is used for the opening reads only and is rolled
    back after them rather than held open for hours.

    ``report`` may be passed in to be updated live (progress).
    :class:`VerifyAborted` after ``max_consecutive_failures`` clips in a row that
    could not be read or transcribed."""
    from sqlalchemy import update

    from app.core.database import async_session_factory

    storage = storage or get_storage()
    report = report if report is not None else VerifyReport()
    already = set(
        (
            await session.exec(
                select(WordClip.form).where(
                    WordClip.status == ClipStatus.VERIFIED, *servable_clip_clauses()
                )
            )
        ).all()
    )
    query = select(WordClip).where(WordClip.status == ClipStatus.CUT)
    if form_whitelist is not None:
        query = query.where(WordClip.form.in_(list(form_whitelist)))
    clips = (await session.exec(query.order_by(WordClip.form))).all()

    # Plain tuples, longest clip first: nothing ORM crosses into the tasks.
    by_form: dict[str, list[tuple[uuid.UUID, str, int]]] = defaultdict(list)
    for clip in clips:
        assert clip.storage_key is not None
        by_form[clip.form].append((clip.id, clip.storage_key, clip.end_ms - clip.start_ms))
    await session.rollback()

    plan = [
        (form, sorted(group, key=lambda c: -c[2]))
        for form, group in by_form.items()
        if not (stop_at_first and form in already)
    ]
    if limit_forms is not None:
        plan = plan[:limit_forms]
    report.forms_total = len(plan)
    pending = list(reversed(plan))  # pop() from the end keeps the form order
    failures = 0
    aborted: VerifyAborted | None = None
    executor = ThreadPoolExecutor(1, thread_name_prefix="whisper")

    async def write(clip_id: uuid.UUID, heard: str, ok: bool) -> bool:
        values: dict = {"heard": heard[:500], "status": ClipStatus.VERIFIED if ok else ClipStatus.REJECTED}
        if ok:
            values["verified_at"] = datetime.now(timezone.utc)
        async with async_session_factory() as own:
            result = await own.execute(
                update(WordClip)
                .where(WordClip.id == clip_id, WordClip.status == ClipStatus.CUT)
                .values(**values)
            )
            await own.commit()
        return bool(result.rowcount)

    async def one_form() -> None:
        nonlocal failures, aborted
        loop = asyncio.get_running_loop()
        while pending and aborted is None:
            form, group = pending.pop()
            for clip_id, storage_key, _length in group:
                if aborted is not None:
                    return
                try:
                    data = await storage.get(storage_key)
                    heard = await loop.run_in_executor(executor, transcribe, data)
                except Exception as exc:  # noqa: BLE001 - leave the clip `cut`, try the next
                    logger.warning("verifying clip %s (%r) failed: %s", clip_id, form, exc)
                    failures += 1
                    if failures >= max_consecutive_failures:
                        aborted = VerifyAborted(
                            f"{failures} clips in a row could not be verified; last error: "
                            f"{type(exc).__name__}: {exc}"
                        )
                        return
                    continue
                failures = 0
                ok = heard_contains(form, heard)
                if await write(clip_id, heard, ok):
                    if ok:
                        report.verified += 1
                    else:
                        report.rejected += 1
                if ok and stop_at_first:
                    break
            report.forms_done += 1

    try:
        await asyncio.gather(*(one_form() for _ in range(max(1, concurrency))))
    finally:
        executor.shutdown(wait=False)
    if aborted is not None:
        raise aborted
    return report
