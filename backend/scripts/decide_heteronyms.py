"""Decide how each sense of a heteronym is pronounced, and write it down.

A heteronym (`record`, `lead`, `close`, `wound` ...) has more than one
pronunciation, and which one is right follows the sense. This script asks a
model once per lemma, appends the answers to the replayable log
``app/data/tts/heteronym_decisions.jsonl`` (commit it), and writes the result
onto ``lexeme_senses.pronunciation``. See :mod:`app.services.heteronym_decisions`
for the design: why the log is keyed by lemma + part of speech + synset (or
definition) and never by a database id, and what a sense with no decision
yet does at serving time.

Run from ``backend/``. ``--confirm-db`` must name the database ``DATABASE_URL``
points at -- the script refuses otherwise (this worktree has no ``.env`` of its
own, and the default URL is the dev ``app``)::

    # ask the model for every heteronym sense the log cannot answer; READS the
    # lexicon, writes only the log file. GEMINI_API_KEY in the environment.
    uv run python -m scripts.decide_heteronyms decide --confirm-db app

    # write lexeme_senses.pronunciation from the log (no model, no network).
    # Run it on a database after migrating it -- dev, then production.
    uv run python -m scripts.decide_heteronyms apply --confirm-db app

``decide --dry-run`` prints what it would ask and spends nothing. ``--limit N``
decides at most N lemmas (a pilot). Re-running ``decide`` with nothing new asks
nothing.
"""

import argparse
import asyncio
import logging
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.database import async_session_factory
from app.services import heteronym_decisions as hd
from app.services import lexicon_enrich as le


async def _decide(args: argparse.Namespace) -> None:
    log = hd.DecisionLog(args.decisions)
    async with async_session_factory() as session:
        items = await hd.heteronym_senses(session)
    lemmas = {row.lemma.lower() for row in items}
    print(f"{len(items)} heteronym sense(s) over {len(lemmas)} lemma(s); "
          f"{len(log.decisions)} decision(s) on file ({args.decisions})")
    if args.dry_run:
        todo = [r for r in items if not log.get(r.lemma, r.pos, r.synset, r.definition)]
        print(f"would ask about {len(todo)} sense(s) over "
              f"{len({r.lemma.lower() for r in todo})} lemma(s)")
        return
    usage = le.UsageLog()
    gemini = le.Gemini(usage)
    try:
        report = await hd.decide(gemini, log, items, model=args.model,
                                 concurrency=args.concurrency, limit=args.limit)
    finally:
        await gemini.aclose()
    print(f"asked about {report.lemmas} lemma(s): replayed {report.replayed}, "
          f"decided {report.decided}, undecided {len(report.undecided)}")
    for line in report.undecided:
        print(f"  undecided: {line}")
    cost = usage.total_cost()
    print(f"model cost: ${cost:.4f}  "
          f"({sum(u.requests for u in usage.by_model.values())} request(s), "
          f"{sum(u.failures for u in usage.by_model.values())} failure(s))")


async def _apply(args: argparse.Namespace) -> None:
    log = hd.DecisionLog(args.decisions)
    async with async_session_factory() as session:
        report = await hd.apply(session, log)
    print(f"{report.heteronym_senses} heteronym sense(s): wrote {report.written}, "
          f"already right {report.unchanged}, no decision {len(report.undecided)}, "
          f"stale {len(report.stale)}")
    for label in report.undecided:
        print(f"  no decision (falls back to misaki's own at serving time): {label}")
    for label in report.stale:
        print(f"  stale (not a current candidate, not written): {label}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("decide", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--confirm-db", required=True,
                       help="the database name DATABASE_URL points at")
        p.add_argument("--decisions", type=Path, default=hd.DEFAULT_LOG,
                       help=f"the decisions log (default: {hd.DEFAULT_LOG})")
        if name == "decide":
            p.add_argument("--model", default=hd.DEFAULT_MODEL)
            p.add_argument("--concurrency", type=int, default=6)
            p.add_argument("--limit", type=int)
            p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    database = make_url(settings.database_url).database
    if args.confirm_db != database:
        parser.error(f"DATABASE_URL points at {database!r}, not {args.confirm_db!r}")
    print(f"database: {database}")
    asyncio.run(_decide(args) if args.command == "decide" else _apply(args))


if __name__ == "__main__":
    main()
