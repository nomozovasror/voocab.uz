"""The one place that knows how to show a page to a model.

Two providers, both speaking OpenAI's chat format with images inlined as data
URLs, chosen with `SEED_VISION=groq|nvidia`:

* **groq** -- `qwen/qwen3.8-27b`. Fast, and metered: this pipeline's cost is
  dominated not by one pass over the corpus but by how many passes it takes to
  get a stage right, which is not knowable in advance. Four passes and a
  page-location scan came to $10.
* **nvidia** -- build.nvidia.com's catalogue, free through the developer
  programme and rate-limited near 40 requests a minute instead. That trade is
  the right way round for work that is mostly iteration.

Being one file is the point. Nine other scripts read pages through this and
none of them knows which provider answered.

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
    "nvidia": {
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "env": "NVIDIA_API_KEY",
        "model": "nvidia/llama-3.1-nemotron-nano-vl-8b-v1",
        "images": 4,
    },
}
PROVIDER = os.environ.get("SEED_VISION", "groq").lower()
if PROVIDER not in PROVIDERS:
    raise SystemExit(f"SEED_VISION={PROVIDER!r}; expected one of {sorted(PROVIDERS)}")

URL = PROVIDERS[PROVIDER]["url"]
DEFAULT_MODEL = os.environ.get("SEED_VISION_MODEL") or PROVIDERS[PROVIDER]["model"]
#: What a reasoning model puts in front of its answer.
THINK = re.compile(r"<think>.*?</think>\s*", re.S)
#: Models fence JSON even when asked not to.
FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def api_key() -> str:
    """The current provider's key, from backend/.env.

    Read from there rather than taken as a parameter: for Groq it is the same
    key the app itself uses, and a second copy is a second thing to rotate."""
    name = PROVIDERS[PROVIDER]["env"]
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
            "messages": [{"role": "user", "content": content}]}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        reply = _post(body)
        error = reply.get("error", {})
        if error.get("code") != "rate_limit_exceeded":
            break
        seconds = float(m.group(1)) + 1 if (m := WAIT.search(error.get("message", ""))) else 20.0
        print(f"  rate limited, waiting {seconds:.0f}s "
              f"(attempt {attempt}/{MAX_ATTEMPTS})", file=sys.stderr)
        time.sleep(seconds)
    if "choices" not in reply:
        raise SystemExit(f"API said: {json.dumps(reply)[:400]}")
    return reply["choices"][0]["message"]["content"]


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
