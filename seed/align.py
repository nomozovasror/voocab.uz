"""Align one section's audioscript against its recording.

    seed/.venv/bin/python seed/align.py cam11-t1-s1

Reads `seed/work/<id>/turns.json` (the book's audioscript, as turns), aligns it
to the recording the catalogue names, and writes `aligned.json` beside it: one
entry per word of the book's own text, with the milliseconds it is spoken at.

The model is never asked WHAT was said, only WHEN. That is why it costs a
fraction of whisper-large-v3 and why the words come out spelled the way the
book spells them, names included.

Two things make this work on real Cambridge recordings:

**Chunking.** wav2vec2's attention is quadratic in sequence length, so one pass
over a whole section runs at 0.8x realtime while 30-second windows run at 11x
on the same machine. Emissions are frame-wise logits and concatenate cleanly.

**Star tokens.** The printed audioscript is not the whole recording. It starts
at the first line of dialogue, with no narrator introduction, no example replay
and none of the half-minute pauses for reading the questions -- for
cam11-t1-s1, 722 words of transcript against 9.6 minutes of audio, so about
half the recording has no text at all. A `*` absorbs audio the transcript does
not cover; without one, the aligner has to spend that audio on real words and
drags everything after it out of place.
"""

import argparse
import json
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

import numpy as np
import soundfile as sf
import torch
import torchaudio

SEED = pathlib.Path(__file__).resolve().parent
REPO = SEED.parent
MATERIALS = REPO / "Materials"
WORK = SEED / "work"
DB_PATH = SEED / "catalogue.db"

MODEL_SR = 16000
CHUNK_S, OVERLAP_S = 30.0, 2.0
STAR = "*"
#: MMS_FA's dictionary is a-z plus apostrophe and hyphen. Everything else is
#: punctuation the reader sees and the speaker doesn't.
KEEP = re.compile(r"[^a-z'\- ]+")

_ONES = ("zero one two three four five six seven eight nine ten eleven twelve "
         "thirteen fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = ("- - twenty thirty forty fifty sixty seventy eighty ninety").split()
_ORDINALS = {"1st": "first", "2nd": "second", "3rd": "third", "21st": "twenty first",
             "22nd": "twenty second", "23rd": "twenty third", "31st": "thirty first"}
#: The book prints "£115" and the speaker says "a hundred and fifteen POUNDS".
#: Dropping the symbol drops a spoken word, and the aligner then has to spend
#: it on whatever comes next.
_CURRENCY = {"£": "pounds", "$": "dollars", "€": "euros"}


def spell_number(n: int) -> str:
    """A number the way a British speaker reads it aloud.

    Needed because the transcript is the book's and the book prints digits. The
    obvious alternative -- letting a star absorb the number -- was tried and is
    worse: a star in the MIDDLE of the transcript is unbounded, and the one
    standing in for "200" swallowed the example's entire second playing, giving
    that turn a 71-second span. Stars are safe at the edges of the text and
    dangerous inside it."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        return f"{_TENS[n // 10]} {_ONES[n % 10]}".strip().replace(" zero", "")
    if n < 1000:
        rest = n % 100
        head = f"{_ONES[n // 100]} hundred"
        return head if not rest else f"{head} and {spell_number(rest)}"
    rest = n % 1000
    head = f"{spell_number(n // 1000)} thousand"
    return head if not rest else f"{head} {spell_number(rest)}"


def say(word: str) -> str:
    """One book word, as spoken. Digits become words; everything else is left
    exactly as the book has it."""
    lowered = word.lower().strip(".,?!;:'\"()")
    if lowered in _ORDINALS:
        return _ORDINALS[lowered]
    digits = re.sub(r"[^0-9]", "", lowered)
    if digits and not re.search(r"[a-z]", lowered):
        spoken = spell_number(int(digits))
        for symbol, name in _CURRENCY.items():
            if symbol in lowered:
                return f"{spoken} {name}"
        return spoken
    return word
#: Per-TOKEN, not per-word. "C-H-A-R" is four tokens and takes two seconds to
#: say letter by letter; judged as one word it looks like drift, and the first
#: version of this check duly reported the two most correctly-aligned words on
#: the page as its worst outliers.
MIN_PLAUSIBLE_MS_PER_TOKEN = 25
MAX_PLAUSIBLE_MS_PER_TOKEN = 400
#: Mean token probability below which a word is not really matched. The
#: aligner always returns an alignment; the score is the only thing that says
#: whether it believed it.
LOW_CONFIDENCE = 0.35


def load_audio(path: pathlib.Path) -> tuple[torch.Tensor, float]:
    """Mono 16 kHz, whatever the file arrived as.

    soundfile reads the mp3s directly, so no ffmpeg is needed; it has no AAC at
    all, which is what Cambridge 14 is, and there CoreAudio's afconvert decodes
    to a temporary wav."""
    try:
        data, sr = sf.read(path, dtype="float32", always_2d=True)
    except sf.LibsndfileError:
        with tempfile.TemporaryDirectory() as td:
            wav = pathlib.Path(td) / "decoded.wav"
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", str(path), str(wav)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            data, sr = sf.read(wav, dtype="float32", always_2d=True)

    waveform = torch.from_numpy(data.T.copy())
    if waveform.shape[0] > 1:  # the model wants one channel
        waveform = waveform.mean(dim=0, keepdim=True)
    duration_s = waveform.shape[1] / sr
    if sr != MODEL_SR:
        waveform = torchaudio.functional.resample(waveform, sr, MODEL_SR)
    return waveform, duration_s


def build_tokens(
    turns: list[dict],
) -> tuple[list[str], list[str], list[int | None], list[int]]:
    """Book words -> alignable tokens, remembering where each token came from.

    Returns the tokens, the words that survived, for each token the index of
    the word it belongs to (``None`` for a star), and for each surviving word
    the turn it was spoken in.

    That last list is built HERE, in the same loop as the words, and that is
    the whole point of it being here. Deriving it afterwards by re-splitting
    each turn's text counts words this function threw away -- "..." and the
    dashes -- so the two lists drift apart at the first one and every word
    after it lands in the wrong turn. The transcript then shows a line with the
    next speaker's words tacked onto it, and the replay spans move with them.

    A hyphenated word is split, because that is how it is spoken; the word's
    span is then its first token's start to its last token's end. Stars go
    where the recording is known to hold speech the book does not print: before
    the first line, at the mid-section break, and after the last.
    """
    tokens: list[str] = [STAR]
    owner: list[int | None] = [None]
    words: list[str] = []
    word_turn: list[int] = []

    for turn_index, turn in enumerate(turns):
        if turn["speaker"] == "__BREAK__":
            tokens.append(STAR)
            owner.append(None)
            continue
        for word in turn["text"].split():
            spoken = say(word)
            pieces = KEEP.sub("", spoken.lower().replace("-", " ")).split()
            if not pieces:
                # Printed and never spoken -- "..." and the dashes the book sets
                # between clauses. Dropping them is right; dropping a NUMBER the
                # same way was the bug that `say()` above exists to fix.
                continue
            index = len(words)
            words.append(word)  # the book's spelling is what comes back out
            word_turn.append(turn_index)
            for piece in pieces:
                tokens.append(piece)
                owner.append(index)
    tokens.append(STAR)
    owner.append(None)
    return tokens, words, owner, word_turn


def emit_chunked(model, waveform: torch.Tensor, device: str) -> torch.Tensor:
    n = waveform.shape[1]
    chunk, overlap = int(CHUNK_S * MODEL_SR), int(OVERLAP_S * MODEL_SR)
    stride = chunk - overlap
    pieces, start = [], 0
    with torch.inference_mode():
        while start < n:
            end = min(start + chunk, n)
            piece, _ = model(waveform[:, start:end].to(device))
            piece = piece[0].cpu()
            fps = piece.shape[0] / ((end - start) / MODEL_SR)
            head = 0 if start == 0 else int(OVERLAP_S / 2 * fps)
            tail = piece.shape[0] if end == n else piece.shape[0] - int(OVERLAP_S / 2 * fps)
            pieces.append(piece[head:tail])
            if end == n:
                break
            start += stride
    return torch.cat(pieces)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("section_id")
    ap.add_argument("--device", default="mps", choices=("mps", "cpu"))
    ap.add_argument("--clips", action="store_true",
                    help="cut the marked answer spans to wav, to check by ear")
    args = ap.parse_args()

    work = WORK / args.section_id
    turns_path = work / "turns.json"
    if not turns_path.exists():
        print(f"No audioscript at {turns_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM section WHERE id = ?", (args.section_id,)).fetchone()
    if row is None:
        print(f"{args.section_id} is not in the catalogue", file=sys.stderr)
        return 1

    turns = json.loads(turns_path.read_text())
    tokens, words, owner, word_turn = build_tokens(turns)
    waveform, duration_s = load_audio(MATERIALS / row["rel_path"])
    print(f"{args.section_id}: {duration_s / 60:.1f} min audio, {len(words)} words, "
          f"{tokens.count(STAR)} stars, device={args.device}")

    bundle = torchaudio.pipelines.MMS_FA
    model = bundle.get_model().to(args.device)
    tokenizer, aligner = bundle.get_tokenizer(), bundle.get_aligner()

    t0 = time.perf_counter()
    emission = emit_chunked(model, waveform, args.device)
    spans = aligner(emission, tokenizer(tokens))
    elapsed = time.perf_counter() - t0
    print(f"aligned in {elapsed:.1f}s -> {duration_s / elapsed:.1f}x realtime")

    fps = emission.shape[0] / duration_s
    to_ms = lambda frame: int(frame / fps * 1000)

    by_word: dict[int, list] = {}
    for span, word_index in zip(spans, owner):
        if word_index is None:  # a star belongs to no word
            continue
        start, end = to_ms(span[0].start), to_ms(span[-1].end)
        scores = [t.score for t in span]
        if word_index in by_word:
            by_word[word_index][1] = end
            by_word[word_index][2] += scores
        else:
            by_word[word_index] = [start, end, list(scores)]

    aligned = [{"word": words[i], "start_ms": by_word[i][0], "end_ms": by_word[i][1],
                "turn": word_turn[i],
                "tokens": len(by_word[i][2]),
                "score": round(sum(by_word[i][2]) / len(by_word[i][2]), 3)}
               for i in sorted(by_word)]
    (work / "aligned.json").write_text(json.dumps(aligned, indent=2))

    first, last = aligned[0], aligned[-1]
    covered = (last["end_ms"] - first["start_ms"]) / 1000
    print(f"\nfirst word at {first['start_ms'] / 1000:.1f}s, last ends at "
          f"{last['end_ms'] / 1000:.1f}s of {duration_s:.1f}s")
    print(f"transcript covers {covered:.0f}s; {duration_s - covered:.0f}s is "
          f"narration, example and pauses")

    per_token = np.array([(w["end_ms"] - w["start_ms"]) / w["tokens"] for w in aligned])
    scores = np.array([w["score"] for w in aligned])
    odd = [w for w in aligned
           if not MIN_PLAUSIBLE_MS_PER_TOKEN
           <= (w["end_ms"] - w["start_ms"]) / w["tokens"] <= MAX_PLAUSIBLE_MS_PER_TOKEN]
    weak = [w for w in aligned if w["score"] < LOW_CONFIDENCE]
    print(f"per-token duration: median {np.median(per_token):.0f}ms, {len(odd)} implausible")
    print(f"confidence: median {np.median(scores):.2f}, "
          f"{len(weak)} words under {LOW_CONFIDENCE} ({100 * len(weak) / len(aligned):.1f}%)")
    for w in sorted(weak, key=lambda w: w["score"])[:6]:
        print(f"    score {w['score']:.2f}  {w['word']!r} at {w['start_ms'] / 1000:.1f}s")

    marked: list[tuple[dict, list[dict]]] = []
    print("\nwhere each answer is spoken, from the book's own margin markers:")
    for i, turn in enumerate(turns):
        if not turn.get("marker"):
            continue
        ws = [w for w in aligned if w["turn"] == i]
        if not ws:
            continue
        marked.append((turn, ws))
        confidence = sum(w["score"] for w in ws) / len(ws)
        flag = "  <-- CHECK" if confidence < 0.6 else ""
        print(f"  {turn['marker']:<8} {ws[0]['start_ms'] / 1000:>6.1f}s - "
              f"{ws[-1]['end_ms'] / 1000:>6.1f}s  conf {confidence:.2f}   "
              f"{turn['answer']!r}{flag}")
    if args.clips:
        # A confident alignment and a correct one are different claims, and only
        # one of them can be settled by listening. Half a second of lead-in so
        # the first syllable is not clipped off.
        clips = work / "clips"
        clips.mkdir(exist_ok=True)
        audio, sr = sf.read(MATERIALS / row["rel_path"], dtype="float32", always_2d=True)
        for turn, ws in marked:
            a = max(0, int((ws[0]["start_ms"] / 1000 - 0.5) * sr))
            b = min(len(audio), int((ws[-1]["end_ms"] / 1000 + 0.5) * sr))
            sf.write(clips / f"{turn['marker']}.wav", audio[a:b], sr)
        print(f"\n{len(marked)} clips in {clips.relative_to(REPO)}")

    conn.execute(
        """UPDATE stage SET status = 'done', attempts = attempts + 1,
               output_path = ?, error = NULL, meta = ?, updated_at = datetime('now')
           WHERE section_id = ? AND name = 'align'""",
        (str((work / "aligned.json").relative_to(REPO)),
         json.dumps({"words": len(aligned), "realtime_factor": round(duration_s / elapsed, 1),
                     "median_score": round(float(np.median(scores)), 3),
                     "low_confidence_words": len(weak),
                     "first_word_s": round(first["start_ms"] / 1000, 1),
                     "uncovered_s": round(duration_s - covered)}),
         args.section_id))
    conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
