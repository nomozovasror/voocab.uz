"""What the reading has cost, and which stage spent it.

    seed/.venv/bin/python seed/spend.py
    seed/.venv/bin/python seed/spend.py --by for      # per section
    seed/.venv/bin/python seed/spend.py --since 2026-09-08

`vision.py` appends one line per request to `work/usage.jsonl`. This adds them
up. The provider's own console gives a total per day, which is the one cut that
cannot answer the question worth asking: a pass over the corpus is four stages
and several re-reads, and knowing the total tells you nothing about which of
them to change.

The number to watch is not the total but **requests per page**. A page costs
what it costs; a page read eleven times costs eleven times that, and every
figure in this file that surprised anyone was a multiplier, never a rate.
"""

import argparse
import collections
import json
import pathlib
import sys

LEDGER = pathlib.Path(__file__).resolve().parent / "work" / "usage.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--by", default="by", choices=("by", "for", "model", "at"),
                    help="group by the program, the section, the model, or the day")
    ap.add_argument("--since", help="ignore anything before this date")
    args = ap.parse_args()

    if not LEDGER.exists():
        print(f"no ledger yet at {LEDGER}", file=sys.stderr)
        return 1

    totals: dict[str, dict[str, float]] = collections.defaultdict(
        lambda: {"calls": 0, "images": 0, "in": 0, "out": 0, "usd": 0.0})
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if args.since and row.get("at", "") < args.since:
            continue
        # Grouping by day means the date, not the second it happened.
        key = row.get(args.by) or "?"
        if args.by == "at":
            key = key[:10]
        into = totals[key]
        into["calls"] += 1
        into["images"] += row.get("images", 0)
        into["in"] += row.get("in", 0)
        into["out"] += row.get("out", 0)
        into["usd"] += row.get("usd", 0.0)

    if not totals:
        print("nothing recorded in that range", file=sys.stderr)
        return 1

    width = max(len(k) for k in totals)
    print(f"{args.by:<{width}}  {'calls':>6} {'images':>7} {'in':>12} {'out':>10} "
          f"{'out/call':>9} {'$':>8}")
    for key, t in sorted(totals.items(), key=lambda kv: -kv[1]["usd"]):
        # Output per call is the reasoning tally: it is what a thinking model
        # adds to a page read, and the one column here that a setting changes.
        print(f"{key:<{width}}  {t['calls']:>6} {t['images']:>7} {t['in']:>12,} "
              f"{t['out']:>10,} {t['out'] / t['calls']:>9,.0f} {t['usd']:>8.2f}")

    every = {k: sum(t[k] for t in totals.values()) for k in ("calls", "images", "in", "out")}
    spent = sum(t["usd"] for t in totals.values())
    print(f"\n{every['calls']} requests over {every['images']} page images "
          f"({every['images'] / max(every['calls'], 1):.1f} an ask), "
          f"{every['in']:,} in and {every['out']:,} out, ${spent:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
