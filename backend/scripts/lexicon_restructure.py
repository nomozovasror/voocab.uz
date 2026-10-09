"""Structural clean-up of the lexicon from a reviewed decisions file -- the
command line of `app.services.lexicon_restructure` (read its docstring for the
rules and the op list).

Run from ``backend/``::

    # 1. fill the Uzbek of add_sense / create_phrase lines that have none
    #    (writes <file>.translated.jsonl; stops cleanly on the spend cap or a
    #    Gemini 402/quota failure, leaving the rest empty)
    uv run python -m scripts.lexicon_restructure translate \\
        --decisions app/data/private/restructure/batch_001.decisions.jsonl --max-usd 2

    # 2. check, then apply (a dry run executes every op for real in one
    #    transaction and rolls it back; --confirm-db writes, one transaction per op)
    uv run python -m scripts.lexicon_restructure apply --decisions F.jsonl
    uv run python -m scripts.lexicon_restructure apply --decisions F.jsonl --confirm-db app

    # re-order every lexeme's senses easiest first (read only; writes the file)
    uv run python -m scripts.lexicon_restructure plan-rerank --out F.decisions.jsonl

    # 3. runs so far; take one back, exactly
    uv run python -m scripts.lexicon_restructure status
    uv run python -m scripts.lexicon_restructure undo --run <id> --confirm-db app

Decision files and reports hold lexicon data and live ONLY in
``app/data/private/restructure/`` (gitignored; the repository is public). A run
writes ``run_<id>.jsonl`` there before each commit: that file is the way back.
``apply`` and ``undo`` write only with ``--confirm-db NAME``, which must be the
database ``DATABASE_URL`` points at.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from pathlib import Path

from app.core.database import async_session_factory
from app.services import lexicon_restructure as lr


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


def print_results(results: list[lr.Result], *, verbose: bool) -> None:
    for r in results:
        if verbose or r.outcome in ("rejected", "error", "skipped"):
            print(f"  #{r.n} {r.op}: {r.outcome} -- {r.detail}")
    table = lr.summarise(results)
    print("  summary (op: outcomes)")
    for op, counts in sorted(table.items()):
        print(f"    {op:<20}" + ", ".join(f"{n} {o}" for o, n in sorted(counts.items())))
    total: dict[str, int] = {}
    for counts in table.values():
        for outcome, n in counts.items():
            total[outcome] = total.get(outcome, 0) + n
    print("  total: " + ", ".join(f"{n} {o}" for o, n in sorted(total.items())))


async def cmd_apply(args: argparse.Namespace) -> None:
    database = _guard(args.confirm_db)
    raw = lr.read_decisions(args.decisions)
    run_id = uuid.uuid4().hex[:12]
    write = bool(args.confirm_db)
    print(f"database {database!r}: {'APPLY' if write else 'dry run (executed, then rolled back)'}; "
          f"{len(raw)} lines from {args.decisions.name}")
    async with async_session_factory() as session:
        try:
            results = await lr.process(session, raw, write=write, run_id=run_id, out_dir=args.out,
                                       database=database, decisions=args.decisions.name)
            if write:
                await session.commit()
            else:
                await session.rollback()
        except BaseException:
            await session.rollback()
            raise
    print_results(results, verbose=args.verbose or not write)
    if write:
        print(f"run {run_id}; report {lr.report_path(args.out, run_id)}")
        print(f"undo with: undo --run {run_id} --confirm-db {database}")
    else:
        print("nothing written; pass --confirm-db <name> to write")


async def cmd_undo(args: argparse.Namespace) -> None:
    database = _guard(args.confirm_db)
    write = bool(args.confirm_db)
    if not lr.RUN_ID.match(args.run):
        raise SystemExit("--run must be a 12-character hex run id")
    print(f"database {database!r}: {'UNDO' if write else 'dry run (checks only)'} run {args.run}")
    results = await lr.undo(async_session_factory, args.run, write=write, out_dir=args.out,
                            only=set(args.ops) if args.ops else None)
    print_results(results, verbose=True)
    if not write:
        print("nothing written; pass --confirm-db <name> to write")


async def cmd_status(args: argparse.Namespace) -> None:
    runs = lr.list_runs(args.out)
    print(f"database {database_name()!r}; {len(runs)} run(s) in {args.out}")
    for run in runs:
        print(f"  {run['run_id']}  {run['started_at'][:19]}  db={run['database']!r}  "
              f"{run['ops']} ops ({run['committed']} committed, {run['undone']} undone)  "
              f"rows {run['rows']}  from {run['decisions']}")
        for key, n in run["by_op"].items():
            print(f"      {key:<34}{n:>5}")


async def cmd_plan_rerank(args: argparse.Namespace) -> None:
    import json

    from sqlalchemy import text

    async with async_session_factory() as session:
        await session.exec(text("SET TRANSACTION READ ONLY"))
        lines, stats = await lr.plan_rerank(session)
        await session.rollback()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines),
                        encoding="utf-8")
    print(f"database {database_name()!r} (read only): {stats['lexemes']} lexemes, "
          f"{stats['changed']} need a rerank_senses line: {stats['reordered']} re-ordered "
          f"({stats['rank1_changed']} change their rank-1 sense), {stats['ranks_not_1_to_n']} with ranks "
          f"not 1..n, {stats['cefr_changed']} with a Lexeme.cefr to change; ngsl_conflict flags: "
          f"{stats['ngsl_stale']} lexemes (+{stats['ngsl_add']} / -{stats['ngsl_remove']})")
    for shift, n in sorted(stats["cefr_shift"].items(), key=lambda kv: -kv[1]):
        print(f"  {shift:<10}{n:>6}")
    print(f"written {args.out}")


async def cmd_translate(args: argparse.Namespace) -> None:
    from app.services import lexicon_enrich as le
    from scripts.lexicon_cleanup import print_usage

    usage = le.UsageLog()
    gemini = le.Gemini(usage)
    try:
        stats = await lr.translate_file(args.decisions, gemini, async_session_factory,
                                        max_usd=args.max_usd, chunk=args.chunk)
    finally:
        await gemini.aclose()
    print(f"{stats['to_translate']} line(s) to translate, {stats['translated']} translated "
          f"(judge: {dict(stats['verdicts'])}), {stats['invalid']} refused by the Uzbek rules, "
          f"{stats['skipped']} not translatable (bad definition / unknown lexeme)")
    print_usage(usage)
    print(f"written {stats['out']}")
    if stats["stopped"]:
        print(f"STOPPED: {stats['stopped']}")
    if stats["remaining"]:
        print(f"{stats['remaining']} line(s) still have no Uzbek -- fill them by hand or re-run "
              f"translate on the .translated file")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    ap = sub.add_parser("apply", help="validate and apply a decisions file (dry run by default)")
    ap.add_argument("--decisions", type=Path, required=True)
    ap.add_argument("--confirm-db", metavar="NAME")
    ap.add_argument("--out", type=Path, default=lr.RESTRUCTURE_DIR)
    ap.add_argument("-v", "--verbose", action="store_true", help="list every op (a dry run does)")

    un = sub.add_parser("undo", help="reverse a run, newest op first")
    un.add_argument("--run", required=True)
    un.add_argument("--ops", type=int, nargs="+", metavar="N", help="only these line numbers")
    un.add_argument("--confirm-db", metavar="NAME")
    un.add_argument("--out", type=Path, default=lr.RESTRUCTURE_DIR)

    st = sub.add_parser("status", help="runs and op counts")
    st.add_argument("--out", type=Path, default=lr.RESTRUCTURE_DIR)

    pr = sub.add_parser("plan-rerank", help="write rerank_senses lines for every lexeme the "
                                            "easiest-first rule would re-order (read only)")
    pr.add_argument("--out", type=Path, default=lr.RESTRUCTURE_DIR / "rerank.decisions.jsonl")

    tr = sub.add_parser("translate", help="fill meaning_uz of add_sense/create_phrase lines")
    tr.add_argument("--decisions", type=Path, required=True)
    tr.add_argument("--max-usd", type=float, default=2.0)
    tr.add_argument("--chunk", type=int, default=20)

    args = parser.parse_args()
    handler = {"apply": cmd_apply, "undo": cmd_undo, "status": cmd_status,
               "translate": cmd_translate, "plan-rerank": cmd_plan_rerank}[args.cmd]
    asyncio.run(handler(args))


if __name__ == "__main__":
    main()
