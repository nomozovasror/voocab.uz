"""Take sections through every stage, in order, and record how far each got.

    seed/.venv/bin/python seed/run_pipeline.py cam11-t1-s1
    seed/.venv/bin/python seed/run_pipeline.py --book 11 --test 1
    seed/.venv/bin/python seed/run_pipeline.py --book 11            # all sixteen

Each stage stays a program you can run on its own -- this calls them, it does
not absorb them. A stage that fails is recorded against that section and the
run moves to the next one: one misread page should cost one section, not a
book.

`import` runs under the BACKEND venv, not this one. The two halves of the
pipeline have deliberately separate environments -- extraction needs torch and
no database, the import needs the database and no torch -- and the only place
that has to know both is here.

Nothing is redone. A stage already marked done is skipped unless --force, so a
run that stops halfway can simply be run again.
"""

import argparse
import json
import pathlib
import sqlite3
import subprocess
import sys
import time

SEED = pathlib.Path(__file__).resolve().parent
REPO = SEED.parent
PYTHON = SEED / ".venv" / "bin" / "python"
BACKEND = REPO / "backend"

#: Stages whose failure is a loss of quality rather than of content. An
#: untrimmed material still publishes -- publish_blockers() asks for questions
#: and answers and audio, not for the disc announcement to be gone -- so
#: stopping the run there would hold back a finished paper over 26 seconds of
#: preamble that can be cut later.
OPTIONAL = {"trim", "picture"}

#: The order they depend on each other in, which is not the order they are
#: interesting in. `align` has to come before `questions` because
#: build_questions.py resolves each answer's replay span out of aligned.json --
#: run the other way round it reports every margin marker as having no turn,
#: and the first two sections only passed because an earlier run had left an
#: alignment on disk.
#:
#: `picture` comes after `questions` and not before, because build_questions.py
#: rewrites questions.json and would erase the picture it had just been given.
#:
#: `questions` covers the answer key as well: both come off the same pages in
#: one reading and are checked against each other.
STAGES = ("audioscript", "align", "questions", "picture", "trim", "import")


#: A stage can be more than one program. `questions` reads the pages and then
#: builds what the importer wants: reading without building leaves
#: questions.src.json on disk and a material with no questions in the database,
#: which is exactly what happened the first time this ran.
def commands(stage: str, section_id: str, owner: str) -> list[list[str]]:
    if stage == "questions":
        steps = []
        # Reading the pages again costs money and cannot improve on a reading
        # that is already on disk. Rebuilding from it is free, and is what a
        # re-run after a corrected transcript actually needs.
        if not (SEED / "work" / section_id / "questions.src.json").exists():
            steps.append([str(PYTHON), str(SEED / "read_questions.py"), section_id])
        steps.append([str(PYTHON), str(SEED / "build_questions.py"), section_id])
        return steps
    return [command(stage, section_id, owner)]


def command(stage: str, section_id: str, owner: str) -> list[str]:
    match stage:
        case "audioscript":
            return [str(PYTHON), str(SEED / "read_audioscript.py"), section_id]
        case "questions":
            return [str(PYTHON), str(SEED / "read_questions.py"), section_id]
        case "align":
            return [str(PYTHON), str(SEED / "align.py"), section_id]
        case "picture":
            return [str(PYTHON), str(SEED / "extract_image.py"), section_id]
        case "trim":
            return [str(PYTHON), str(SEED / "trim_audio.py"), section_id]
        case "import":
            return ["uv", "run", "--no-sync", "python", "-m", "scripts.import_section",
                    section_id, "--owner", owner]
    raise ValueError(stage)


def run(stage: str, section_id: str, owner: str) -> tuple[bool, str]:
    """One stage. Returns whether it worked and the last of what it said."""
    env = {"PYTHONPATH": str(SEED), "PYTORCH_ENABLE_MPS_FALLBACK": "1",
           "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin", "HOME": str(pathlib.Path.home())}
    cwd = BACKEND if stage == "import" else REPO
    said = ""
    for argv in commands(stage, section_id, owner):
        out = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)
        lines = (out.stdout + out.stderr).strip().splitlines()
        said = lines[-1][:150] if lines else ""
        if out.returncode != 0:
            return False, said
    return True, said


def record(conn, section_id: str, stage: str, ok: bool, note: str) -> None:
    conn.execute(
        """UPDATE stage SET status = ?, attempts = attempts + 1, error = ?,
               updated_at = datetime('now')
           WHERE section_id = ? AND name = ?""",
        ("done" if ok else "failed", None if ok else note[:400], section_id, stage))
    # `questions` and `answer_key` are one reading of one pair of pages.
    if stage == "questions":
        conn.execute(
            """UPDATE stage SET status = ?, attempts = attempts + 1,
                   updated_at = datetime('now')
               WHERE section_id = ? AND name = 'answer_key'""",
            ("done" if ok else "failed", section_id))
    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sections", nargs="*", help="section ids; or use --book/--test")
    ap.add_argument("--book", type=int)
    ap.add_argument("--test", type=int)
    ap.add_argument("--owner", default="d2b9f563-9669-4fb3-b6dc-51536c8baac1")
    ap.add_argument("--force", action="store_true", help="redo stages already done")
    ap.add_argument("--stop-after", help="last stage to run")
    args = ap.parse_args()

    conn = sqlite3.connect(SEED / "catalogue.db")
    conn.row_factory = sqlite3.Row

    if args.sections:
        ids = args.sections
    elif args.book:
        where = "book_number = ?" + (" AND test_no = ?" if args.test else "")
        params = (args.book, args.test) if args.test else (args.book,)
        ids = [r["id"] for r in conn.execute(
            f"SELECT id FROM section WHERE {where} ORDER BY test_no, section_no", params)]
    else:
        raise SystemExit("name some sections, or pass --book")

    stages = STAGES[:STAGES.index(args.stop_after) + 1] if args.stop_after else STAGES
    started = time.perf_counter()
    finished, stalled = 0, []

    for section_id in ids:
        done = {r["name"] for r in conn.execute(
            "SELECT name FROM stage WHERE section_id = ? AND status = 'done'",
            (section_id,))}
        blocked = {r["name"] for r in conn.execute(
            "SELECT name FROM stage WHERE section_id = ? AND status = 'blocked'",
            (section_id,))}
        print(f"\n{section_id}")
        for stage in stages:
            if stage in blocked:
                print(f"  {stage:<12} blocked")
                break
            if stage in done and not args.force:
                print(f"  {stage:<12} done already")
                continue
            begin = time.perf_counter()
            ok, note = run(stage, section_id, args.owner)
            record(conn, section_id, stage, ok, note)
            mark = "ok  " if ok else "FAIL"
            print(f"  {stage:<12} {mark} {time.perf_counter() - begin:>5.0f}s  {note}")
            if not ok and stage in OPTIONAL:
                print(f"  {stage:<12} skipped, carrying on: the material can "
                      "publish without it")
                continue
            if not ok:
                stalled.append((section_id, stage, note))
                break
        else:
            finished += 1

    conn.close()
    print(f"\n{finished}/{len(ids)} sections through every stage in "
          f"{(time.perf_counter() - started) / 60:.1f} min")
    for section_id, stage, note in stalled:
        print(f"  stopped at {stage}: {section_id} -- {note}")
    return 0 if not stalled else 1


if __name__ == "__main__":
    sys.exit(main())
