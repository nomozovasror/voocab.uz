"""Forced alignment, chunked.

The chunking is not an optimisation, it is the difference between the thing
working and not: wav2vec2's attention is quadratic in sequence length, so one
pass over a whole section runs at 0.8x realtime while 30-second windows run at
11x. Emissions are frame-wise logits, so windows concatenate cleanly; a small
overlap is trimmed at each seam to keep the boundary frames honest.
"""

import json, re, sys, time
import numpy as np, torch, torchaudio, soundfile as sf

DEVICE = sys.argv[1] if len(sys.argv) > 1 else "cpu"
CHUNK_S, OVERLAP_S = 30.0, 2.0
KEEP = re.compile(r"[^a-z'\- ]+")


def normalize(words):
    """Book words -> MMS_FA tokens, remembering which word each came from."""
    tokens, owner = [], []
    for i, w in enumerate(words):
        for piece in KEEP.sub("", w.lower().replace("-", " ")).split():
            tokens.append(piece)
            owner.append(i)
    return tokens, owner


def emit_chunked(model, waveform, sr):
    """Frame logits for the whole waveform, computed in overlapping windows."""
    n = waveform.shape[1]
    chunk, overlap = int(CHUNK_S * sr), int(OVERLAP_S * sr)
    stride = chunk - overlap
    pieces, start = [], 0
    with torch.inference_mode():
        while start < n:
            end = min(start + chunk, n)
            piece, _ = model(waveform[:, start:end].to(DEVICE))
            piece = piece[0].cpu()
            fps = piece.shape[0] / ((end - start) / sr)   # frames per second
            head = 0 if start == 0 else int(OVERLAP_S / 2 * fps)
            tail = piece.shape[0] if end == n else piece.shape[0] - int(OVERLAP_S / 2 * fps)
            pieces.append(piece[head:tail])
            if end == n:
                break
            start += stride
    return torch.cat(pieces), n


turns = json.load(open("turns.json"))
words, word_turn = [], []
for ti, t in enumerate(turns):
    for w in t["text"].split():
        words.append(w); word_turn.append(ti)
tokens, owner = normalize(words)

data, sr = sf.read("section.wav", dtype="float32", always_2d=True)
waveform = torch.from_numpy(data.T.copy())
if waveform.shape[0] > 1:
    waveform = waveform.mean(dim=0, keepdim=True)
duration_s = waveform.shape[1] / sr

bundle = torchaudio.pipelines.MMS_FA
model = bundle.get_model().to(DEVICE)
tokenizer, aligner = bundle.get_tokenizer(), bundle.get_aligner()

t0 = time.perf_counter()
emission, n_samples = emit_chunked(model, waveform, sr)
if DEVICE == "mps":
    torch.mps.synchronize()
emit_s = time.perf_counter() - t0

t1 = time.perf_counter()
spans = aligner(emission, tokenizer(tokens))
align_s = time.perf_counter() - t1

fps = emission.shape[0] / duration_s
to_ms = lambda f: int(f / fps * 1000)

by_word = {}
for span, wi in zip(spans, owner):
    s, e = to_ms(span[0].start), to_ms(span[-1].end)
    by_word[wi] = (by_word[wi][0], e) if wi in by_word else (s, e)

out = [{"word": words[i], "start_ms": by_word[i][0], "end_ms": by_word[i][1],
        "turn": word_turn[i]} for i in sorted(by_word)]
json.dump(out, open(f"aligned-{DEVICE}.json", "w"), indent=2)

total = emit_s + align_s
print(f"[{DEVICE}] emission {emit_s:.1f}s | align {align_s:.1f}s | "
      f"{total:.1f}s for {duration_s:.1f}s -> {duration_s/total:.1f}x realtime")

# --- accuracy against the timings the audio was actually built from --------
truth = json.load(open("truth.json"))
starts, ends = [], []
for ti, tr in enumerate(truth):
    ws = [w for w in out if w["turn"] == ti]
    if not ws:
        continue
    starts.append(abs(ws[0]["start_ms"] / 1000 - tr["true_start_s"]))
    ends.append(abs(ws[-1]["end_ms"] / 1000 - tr["true_end_s"]))
a = np.array(starts + ends)
print(f"[{DEVICE}] turn-boundary error over {len(truth)} turns: "
      f"median {np.median(a)*1000:.0f}ms | p90 {np.percentile(a,90)*1000:.0f}ms | max {a.max()*1000:.0f}ms")
