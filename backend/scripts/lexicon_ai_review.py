"""AI-assisted review of flagged lexicon senses -- the command line of
`app.services.lexicon_ai_review` (read its docstring for the rules).

Run from ``backend/``::

    # 1. hand a reviewer its work (read only; files go to the PRIVATE dir)
    uv run python -m scripts.lexicon_ai_review export --sample 100 --seed 1 --tag pilot
    uv run python -m scripts.lexicon_ai_review export --exclude-file \\
        app/data/private/review/pilot_001.jsonl
    uv run python -m scripts.lexicon_ai_review export --reason pos_mismatch

    # 2. check, then apply, what it decided (dry run unless --confirm-db)
    uv run python -m scripts.lexicon_ai_review apply --decisions d.jsonl
    uv run python -m scripts.lexicon_ai_review apply --decisions d.jsonl --confirm-db app

    # 3. where things stand; take decisions back
    uv run python -m scripts.lexicon_ai_review status [--list OUTCOME]
    uv run python -m scripts.lexicon_ai_review undo --all --confirm-db app
    uv run python -m scripts.lexicon_ai_review undo --ids <uuid> ... --confirm-db app

Exports hold DICTIONARY TEXT and decision reports name senses: both live ONLY
in ``app/data/private/review/`` (gitignored; the repository is public). The
decision format and the reviewer's instructions are ``REVIEW_RUBRIC.md``, which
``export`` writes there.

``apply`` and ``undo`` write only with ``--confirm-db NAME``, and refuse unless
NAME is the database ``DATABASE_URL`` points at; each is ONE transaction.
``export``, ``status`` and the dry runs read only (the connection itself is
``READ ONLY``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from sqlalchemy import text

from app.core.database import async_session_factory
from app.services import lexicon_ai_review as air
from app.services.lexicon_cald import readonly_connection


def database_name() -> str:
    from sqlalchemy.engine import make_url

    from app.core.config import settings

    return make_url(settings.database_url).database or ""


def _guard(confirm_db: str | None) -> str:
    database = database_name()
    if confirm_db and confirm_db != database:
        raise SystemExit(f"--confirm-db {confirm_db!r} is not the database DATABASE_URL points at "
                         f"({database!r}); nothing written")
    return database


async def cmd_export(args: argparse.Namespace) -> None:
    exclude = air.parse_exclude_file(args.exclude_file) if args.exclude_file else None
    async with readonly_connection() as conn:
        manifest = await air.export(
            conn, args.out, database=database_name(), reason=args.reason, sample=args.sample,
            seed=args.seed, exclude=exclude, batch_size=args.batch_size, tag=args.tag)
    print(f"database {manifest['database']!r}: {manifest['senses']} senses "
          f"({manifest['flagged_available']} flagged, {manifest['filters']['excluded']} excluded) "
          f"in {len(manifest['batches'])} batch file(s) -> {args.out}")
    for reason, n in manifest["by_primary_reason"].items():
        print(f"  {reason:<20}{n:>6}")
    for batch in manifest["batches"]:
        print(f"  {batch['file']}  {batch['senses']}")


def print_results(results: list[air.Result]) -> None:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.outcome] = counts.get(result.outcome, 0) + 1
        if result.outcome in ("rejected", "skipped"):
            print(f"  {result.outcome}: {result.sense_id} {result.lemma} -- {result.detail}")
    print("  " + ", ".join(f"{n} {outcome}" for outcome, n in sorted(counts.items())))
    by_action: dict[str, int] = {}
    for result in results:
        if result.outcome in ("applied", "would apply", "undone", "would undo"):
            by_action[result.action] = by_action.get(result.action, 0) + 1
    if by_action:
        print("  by action: " + ", ".join(f"{n} {a}" for a, n in sorted(by_action.items())))


def write_report(out: Path, name: str, results: list[air.Result]) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    path.write_text("\n".join(json.dumps(r.__dict__, ensure_ascii=False) for r in results) + "\n",
                    encoding="utf-8")
    return path


async def cmd_apply(args: argparse.Namespace) -> None:
    database = _guard(args.confirm_db)
    raw = air.read_decisions(args.decisions)
    run_id = uuid.uuid4().hex[:12]
    print(f"database {database!r}: {'APPLY' if args.confirm_db else 'dry run (read only)'}; "
          f"{len(raw)} decisions from {args.decisions.name}")
    async with async_session_factory() as session:
        if not args.confirm_db:
            await session.exec(text("SET TRANSACTION READ ONLY"))
        try:
            results = await air.process(
                session, raw, write=bool(args.confirm_db),
                allow_material_fixes=args.allow_material_fixes, run_id=run_id)
            if args.confirm_db:
                await session.commit()
            else:
                await session.rollback()
        except BaseException:
            await session.rollback()
            raise
    print_results(results)
    if args.confirm_db:
        report = write_report(args.out, f"apply_{run_id}.jsonl", results)
        print(f"run {run_id}; report {report}")
    else:
        print("nothing written; pass --confirm-db <name> to write")


async def cmd_undo(args: argparse.Namespace) -> None:
    database = _guard(args.confirm_db)
    if not args.all and not args.ids:
        raise SystemExit("undo needs --all or --ids")
    ids = None if args.all else [uuid.UUID(i) for i in args.ids]
    print(f"database {database!r}: {'UNDO' if args.confirm_db else 'dry run (read only)'}")
    async with async_session_factory() as session:
        if not args.confirm_db:
            await session.exec(text("SET TRANSACTION READ ONLY"))
        try:
            results = await air.undo(session, sense_ids=ids, write=bool(args.confirm_db))
            if args.confirm_db:
                await session.commit()
            else:
                await session.rollback()
        except BaseException:
            await session.rollback()
            raise
    print_results(results)
    if not args.confirm_db:
        print("nothing written; pass --confirm-db <name> to write")


async def cmd_status(args: argparse.Namespace) -> None:
    async with async_session_factory() as session:
        await session.exec(text("SET TRANSACTION READ ONLY"))
        table = await air.status(session)
        print(f"database {database_name()!r}")
        print(air.format_status(table))
        if args.list:
            for line in await air.list_outcome(session, args.list):
                print(line)
        await session.rollback()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("export", help="write review batches (read only)")
    ex.add_argument("--reason", choices=air.REVIEW_REASONS)
    ex.add_argument("--sample", type=int, help="N senses, stratified over the reasons")
    ex.add_argument("--seed", type=int, default=1)
    ex.add_argument("--exclude-file", type=Path,
                    help="skip every sense whose uuid appears in this file (a batch, a "
                         "decisions file, a list of ids)")
    ex.add_argument("--batch-size", type=int, default=150)
    ex.add_argument("--tag", default="batch", help="file prefix: <tag>_001.jsonl, <tag>_manifest.json")
    ex.add_argument("--out", type=Path, default=air.REVIEW_DIR)

    ap = sub.add_parser("apply", help="validate and apply decisions (dry run by default)")
    ap.add_argument("--decisions", type=Path, required=True)
    ap.add_argument("--confirm-db", metavar="NAME")
    ap.add_argument("--allow-material-fixes", action="store_true",
                    help="accept material_fixes (relink_sense / relink_lexeme); off by default")
    ap.add_argument("--out", type=Path, default=air.REVIEW_DIR)

    un = sub.add_parser("undo", help="revert Claude-review decisions, exactly")
    which = un.add_mutually_exclusive_group()
    which.add_argument("--all", action="store_true")
    which.add_argument("--ids", nargs="+", metavar="SENSE_ID")
    un.add_argument("--confirm-db", metavar="NAME")

    st = sub.add_parser("status", help="counts by reason x outcome")
    st.add_argument("--list", choices=air.OUTCOMES, metavar="OUTCOME",
                    help="also list the senses with this outcome (" + ", ".join(air.OUTCOMES) + ")")

    args = parser.parse_args()
    handler = {"export": cmd_export, "apply": cmd_apply, "undo": cmd_undo,
               "status": cmd_status}[args.cmd]
    asyncio.run(handler(args))


if __name__ == "__main__":
    main()
