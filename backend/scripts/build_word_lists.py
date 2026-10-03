"""Populate the five word lists (`app.services.word_lists_build`).

Run from ``backend/``. ``--confirm-db`` must name the database
``DATABASE_URL`` points at -- the script refuses otherwise, because this
worktree has no ``.env`` of its own and the default URL is the dev ``app``::

    # dry run on a copy, paying for the model once and keeping every answer
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/app_tmp_wordlists_copy \\
    GEMINI_API_KEY=... \\
    uv run python -m scripts.build_word_lists --confirm-db app_tmp_wordlists_copy \\
        --usage-log word_list_usage.jsonl

    # the real run: same log replayed, so the same senses and no model cost
    # for anything the dry run already decided (new questions only, if any)
    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/app \\
    GEMINI_API_KEY=... \\
    uv run python -m scripts.build_word_lists --confirm-db app \\
        --usage-log word_list_usage.jsonl

    # replay only, never call a model (entries the log cannot answer stay
    # unresolved and are listed)
    ... --confirm-db app --no-model

    # numbers only, no writes
    ... --confirm-db app --summary-only

Re-running is safe: resolved entries are skipped, ranks are recomputed
deterministically, and a second run with nothing new to decide makes no
model call. ``--reselect business`` asks a list's senses again from scratch
(ignoring the log for that list). ``--limit N`` resolves at most N
unresolved entries per domain list -- a pilot.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.database import async_session_factory
from app.services import lexicon_enrich as le
from app.services import word_lists_build as wb

#: Kept in the repo: replaying it is how the lists are rebuilt without the model.
DEFAULT_DECISIONS = Path(__file__).resolve().parent.parent / "app" / "data" / "word_lists" / "decisions.jsonl"


def _print_summary(summary: dict) -> None:
    print("\nLists:")
    for key, stat in summary["lists"].items():
        extra = ""
        if "non_rank1" in stat:
            extra = (f"  non-rank-1 sense {stat['non_rank1']}"
                     f" (of which on a lexeme the lemma did not have: "
                     f"{stat['non_rank1_new_lexeme']})")
        print(f"  {key:9} entries {stat['entries']:5}  resolved {stat['resolved']:5}"
              f"  rank_source {stat['rank_source']}{extra}")
        print(f"            cefr {dict(sorted(stat['cefr'].items()))}")
        print(f"            first {', '.join(stat['first'])}")
    for key in ("core", "medical"):
        stat = summary["lists"].get(key)
        if not stat:
            continue
        if "changed_vs_old_rule" in stat:
            print(f"\n{key}: {stat['changed_vs_old_rule']} entries' sense differs from the old "
                  f"rule (rank 1 of the primary lexeme)")
        print(f"\n{key}: first 20")
        for row in stat["first20"]:
            print(f"  {row['rank']:3} {row['lemma']:22} [{row['rank_source']}] {row['sense'][:90]}")
    if summary.get("core_changed_examples"):
        print("\nCore entries whose sense changed:")
        for ex in summary["core_changed_examples"]:
            print(f"  [core #{ex['rank']}] {ex['lemma']}: {ex['now'][:90]}")
            print(f"      old rule: {ex['old_rule'][:90]}")
    if summary["non_rank1_examples"]:
        print("\nDomain entries whose sense is not the lemma's global rank-1:")
        for ex in summary["non_rank1_examples"]:
            print(f"  [{ex['list']} #{ex['rank']}] {ex['lemma']}: {ex['chosen']}")
            print(f"      global rank-1: {ex['global_rank1']}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--confirm-db", required=True,
                        help="the database name DATABASE_URL points at")
    parser.add_argument("--lists", default=",".join(wb.ALL_LISTS))
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS,
                        help="JSONL log of model answers: read to replay, appended to "
                             f"(default: {DEFAULT_DECISIONS}, see its README)")
    parser.add_argument("--usage-log", type=Path, help="append token usage/cost as JSON")
    parser.add_argument("--summary-json", type=Path, help="write the summary as JSON")
    parser.add_argument("--model", default=wb.DEFAULT_CHOICE_MODEL,
                        help="the domain sense chooser")
    parser.add_argument("--reselect", default="", help="lists to choose again, comma-separated")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--unit", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--no-model", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("app.services.word_lists_build").setLevel(logging.INFO)

    database = make_url(settings.database_url).database
    if args.confirm_db != database:
        parser.error(f"DATABASE_URL points at {database!r}, not {args.confirm_db!r}")
    lists = tuple(k.strip() for k in args.lists.split(",") if k.strip())
    reselect = tuple(k.strip() for k in args.reselect.split(",") if k.strip())
    unknown = set(lists + reselect) - set(wb.ALL_LISTS)
    if unknown:
        parser.error(f"unknown list(s): {sorted(unknown)}")
    print(f"database: {database}   lists: {', '.join(lists)}")

    oewn = le.load_oewn()
    if not args.summary_only:
        log = wb.DecisionLog(args.decisions)
        print(f"decisions log: {args.decisions or '(none)'} -- "
              f"{len(log.choices)} choices, {len(log.senses)} enriched senses on file")
        usage = le.UsageLog()
        gemini = None if args.no_model else le.Gemini(usage)
        options = wb.BuildOptions(
            lists=lists, model=args.model, unit=args.unit, concurrency=args.concurrency,
            reselect=reselect, limit=args.limit, no_model=args.no_model,
        )
        started = time.monotonic()
        try:
            report, rank_sources = await wb.build(async_session_factory, gemini, options,
                                                  log, oewn)
        finally:
            if gemini is not None:
                await gemini.aclose()
        elapsed = time.monotonic() - started

        print(f"\nDone in {elapsed:.0f}s. Choices asked {report.asked_choices}, "
              f"replayed {report.replayed_choices}; senses enriched from the log "
              f"{report.replayed_senses}.")
        print(f"New senses: {dict(report.new_senses)} (by list {dict(report.new_by_list)}); "
              f"new lexemes: {report.new_lexemes}")
        if report.core_how:
            print(f"Core decided by: {dict(report.core_how)}")
        for key in lists:
            excluded = dict(report.excluded.get(key, {}))
            print(f"  {key:9} source {report.source_size.get(key, 0):5}  excluded {excluded}"
                  f"  unresolved {len(report.unresolved.get(key, []))}"
                  f"  rank_source {dict(rank_sources.get(key, {}))}")
            skipped = [x for x in report.excluded_lemmas.get(key, []) if "skip:" in x
                       or "proper_noun" in x]
            if skipped:
                print(f"            names/fragments: {', '.join(skipped[:40])}")
            if report.unresolved.get(key):
                print(f"            unresolved: {', '.join(report.unresolved[key][:40])}")
        if report.failures:
            print(f"\nFailures ({len(report.failures)}):")
            for failure in report.failures[:40]:
                print(f"  {failure}")
        if gemini is not None:
            print("\nUsage by model:")
            for model, u in usage.by_model.items():
                print(f"  {model:24} {u.requests:5} req ({u.failures} failed)  "
                      f"in {u.input_tokens:9,}  out {u.output_tokens:8,}  ${u.cost(model):.4f}")
            print("Usage by step:")
            for step, u in sorted(usage.by_step.items()):
                print(f"  {step:36} {u.requests:5} req  in {u.input_tokens:9,}  "
                      f"out {u.output_tokens:8,}  ${u.cost(step.split(':', 1)[1]):.4f}")
            print(f"Total cost: ${usage.total_cost():.4f}")
            if args.usage_log:
                with args.usage_log.open("a") as fh:
                    fh.write(json.dumps({
                        "job": "build_word_lists", "database": database,
                        "seconds": round(elapsed, 1), "asked": report.asked_choices,
                        "new_senses": dict(report.new_senses),
                        "new_lexemes": report.new_lexemes,
                        "new_by_list": dict(report.new_by_list),
                        "core_how": dict(report.core_how),
                        "by_model": {m: vars(u) | {"cost": round(u.cost(m), 6)}
                                     for m, u in usage.by_model.items()},
                        "by_step": {s: vars(u) for s, u in usage.by_step.items()},
                        "total_cost": round(usage.total_cost(), 6),
                    }) + "\n")

    summary = await wb.summarise(async_session_factory, oewn, lists,
                                 global_before=None if args.summary_only
                                 else report.global_before)
    _print_summary(summary)
    if args.summary_json:
        args.summary_json.write_text(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
