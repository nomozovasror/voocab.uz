"""``seed_tts doctor`` -- the preflight to run before a real seed run.

Prints a PASS / FAIL / WARN / SKIP line per check, each FAIL with a one-line fix,
and exits non-zero if anything FAILed. It answers, in order: is this the right
Python and platform; can it reach the database, is that database migrated to
the repo's head, and what would each step do; is the media folder there,
writable, and holding the clip files verification reads; does torch see the
GPU; does Kokoro load and speak both voices on it; does misaki's espeak
fallback work on this OS (a word outside the lexicon must get phonemes, or it
would be spoken as a silent gap); does faster-whisper load on CUDA with the
chosen model and hear a word.

Every check is wrapped: one that crashes is a FAIL line, not a dead doctor. The
espeak probe runs in a SUBPROCESS because on macOS the ``espeakng-loader``
wheel ``exit(1)``s the interpreter -- a hard exit there is a FAIL line, and the
checks that need Kokoro in-process are skipped (never attempted on darwin).
``python -m scripts.seed_tts_doctor probe-g2p`` is that subprocess's entry.
"""

import argparse
import asyncio
import json
import logging
import platform
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, text
from sqlmodel import select

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.audio_render import AudioRender, RenderKind, RenderStatus
from app.models.word_clip import ClipStatus, WordClip
from app.services import accents, audio_pcm, tts, word_clips
from app.services.storage import get_storage

BACKEND = Path(__file__).resolve().parents[1]
#: A word no lexicon holds: misaki must fall back to espeak for it.
OOV_WORD = "algorithmication"

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"


@dataclass
class Check:
    status: str
    name: str
    detail: str = ""
    #: One line on what to do; shown under a FAIL (and a WARN).
    fix: str = ""


Probe = Callable[[], Awaitable[list[Check]]]


def _fmt(check: Check) -> str:
    line = f"[{check.status}] {check.name}" + (f": {check.detail}" if check.detail else "")
    if check.fix and check.status in (FAIL, WARN):
        line += f"\n       fix: {check.fix}"
    return line


# --- 1. Python and platform --------------------------------------------------------


def check_python() -> list[Check]:
    version = ".".join(map(str, sys.version_info[:3]))
    detail = f"Python {version} on {platform.platform()} ({platform.machine()})"
    if sys.version_info < (3, 14):
        return [Check(FAIL, "Python / platform", detail, "install Python 3.14 (`uv python install 3.14`) and re-run `uv sync`")]
    if sys.maxsize <= 2**32:
        return [Check(FAIL, "Python / platform", detail, "use a 64-bit Python")]
    return [Check(PASS, "Python / platform", detail)]


# --- 2. Database -------------------------------------------------------------------


def alembic_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    return str(ScriptDirectory.from_config(config).get_current_head())


async def _existing_keys(keys: list[str]) -> set[str]:
    found: set[str] = set()
    async with async_session_factory() as session:
        for offset in range(0, len(keys), 5000):
            chunk = keys[offset : offset + 5000]
            found.update((await session.exec(select(AudioRender.key).where(AudioRender.key.in_(chunk)))).all())
    return found


async def check_database() -> list[Check]:
    out: list[Check] = []
    where = settings.database_url.rsplit("@", 1)[-1]
    try:
        async with async_session_factory() as session:
            await asyncio.wait_for(session.execute(text("select 1")), timeout=15)
            current = (await session.execute(text("select version_num from alembic_version"))).scalars().all()
    except Exception as exc:  # noqa: BLE001
        return [Check(
            FAIL, "Database reachable", f"{where}: {type(exc).__name__}: {exc}",
            "check DATABASE_URL in backend/.env (and that the tunnel/port to the dev database is up)",
        )]
    out.append(Check(PASS, "Database reachable", where))
    head = alembic_head()
    if list(current) == [head]:
        out.append(Check(PASS, "Database migrated", f"at head {head}"))
    else:
        out.append(Check(
            FAIL, "Database migrated", f"database at {list(current) or 'nothing'}, code expects {head}",
            "run `uv run alembic upgrade head` against that database -- or update this checkout to the commit the database was migrated with",
        ))
        return out  # the counts below would be reading a schema that may not match

    # What each step would do.
    from scripts import seed_tts

    try:
        async with async_session_factory() as session:
            candidates = await word_clips.count_candidates()
            clip_counts = dict(
                (await session.exec(select(WordClip.status, func.count()).group_by(WordClip.status))).all()
            )
            cut_forms = int(
                (await session.exec(
                    select(func.count(func.distinct(WordClip.form))).where(WordClip.status == ClipStatus.CUT)
                )).one()
            )
            render_counts = {
                (kind, status): n
                for kind, status, n in (
                    await session.exec(
                        select(AudioRender.kind, AudioRender.status, func.count()).group_by(
                            AudioRender.kind, AudioRender.status
                        )
                    )
                ).all()
            }
            every = list(accents.ACCENTS)
            words = await seed_tts.word_specs(session, saved_only=False, limit=None, accents_=every)
            definitions = await seed_tts.definition_specs(session, saved_only=False, limit=None, accents_=every)
        new_words = len(words) - len(await _existing_keys([s.key for s in words]))
        new_defs = len(definitions) - len(await _existing_keys([s.key for s in definitions]))
    except Exception as exc:  # noqa: BLE001
        out.append(Check(WARN, "What each step would do", f"could not count: {type(exc).__name__}: {exc}"))
        return out

    def renders(kind: str, status: str) -> int:
        return int(render_counts.get((kind, status), 0))

    out.append(Check(PASS, "clips", f"{candidates} candidate clip(s) left to cut (the dev worker cuts them too); "
                     f"by status: {clip_counts or 'none yet'}"))
    out.append(Check(PASS, "verify-clips", f"{clip_counts.get(ClipStatus.CUT, 0)} cut clip(s) over {cut_forms} form(s) to examine"))
    out.append(Check(PASS, "words --accent both", f"{new_words} new render(s) to queue, "
                     f"{renders(RenderKind.WORD, RenderStatus.PENDING)} already pending, "
                     f"{renders(RenderKind.WORD, RenderStatus.READY)} ready, "
                     f"{renders(RenderKind.WORD, RenderStatus.FAILED)} failed"))
    out.append(Check(PASS, "definitions --accent both", f"{new_defs} new render(s) to queue, "
                     f"{renders(RenderKind.DEFINITION, RenderStatus.PENDING)} already pending, "
                     f"{renders(RenderKind.DEFINITION, RenderStatus.READY)} ready, "
                     f"{renders(RenderKind.DEFINITION, RenderStatus.FAILED)} failed"))
    return out


# --- 3. Media root -----------------------------------------------------------------


async def check_media() -> list[Check]:
    storage = get_storage()
    out: list[Check] = []
    if settings.use_r2:
        out.append(Check(WARN, "Storage backend", f"R2 bucket {settings.r2_bucket} is configured -- files will go THERE, not to MEDIA_ROOT",
                         "remove the R2_* / AWS_* settings from backend/.env for a local run"))
        return out
    root = Path(settings.media_root)
    key = f"doctor-probe/{uuid.uuid4().hex}.txt"
    body = b"seed_tts doctor " + uuid.uuid4().hex.encode()
    try:
        await storage.put(key, body, "text/plain")
        back = await storage.get(key)
        (root / key).unlink()
        try:
            (root / key).parent.rmdir()
        except OSError:
            pass
        if back != body:
            raise OSError("read back different bytes than were written")
    except Exception as exc:  # noqa: BLE001
        return [Check(FAIL, "MEDIA_ROOT writable", f"{root.resolve()}: {type(exc).__name__}: {exc}",
                      "set MEDIA_ROOT in backend/.env to an existing writable folder")]
    out.append(Check(PASS, "MEDIA_ROOT writable", f"{root.resolve()} (wrote, read and deleted a probe file)"))

    samples: list[tuple[str, str]] = []
    async with async_session_factory() as session:
        for row in (await session.exec(
            select(WordClip).where(WordClip.status.in_((ClipStatus.CUT, ClipStatus.VERIFIED)),
                                   WordClip.storage_key.is_not(None)).order_by(func.random()).limit(5)
        )).all():
            samples.append(("clip", row.storage_key))
        for row in (await session.exec(
            select(AudioRender).where(AudioRender.status == RenderStatus.READY,
                                      AudioRender.storage_key.is_not(None)).order_by(func.random()).limit(3)
        )).all():
            samples.append(("render", row.storage_key))
    clips = [k for kind, k in samples if kind == "clip"]
    if not clips:
        out.append(Check(WARN, "Clip files present", "no cut clips in the database yet",
                         "let the dev worker finish cutting (or run `clips`) before `verify-clips`"))
        return out
    problems: list[str] = []
    for kind, key in samples:
        try:
            data = await storage.get(key)
            if kind == "clip":
                audio_pcm.decode_range(data)  # PyAV can read it
            elif not data:
                raise OSError("empty file")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{key}: {type(exc).__name__}: {exc}")
    if problems:
        out.append(Check(FAIL, "Clip files present", f"{len(problems)} of {len(samples)} sampled file(s) unusable, e.g. {problems[0]}",
                         "copy backend/media/clips (and tts/, renders/) from the Mac into MEDIA_ROOT; `check-files --what clips` lists every missing one"))
    else:
        out.append(Check(PASS, "Clip files present", f"{len(samples)} sampled file(s) found and readable"))
    return out


# --- 4-7. torch, Kokoro, espeak, faster-whisper --------------------------------------


def check_torch(device: str) -> tuple[list[Check], bool]:
    try:
        import torch
    except ImportError as exc:
        return [Check(FAIL, "torch + CUDA", str(exc), "`uv sync --extra seed --extra tts-gpu`")], False
    detail = f"torch {torch.__version__}"
    if not torch.cuda.is_available():
        built = torch.version.cuda
        fix = ("this is a CPU build of torch: `uv sync --extra seed --extra tts-gpu` (not the `tts` extra)"
               if built is None else "update the NVIDIA driver (`nvidia-smi` must work; CUDA 12.8 needs driver 570+)")
        status = PASS if device == "cpu" else FAIL
        return [Check(status, "torch + CUDA", f"{detail}, CUDA not available (built for CUDA {built})", fix)], device == "cpu"
    name = torch.cuda.get_device_name(0)
    return [Check(PASS, "torch + CUDA", f"{detail}, CUDA {torch.version.cuda}, device: {name}")], True


def probe_g2p_subprocess() -> list[Check]:
    """misaki's G2P with its espeak fallback, per accent, in a child process."""
    try:
        done = subprocess.run(
            [sys.executable, "-m", "scripts.seed_tts_doctor", "probe-g2p"],
            cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        )
    except subprocess.TimeoutExpired:
        return [Check(FAIL, "misaki espeak fallback", "probe timed out after 300 s", "re-run; the first start loads spaCy")]
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-1:] or [""]
        fix = ("misaki is not installed: `uv sync --extra seed --extra tts-gpu`"
               if "ModuleNotFoundError" in tail[0] else
               "espeakng-loader does not work on this OS/install: on Windows reinstall (`uv sync --reinstall-package espeakng-loader`); it cannot work on macOS")
        return [Check(FAIL, "misaki espeak fallback", f"the probe process died (exit {done.returncode}): {tail[0][:200]}", fix)]
    try:
        report = json.loads(done.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return [Check(FAIL, "misaki espeak fallback", f"unreadable probe output: {done.stdout[-200:]!r}", "re-run `doctor`")]
    out = []
    for accent, info in report.items():
        if info.get("error"):
            out.append(Check(FAIL, f"misaki espeak fallback ({accent})", info["error"], "see the error; espeak must load for words outside the lexicon"))
        elif not info["phonemes"] or info["unknown"]:
            out.append(Check(FAIL, f"misaki espeak fallback ({accent})", f"{OOV_WORD!r} got no phonemes", "espeak fallback is not working; do not run `words`"))
        else:
            out.append(Check(PASS, f"misaki espeak fallback ({accent})", f"{OOV_WORD!r} -> {info['phonemes']}"))
    return out


def check_kokoro(device: str) -> tuple[list[Check], tts.KokoroSynth | None]:
    if sys.platform == "darwin":
        return [Check(SKIP, "Kokoro on the GPU", "Kokoro cannot run on macOS (espeakng-loader kills the process); run this on the Windows machine")], None
    if not tts.kokoro_available():
        return [Check(FAIL, "Kokoro loads", "the kokoro package is not installed", "`uv sync --extra seed --extra tts-gpu`")], None
    synth = tts.KokoroSynth(device=device)
    out: list[Check] = []
    first = True
    for accent, entry in accents.ACCENTS.items():
        try:
            t0 = time.perf_counter()
            audio = synth("hello", entry.voice)
            cold = time.perf_counter() - t0
            t1 = time.perf_counter()
            audio = synth("information", entry.voice)
            warm = time.perf_counter() - t1
            # Out-of-lexicon word through the real guard: must speak, not raise.
            oov = synth(OOV_WORD, entry.voice)
        except Exception as exc:  # noqa: BLE001
            hint = ("a voice/model download failed: check the internet connection (first run fetches ~330 MB from huggingface.co)"
                    if isinstance(exc, tts.InfrastructureError) else
                    "see the error" if not isinstance(exc, tts.UnknownPronunciation) else
                    "misaki's espeak fallback is not working here")
            out.append(Check(FAIL, f"Kokoro {accent} ({entry.voice})", f"{type(exc).__name__}: {exc}", hint))
            continue
        level = audio_pcm.rms_dbfs(audio)
        seconds = audio_pcm.duration_ms(audio) / 1000
        problem = None if seconds > 0.2 and level > -60 else "audio is empty or silent"
        where = ""
        try:
            model = next(iter(synth._pipelines.values())).model
            where = f", on {model.device}"
        except Exception:  # noqa: BLE001
            pass
        note = f" (first call incl. load {cold:.1f}s)" if first else ""
        first = False
        detail = (f"'information' {audio_pcm.duration_ms(audio) / 1000:.2f}s of audio in {warm * 1000:.0f} ms warm{where}{note}; "
                  f"out-of-lexicon word spoken ({audio_pcm.duration_ms(oov) / 1000:.2f}s)")
        if problem:
            out.append(Check(FAIL, f"Kokoro {accent} ({entry.voice})", f"{detail}; {problem}", "re-install torch/kokoro"))
        elif device == "cuda" and "cuda" not in where:
            out.append(Check(FAIL, f"Kokoro {accent} ({entry.voice})", detail, "the model did not land on the GPU"))
        else:
            out.append(Check(PASS, f"Kokoro {accent} ({entry.voice})", detail))
    return out, synth


def check_whisper(model_name: str, device: str, synth: tts.KokoroSynth | None) -> list[Check]:
    from scripts import seed_tts

    try:
        t0 = time.perf_counter()
        transcribe = seed_tts.make_transcriber(model_name, device)
        load = time.perf_counter() - t0
    except Exception as exc:  # noqa: BLE001
        return [Check(FAIL, f"faster-whisper {model_name} on {device}", f"{type(exc).__name__}: {exc}", _whisper_fix(exc))]
    speech = False
    try:
        if synth is not None:
            samples = synth("hello", accents.voice_for("british"))
            speech = True
        else:
            samples = audio_pcm.concat(audio_pcm.silence(300))
        data = audio_pcm.encode_m4a(samples)
        t1 = time.perf_counter()
        heard = transcribe(data)
        took = time.perf_counter() - t1
    except Exception as exc:  # noqa: BLE001
        return [Check(FAIL, f"faster-whisper {model_name} on {device}", f"loaded in {load:.1f}s but transcribing failed: {type(exc).__name__}: {exc}", _whisper_fix(exc))]
    if speech and not word_clips.heard_contains("hello", heard):
        return [Check(FAIL, f"faster-whisper {model_name} on {device}", f"heard {heard!r} for a generated 'hello'", "the model or the decode path is wrong; try `--model small.en`")]
    note = f"heard {heard!r}" if speech else "ran on silence (no Kokoro to make speech)"
    return [Check(PASS, f"faster-whisper {model_name} on {device}", f"loaded in {load:.1f}s, transcribed in {took:.2f}s, {note}")]


def _whisper_fix(exc: Exception) -> str:
    message = str(exc).lower()
    if any(word in message for word in ("cublas", "cudnn", ".dll", "libcuda", "cuda")):
        return ("CUDA libraries for ctranslate2 not found: `uv sync --extra tts-gpu` brings cuBLAS 12 + cuDNN 9 inside torch\\lib "
                "(this script puts them on the path); else install CUDA 12 + cuDNN 9, or `uv pip install nvidia-cublas-cu12 nvidia-cudnn-cu12`")
    if "connection" in message or "hub" in message or "offline" in message:
        return "the model downloads on first use (large-v3 ~3 GB): check the internet connection, or use `--model small.en`"
    return "see the error; `--model small.en` is a smaller try"


# --- run ---------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> int:
    """Run every check; print; return the exit status."""
    device = args.device or "cuda"
    logging.getLogger("alembic").setLevel(logging.WARNING)  # its "setup plugin" chatter
    checks: list[Check] = []

    def show(items: list[Check]) -> None:
        for check in items:
            print(_fmt(check), flush=True)
        checks.extend(items)

    async def guarded(name: str, fn: Callable[[], Awaitable[list[Check]]]) -> None:
        try:
            show(await fn())
        except Exception as exc:  # noqa: BLE001 - a crashing check is a FAIL line
            show([Check(FAIL, name, f"check crashed: {type(exc).__name__}: {exc}")])

    def sync(name: str, fn: Callable[[], list[Check]]) -> Awaitable[None]:
        async def call() -> list[Check]:
            return await asyncio.to_thread(fn)
        return guarded(name, call)

    print(f"seed_tts doctor -- device {device}, whisper model {args.model}\n", flush=True)
    await guarded("Python / platform", lambda: _as_async(check_python))
    await guarded("Database", check_database)
    await guarded("MEDIA_ROOT", check_media)

    torch_ok = False
    try:
        items, torch_ok = await asyncio.to_thread(check_torch, device)
        show(items)
    except Exception as exc:  # noqa: BLE001
        show([Check(FAIL, "torch + CUDA", f"check crashed: {type(exc).__name__}: {exc}")])

    await sync("misaki espeak fallback", probe_g2p_subprocess)
    synth: tts.KokoroSynth | None = None
    if torch_ok:
        try:
            items, synth = await asyncio.to_thread(check_kokoro, device)
            show(items)
        except Exception as exc:  # noqa: BLE001
            show([Check(FAIL, "Kokoro", f"check crashed: {type(exc).__name__}: {exc}")])
    else:
        show([Check(SKIP, "Kokoro on the GPU", "skipped: torch has no usable device (see above)")])
    if sys.platform == "darwin" and device == "cuda":
        show([Check(SKIP, "faster-whisper on CUDA", "no CUDA on macOS")])
    else:
        await sync("faster-whisper", lambda: check_whisper(args.model, device, synth))

    failed = [c for c in checks if c.status == FAIL]
    warned = [c for c in checks if c.status == WARN]
    print(f"\n{len(checks) - len(failed) - len(warned)} ok, {len(warned)} warning(s), {len(failed)} FAILED", flush=True)
    return 1 if failed else 0


async def _as_async(fn: Callable[[], list[Check]]) -> list[Check]:
    return fn()


# --- the subprocess probe ----------------------------------------------------------


def _probe_g2p() -> None:
    """Build misaki's G2P exactly as ``KPipeline`` does (espeak fallback, both
    accents) and phonemize an out-of-lexicon word. Prints one JSON line. Runs in
    its own process: a hard exit from espeak is the parent's FAIL line."""
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    logging.disable(logging.CRITICAL)
    from misaki import en, espeak

    report: dict[str, dict] = {}
    for accent, entry in accents.ACCENTS.items():
        british = entry.lang_code == "b"
        try:
            g2p = en.G2P(trf=False, british=british, fallback=espeak.EspeakFallback(british=british), unk=tts.UNKNOWN_MARK)
            _ps, tokens = g2p(OOV_WORD)
            report[accent] = {
                "phonemes": "".join(t.phonemes or "" for t in tokens),
                "unknown": tts.unknown_words(tokens),
            }
        except Exception as exc:  # noqa: BLE001
            report[accent] = {"error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["probe-g2p"]:
        _probe_g2p()
    else:
        raise SystemExit("this module is run through `python -m scripts.seed_tts doctor`")
