"""The one place that knows how to show a page to a model.

Three providers, all speaking OpenAI's chat format with images inlined as data
URLs, chosen with `SEED_VISION=groq|gemini|nvidia`:

* **groq** -- `qwen/qwen3.8-27b`. Fast, and metered: this pipeline's cost is
  dominated not by one pass over the corpus but by how many passes it takes to
  get a stage right, which is not knowable in advance. Four passes and a
  page-location scan came to $10.
* **gemini** -- `gemini-3.1-flash-lite`, the cheapest thing in the catalogue
  that reads a page, and measured against the hand transcription before it was
  adopted: 41 turns, 11 of 11 margin markers on the same turns, at a cent a
  section. `SEED_VISION_MODEL` overrides it, and `gemini-flash-lite-latest` is
  an alias Google keeps pointed at the current one. NOTE that `PRICES` below
  is written for THIS model; a bigger one makes the ledger read low.
* **nvidia** -- build.nvidia.com's catalogue, free through the developer
  programme and rate-limited near 40 requests a minute instead. That trade is
  the right way round for work that is mostly iteration.

Measure a new provider before adopting it. `nvidia` is in this table and is
not the default, because the measurement said no -- see the README. What has
to hold is not "does it transcribe the page" but "does it answer the narrow
question", and the margin markers are where that has been decided every time.

Being one file is the point. Nine other scripts read pages through this and
none of them knows which provider answered.

Every request's token counts go to `work/usage.jsonl`, and `spend.py` adds
them up. This exists because the first estimate of what the corpus would cost
was made by reading the code, and came out eight times under: the number that
matters is not what one page costs but how many times a page is read, and only
a ledger knows that.

Requests go out through `curl` rather than `urllib`: Groq sits behind
Cloudflare, which answers urllib's default User-Agent with a 403 and an error
code that says nothing about the real problem.
"""

import base64
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time

#: provider -> endpoint, the .env key it reads, and what to ask by default.
PROVIDERS = {
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "env": "GROQ_API_KEY",
        "model": "qwen/qwen3.8-27b",
        "images": 3,
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "env": "GEMINI_API_KEY",
        "model": "gemini-3.1-flash-lite",
        "images": 3,
    },
    "nvidia": {
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "env": "NVIDIA_API_KEY",
        "model": "nvidia/llama-3.1-nemotron-nano-vl-8b-v1",
        "images": 4,
    },
}
#: What a provider charges per million tokens, in and out. Kept here because
#: the alternative -- and what happened -- is an estimate made by reading the
#: code and guessing at the multiplier. A rate that has moved makes the ledger
#: wrong by a known factor; no ledger at all makes it wrong by an unknown one.
#: Checked 2026-09-08.
PRICES = {
    "groq":   {"in": 0.29, "out": 0.59},
    "gemini": {"in": 0.25, "out": 1.50},   # 3.1-flash-lite, the default below
    "nvidia": {"in": 0.00, "out": 0.00},
}
#: Every request's token counts, appended as one JSON object per line. This is
#: the only record of what a pass over the corpus costs: the provider's console
#: gives a total per day, which cannot say which stage spent it.
LEDGER = pathlib.Path(__file__).resolve().parent / "work" / "usage.jsonl"
#: qwen3 is a reasoning model and `<think>` is billed as output, at twice the
#: rate of the page that prompted it, before being thrown away by `read_json`.
#: Groq takes an effort setting; left unset the default stands, because what
#: reasoning is worth here is a measurement nobody has made yet.
EFFORT = os.environ.get("SEED_VISION_EFFORT")

PROVIDER = os.environ.get("SEED_VISION", "groq").lower()
if PROVIDER not in PROVIDERS:
    raise SystemExit(f"SEED_VISION={PROVIDER!r}; expected one of {sorted(PROVIDERS)}")

URL = PROVIDERS[PROVIDER]["url"]
DEFAULT_MODEL = os.environ.get("SEED_VISION_MODEL") or PROVIDERS[PROVIDER]["model"]
#: What a reasoning model puts in front of its answer.
THINK = re.compile(r"<think>.*?</think>\s*", re.S)
#: Models fence JSON even when asked not to.
FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def api_key(provider: str = "") -> str:
    """A provider's key, from backend/.env; the current one unless named.

    Read from there rather than taken as a parameter: for Groq it is the same
    key the app itself uses, and a second copy is a second thing to rotate.

    Naming one matters because not every caller is reading a page.
    `trim_audio.py` posts to Groq's transcription endpoint whatever is reading
    the pages, and took the current provider's key -- so the moment the pages
    moved to Gemini it sent a Gemini key to Groq and was told, accurately and
    uselessly, "Invalid API Key"."""
    name = PROVIDERS[provider or PROVIDER]["env"]
    env = pathlib.Path(__file__).resolve().parent.parent / "backend" / ".env"
    for line in env.read_text().splitlines():
        if line.startswith(f"{name}="):
            value = line.split("=", 1)[1].strip()
            if value:
                return value
    raise SystemExit(f"{name} is not set in backend/.env (SEED_VISION={PROVIDER})")


#: The free tier allows 7000 input tokens a minute and a page image at 170 dpi
#: costs about 3400 of them, so two pages is already the budget. The error says
#: how long to wait, which is better than any interval we would pick.
WAIT = re.compile(r"try again in ([\d.]+)s")
MAX_ATTEMPTS = 5


def ask(prompt: str, images: list[pathlib.Path], *, model: str = DEFAULT_MODEL,
        max_tokens: int = 4000, temperature: float = 0.0) -> str:
    """One question about one or more page images. Returns the reply text.

    Waits and retries on a rate limit rather than failing: a batch that dies
    two thirds of the way through a book is worse than one that takes longer."""
    content: list[dict] = [{"type": "text", "text": prompt}]
    for path in images:
        data = base64.b64encode(path.read_bytes()).decode()
        mime = "image/jpeg" if path.suffix == ".jpg" else "image/png"
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{data}"}})

    body = {"model": model, "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
            **({"reasoning_effort": EFFORT} if EFFORT else {})}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        reply = _post(body)
        if not isinstance(reply, dict):
            # An endpoint that answers with a JSON array -- an error payload,
            # usually. Said plainly here rather than as an AttributeError on
            # the next line, which names neither the provider nor the page.
            raise SystemExit(f"{PROVIDER} answered with a "
                             f"{type(reply).__name__}: {json.dumps(reply)[:300]}")
        error = reply.get("error", {})
        if error.get("code") != "rate_limit_exceeded":
            break
        seconds = float(m.group(1)) + 1 if (m := WAIT.search(error.get("message", ""))) else 20.0
        print(f"  rate limited, waiting {seconds:.0f}s "
              f"(attempt {attempt}/{MAX_ATTEMPTS})", file=sys.stderr)
        time.sleep(seconds)
    record(reply.get("usage") or {}, model, len(images))
    if "choices" not in reply:
        raise SystemExit(f"API said: {json.dumps(reply)[:400]}")
    return reply["choices"][0]["message"]["content"]


def record(usage: dict, model: str, images: int) -> None:
    """Append one request's token counts to the ledger.

    Written from `sys.argv` rather than passed down through nine callers: what
    is wanted is which program spent it, and that is exactly what argv says.
    Never raises -- a ledger that can stop a batch is worse than no ledger."""
    if not usage:
        return
    price = PRICES.get(PROVIDER, {"in": 0.0, "out": 0.0})
    got, made = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a") as fh:
            json.dump({
                "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "by": pathlib.Path(sys.argv[0]).stem,
                "for": sys.argv[1] if len(sys.argv) > 1 else None,
                "provider": PROVIDER, "model": model, "images": images,
                "in": got, "out": made,
                "usd": round(got / 1e6 * price["in"] + made / 1e6 * price["out"], 6),
            }, fh)
            fh.write("\n")
    except OSError:
        pass


def _post(body: dict) -> dict:
    """One request. Split out so the retry above reads as a retry."""
    # The payload carries base64 pages and is far past a comfortable argv.
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(body, fh)
        payload = fh.name
    try:
        out = subprocess.run(
            ["curl", "-sS", "-X", "POST", URL,
             "-H", f"Authorization: Bearer {api_key()}",
             "-H", "Content-Type: application/json",
             "--data-binary", f"@{payload}"],
            capture_output=True, text=True, timeout=300)
    finally:
        pathlib.Path(payload).unlink(missing_ok=True)

    if out.returncode != 0:
        raise SystemExit(f"curl failed: {out.stderr[:300]}")
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        raise SystemExit(f"not JSON from the API: {out.stdout[:300]}")


def ask_json(prompt: str, images: list[pathlib.Path], **kwargs) -> dict:
    """`ask`, with the reply parsed as JSON.

    Strips a reasoning block and a code fence before parsing, because both
    arrive whatever the prompt says and neither is worth a retry."""
    text = FENCE.sub("", THINK.sub("", ask(prompt, images, **kwargs)).strip()).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        # The model wrote prose around the object often enough to be worth one
        # rescue attempt before giving up on the page.
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise SystemExit(f"reply was not JSON ({exc}):\n{text[:600]}")


#: How many images one request may carry. A COUNT, not a size limit.
MAX_IMAGES = PROVIDERS[PROVIDER]["images"]


def render(pdf: pathlib.Path, pages: list[int], out_dir: pathlib.Path,
           dpi: int = 170, jpeg: bool = False) -> list[pathlib.Path]:
    """Page images for the model, by ZERO-BASED pdf index.

    Not by the number printed on the page: Cambridge 11's printed page 10 is
    index 7, and assuming otherwise reads Section 2's questions as Section 1's.
    Whatever knows the offset passes indices in."""
    import pymupdf

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with pymupdf.open(pdf) as doc:
        for index in pages:
            pixmap = doc[index].get_pixmap(dpi=dpi)
            if jpeg:
                # These pages are photographs of paper, which is the one thing
                # PNG is bad at: the same page is 458 KB as PNG and 216 KB as
                # JPEG at 110 dpi. Half the bytes is a page and a half more per
                # request, or the same pages read larger.
                path = out_dir / f"page{index:03d}.jpg"
                path.write_bytes(pixmap.tobytes("jpeg", jpg_quality=80))
            else:
                path = out_dir / f"page{index:03d}.png"
                pixmap.save(path)
            paths.append(path)
    return paths
