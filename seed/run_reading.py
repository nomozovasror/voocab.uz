"""Take reading passages through every stage, in order, and say how far each got.

    seed/.venv/bin/python seed/run_reading.py cam11-t1-p2 --owner <uuid>
    seed/.venv/bin/python seed/run_reading.py --book 11 --owner <uuid>
    seed/.venv/bin/python seed/run_reading.py --owner <uuid>        # all 191
    seed/.venv/bin/python seed/run_reading.py --report

Its own runner rather than an arm of `run_pipeline.py`, and the reason is
what `run_pipeline` is: a loop over the `stage` table, which holds one row
per SECTION per stage. A reading passage is a sibling of a section rather
than one of them -- the two have no foreign key between them and no shared
id -- so a reading arm there would have to either invent stage rows for
things that are not sections or carry a second bookkeeping scheme beside the
first. This carries no bookkeeping at all: what a passage has done is what is
on disk beside it, which is also what makes the run resumable for free.

Seven stages, and three of listening's are simply absent -- there is no
recording, so nothing to align and nothing to trim:

    text       read_passages.py            passage.json
    questions  read_passage_questions.py   questions.src.json
    build      build_questions.py          questions.json
    vocab      read_vocabulary.py          vocabulary.json
    evidence   read_evidence.py            evidence.json
    picture    extract_image.py            image-group<N>.png
    import     scripts.import_passage      a Material, private

`build` comes before `picture` because the picture is cut for the groups the
build named, and `picture` before `import` because a labelling group without
its picture is a group `publish_blockers` refuses. `import` runs under the
BACKEND venv, like its listening twin: extraction needs no database and the
import needs nothing else.

`vocab` needs only `passage.json` and could run second. It runs fourth
because it spends money: a passage whose questions could not be read is a
passage that will not be imported, and glossing its eighty words first would
be paying for a material nobody is going to sit.

`evidence` is listening's replay span with the clock taken out of it -- where
in the PASSAGE each answer is -- and it is the same bargain: one request a
passage, paid once, for the thing the review page is actually for. It must
come after `build` because it is asked about the built questions and their
answer key, and it is optional for the same reason `vocab` is: a paper whose
evidence could not be placed is still a paper worth sitting, and holding it
back would be protesting about the help by withholding the work.

Nothing is redone. A stage whose output is already on disk is skipped unless
--force, so a run that stops halfway is simply run again.
"""

import argparse
import json
import os
import pathlib
import sqlite3
import subprocess
import sys

SEED = pathlib.Path(__file__).resolve().parent
REPO = SEED.parent
BACKEND = REPO / "backend"
PYTHON = SEED / ".venv" / "bin" / "python"
WORK = SEED / "work"

#: The order they depend on each other in. Not the order they are interesting
#: in: `build` is the one that catches a misread page, and it can only run
#: after both readings of it exist.
STAGES = ("text", "questions", "build", "vocab", "evidence", "picture",
          "import")

#: A stage whose failure is a loss of quality rather than of content. A
#: passage with no labelling group has no picture to cut and says so by
#: exiting zero with nothing done; one whose picture could not be found still
#: has twelve other questions worth practising, and stopping the run there
#: would hold all of them back.
#:
#: `vocab` and `evidence` are optional on the same reading. A passage with no
#: glosses and no marked evidence is a passage a learner can still sit; it is
#: the help around it that is missing, and holding the paper back to protest
#: about the help would be a strange way to serve them.
OPTIONAL = {"picture", "vocab", "evidence"}


def output(stage: str, passage_id: str) -> pathlib.Path | None:
    """What this stage leaves behind, or None where it leaves nothing.

    `picture` leaves a file only for a passage that has a labelling group,
    and `import` leaves a row in another database entirely -- both are asked
    every run, which costs nothing for the first and is what makes a
    re-import pick up a corrected passage for the second.
    """
    work = WORK / passage_id
    return {
        "text": work / "passage.json",
        "questions": work / "questions.src.json",
        "build": work / "questions.json",
        "vocab": work / "vocabulary.json",
        "evidence": work / "evidence.json",
    }.get(stage)


def command(stage: str, passage_id: str, owner: str) -> list[str]:
    match stage:
        case "text":
            return [str(PYTHON), str(SEED / "read_passages.py"), passage_id]
        case "questions":
            return [str(PYTHON), str(SEED / "read_passage_questions.py"), passage_id]
        case "build":
            return [str(PYTHON), str(SEED / "build_questions.py"), passage_id]
        case "vocab":
            return [str(PYTHON), str(SEED / "read_vocabulary.py"), passage_id]
        case "evidence":
            return [str(PYTHON), str(SEED / "read_evidence.py"), passage_id]
        case "picture":
            return [str(PYTHON), str(SEED / "extract_image.py"), passage_id]
        case "import":
            return ["uv", "run", "--no-sync", "python", "-m",
                    "scripts.import_passage", passage_id, "--owner", owner]
    raise ValueError(stage)


def run(stage: str, passage_id: str, owner: str) -> tuple[bool, str]:
    """One stage. Returns whether it worked and the last of what it said."""
    # Built rather than inherited, so a stage runs the same way from any
    # shell -- and the three knobs `vision.py` reads are passed through by
    # name, because building the environment silently swallowed SEED_VISION
    # once and a whole batch ran on the provider the runner was not told to
    # use.
    env = {"PYTHONPATH": str(SEED),
           "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
           "HOME": str(pathlib.Path.home())}
    env.update({name: os.environ[name] for name in
                ("SEED_VISION", "SEED_VISION_MODEL", "SEED_VISION_EFFORT")
                if name in os.environ})
    out = subprocess.run(command(stage, passage_id, owner),
                         cwd=BACKEND if stage == "import" else REPO,
                         env=env, capture_output=True, text=True)
    lines = (out.stdout + out.stderr).strip().splitlines()
    return out.returncode == 0, (lines[-1][:150] if lines else "")


def passages(conn: sqlite3.Connection, book: int | None) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM passage"
        + (" WHERE book_number = ?" if book else "")
        + " ORDER BY book_number, test_no, passage_no",
        (book,) if book else ()).fetchall()
    return [row[0] for row in rows]


def report(conn: sqlite3.Connection) -> None:
    """How far the corpus has got, one column per stage."""
    ids = passages(conn, None)
    counts = {stage: 0 for stage in STAGES}
    for passage_id in ids:
        for stage in STAGES:
            path = output(stage, passage_id)
            if path is not None and path.exists():
                counts[stage] += 1
    print(f"{len(ids)} located passages\n")
    for stage in STAGES:
        if output(stage, "x") is None:
            print(f"  {stage:<10} — (leaves nothing on disk to count)")
            continue
        left = len(ids) - counts[stage]
        print(f"  {stage:<10} {counts[stage]:>4} done"
              f"{f', {left} left' if left else ''}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("passage_id", nargs="?")
    ap.add_argument("--book", type=int)
    ap.add_argument("--owner", help="who the imported materials belong to")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--force", help="stages to redo, comma-separated, or '*'")
    ap.add_argument("--stop-after", choices=STAGES,
                    help="the last stage to run, for a pass that is not "
                         "ready to reach the database")
    args = ap.parse_args()

    conn = sqlite3.connect(SEED / "catalogue.db")
    if args.report:
        report(conn)
        return 0

    stages = (STAGES[:STAGES.index(args.stop_after) + 1] if args.stop_after
              else STAGES)
    if "import" in stages and not args.owner:
        print("--owner is required to import; use --stop-after build to "
              "stop short of the database", file=sys.stderr)
        return 2
    forced = (set(STAGES) if args.force == "*"
              else {name.strip() for name in (args.force or "").split(",") if name.strip()})
    if unknown := forced - set(STAGES):
        print(f"not a stage: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    ids = [args.passage_id] if args.passage_id else passages(conn, args.book)
    conn.close()

    failed: list[tuple[str, str]] = []
    for passage_id in ids:
        for stage in stages:
            path = output(stage, passage_id)
            if path is not None and path.exists() and stage not in forced:
                continue
            ok, said = run(stage, passage_id, args.owner or "")
            mark = "ok " if ok else ("note" if stage in OPTIONAL else "FAIL")
            print(f"{passage_id:<16} {stage:<10} {mark}  {said}")
            if not ok and stage not in OPTIONAL:
                failed.append((passage_id, stage))
                break

    if failed:
        print(f"\n{len(failed)} passage(s) stopped:")
        for passage_id, stage in failed:
            print(f"  {passage_id:<16} at {stage}")
        print("Run the same command again to pick them up.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
