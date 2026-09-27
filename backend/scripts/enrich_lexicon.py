"""Lexicon P2: enrich lexemes with the model (see `app.services.lexicon_enrich`).

Run from ``backend/``::

    # pick a ~200-lexeme sample and write its ids (+ the "before" counts)
    uv run python -m scripts.enrich_lexicon --make-sample /path/sample.json
    # enrich just those
    uv run python -m scripts.enrich_lexicon --ids /path/sample.json
    # everything not yet enriched (resumes after a crash: done lexemes are
    # skipped via lexemes.enriched_at)
    uv run python -m scripts.enrich_lexicon --all
    # numbers + tables for a set of lexemes
    uv run python -m scripts.enrich_lexicon --report /path/sample.json

``--force`` re-enriches lexemes already done (idempotent in structure: senses
are reused by synset / by row overlap, never deleted-and-rebuilt).

Work is split into units of ``--unit`` lexemes; each unit asks the model
everything first and then writes all its lexemes in one transaction, so a
crash loses at most the units in flight. Token usage and cost are printed
per run and appended as JSON lines to ``--usage-log``.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import logging
import random
import sys
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import func, select as sa_select
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.lexicon import Lexeme, LexemeSense
from app.models.vocabulary import MaterialVocabulary
from app.services import lexicon_enrich as le

REPO_ROOT = Path(__file__).resolve().parents[2]
OEWN_PATH = REPO_ROOT / "seed" / "wordlists" / "oewn_senses.jsonl.gz"


def load_oewn() -> dict[tuple[str, str], list[dict]]:
    """(lemma, pos) -> senses in OEWN order. Two entries for one key
    (`adj` folds WordNet's `a` and `s`) are concatenated and re-ranked."""
    index: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with gzip.open(OEWN_PATH, "rt", encoding="utf-8") as fh:
        for line in fh:
            record = json.loads(line)
            index[(record["lemma"], record["pos"])].extend(record["senses"])
    out = {}
    for key, senses in index.items():
        seen, ranked = set(), []
        for sense in senses:
            if sense["synset"] in seen:
                continue
            seen.add(sense["synset"])
            ranked.append({"synset": sense["synset"], "rank": len(ranked) + 1,
                           "definition": sense["definition"]})
        out[key] = ranked
    return out


# --- Sample ------------------------------------------------------------------

NAMED = ("figure", "subject", "bank", "spring", "accumulate")


async def make_sample(path: Path, size: int) -> None:
    rng = random.Random(20260927)
    async with async_session_factory() as session:
        lexemes = (await session.exec(select(Lexeme))).all()
        sense_rows = (await session.exec(
            select(LexemeSense.lexeme_id, LexemeSense.review_reasons, LexemeSense.provisional)
        )).all()
        material_ids = set((await session.exec(
            sa_select(MaterialVocabulary.lexeme_id).distinct()
        )).scalars().all())
    senses_of = Counter(r[0] for r in sense_rows)
    reasons_of: dict = defaultdict(set)
    for lexeme_id, reasons, _ in sense_rows:
        reasons_of[lexeme_id].update(reasons)

    chosen: dict[uuid.UUID, str] = {}

    def take(pool, n, tag):
        pool = [lx for lx in pool if lx.id not in chosen]
        rng.shuffle(pool)
        for lx in pool[:n]:
            chosen[lx.id] = tag

    take([lx for lx in lexemes if lx.lemma in NAMED], 99, "named")
    many = sorted((lx for lx in lexemes if lx.frequency_source == "ngsl"
                   and lx.id in material_ids and senses_of[lx.id] >= 3),
                  key=lambda lx: -senses_of[lx.id])
    take(many[:120], 40, "ngsl-many-senses")
    take([lx for lx in lexemes if lx.is_phrase and lx.id in material_ids], 30, "phrase")
    list_only = [lx for lx in lexemes if lx.id not in material_ids]
    for source, n in (("bsl", 12), ("moel", 12), ("tsl", 6), ("ngsl", 5), ("nawl", 3)):
        take([lx for lx in list_only if lx.frequency_source == source], n, f"list-only-{source}")
    take([lx for lx in lexemes if "lemma_merge" in reasons_of[lx.id]], 25, "lemma-merge")
    take([lx for lx in lexemes if "ngsl_conflict" in reasons_of[lx.id]], 15, "ngsl-conflict")
    take([lx for lx in lexemes if lx.id in material_ids], size - len(chosen), "random")

    by_id = {lx.id: lx for lx in lexemes}
    payload = {
        "lexemes": [
            {"id": str(i), "lemma": by_id[i].lemma, "pos": by_id[i].pos, "tag": tag,
             "senses_before": senses_of[i]}
            for i, tag in chosen.items()
        ],
    }
    path.write_text(json.dumps(payload, indent=1))
    print(f"{len(chosen)} lexemes -> {path}: {dict(Counter(chosen.values()))}")
    print(f"senses before: {sum(senses_of[i] for i in chosen)}")


# --- Run ---------------------------------------------------------------------


async def run(ids: list[uuid.UUID], unit: int, concurrency: int, usage_log: Path | None) -> None:
    oewn = load_oewn()
    usage = le.UsageLog()
    gemini = le.Gemini(usage)
    units = [ids[i:i + unit] for i in range(0, len(ids), unit)]
    semaphore = asyncio.Semaphore(concurrency)
    done = failed = 0
    notes: Counter[str] = Counter()
    started = time.monotonic()

    async def one(chunk):
        nonlocal done, failed
        async with semaphore:
            try:
                works = await le.enrich(async_session_factory, gemini, chunk, oewn)
            except Exception:  # noqa: BLE001 - one unit's failure must not stop the run
                failed += len(chunk)
                import traceback
                traceback.print_exc()
                return
            done += len(chunk)
            for work in works:
                notes.update(work.note.split())
            elapsed = time.monotonic() - started
            print(f"  {done}/{len(ids)} lexemes, {elapsed:.0f}s, ${usage.total_cost():.4f}",
                  flush=True)

    try:
        await asyncio.gather(*(one(chunk) for chunk in units))
    finally:
        await gemini.aclose()
    elapsed = time.monotonic() - started
    print(f"\nDone {done}, failed {failed} lexemes in {elapsed:.0f}s")
    if notes:
        print(f"Per-lexeme notes: {dict(notes)}")
    print_usage(usage)
    if usage_log:
        with usage_log.open("a") as fh:
            fh.write(json.dumps({
                "lexemes": done, "failed": failed, "seconds": round(elapsed, 1),
                "by_model": {m: vars(u) | {"cost": round(u.cost(m), 6)}
                             for m, u in usage.by_model.items()},
                "by_step": {s: vars(u) for s, u in usage.by_step.items()},
            }) + "\n")


def print_usage(usage: le.UsageLog) -> None:
    print("\nUsage by model:")
    for model, u in usage.by_model.items():
        print(f"  {model:24} {u.requests:5} req ({u.failures} failed)  "
              f"in {u.input_tokens:9,}  out {u.output_tokens:8,}  ${u.cost(model):.4f}")
    print("Usage by step:")
    for step, u in sorted(usage.by_step.items()):
        print(f"  {step:36} {u.requests:5} req  in {u.input_tokens:9,}  out {u.output_tokens:8,}")
    print(f"Total cost: ${usage.total_cost():.4f}")


# --- Report ------------------------------------------------------------------


def _cell(text: object, width: int) -> str:
    text = " ".join(str(text or "").split()).replace("|", "/")
    return text if len(text) <= width else text[: width - 1] + "…"


async def report(sample: dict | None) -> None:
    """``sample`` None: the whole lexicon."""
    async with async_session_factory() as session:
        if sample is None:
            ids = list((await session.exec(sa_select(Lexeme.id))).scalars().all())
            before = 0
            orphans = (await session.exec(sa_select(func.count()).select_from(MaterialVocabulary)
                                          .where(MaterialVocabulary.lexeme_id.is_(None)))).one()
            print(f"material rows with no lexeme (live lookups, left for P3): {orphans[0]}")
        else:
            ids = [uuid.UUID(x["id"]) for x in sample["lexemes"]]
            before = sum(x["senses_before"] for x in sample["lexemes"])
        lexemes = {lx.id: lx for lx in (await session.exec(
            select(Lexeme).where(Lexeme.id.in_(ids)))).all()}
        senses = (await session.exec(
            select(LexemeSense).where(LexemeSense.lexeme_id.in_(ids)))).all()
        rows = (await session.exec(
            select(MaterialVocabulary.id, MaterialVocabulary.sense_id, MaterialVocabulary.lexeme_id)
            .where(MaterialVocabulary.lexeme_id.in_(ids)))).all()
    sense_by = {s.id: s for s in senses}
    enriched = sum(1 for lx in lexemes.values() if lx.enriched_at)
    print(f"Lexemes: {len(ids)} ({enriched} enriched)")
    print(f"Senses before (P1 provisional): {before}; after: {len(senses)} "
          f"({sum(s.provisional for s in senses)} still provisional)")
    print(f"  by source: {dict(Counter(s.source_id for s in senses))}")
    material_senses = {r.sense_id for r in rows}
    ms = [sense_by[i] for i in material_senses if i in sense_by]
    print(f"  material-linked senses: {len(ms)} "
          f"({sum(s.source_id == 'oewn' for s in ms)} OEWN-matched)")
    oewn_rows = sum(1 for r in rows if r.sense_id in sense_by and sense_by[r.sense_id].oewn_synset_id)
    print(f"OEWN match rate: {oewn_rows}/{len(rows)} material rows "
          f"({100 * oewn_rows / max(1, len(rows)):.1f}%) linked to an OEWN sense")
    oewn_idx = load_oewn()
    with_entry = [r for r in rows if (lexemes[r.lexeme_id].lemma, lexemes[r.lexeme_id].pos) in oewn_idx]
    matched_with_entry = sum(1 for r in with_entry
                             if r.sense_id in sense_by and sense_by[r.sense_id].oewn_synset_id)
    print(f"  among rows whose (lemma,pos) HAS an OEWN entry: {matched_with_entry}/{len(with_entry)} "
          f"({100 * matched_with_entry / max(1, len(with_entry)):.1f}%)")
    unlinked = sum(1 for r in rows if r.sense_id is None or r.sense_id not in sense_by)
    print(f"material rows without a live sense: {unlinked}")
    translated = sum(1 for s in senses if s.meaning_uz and not s.meaning_uz_material)
    copied = sum(1 for s in senses if s.meaning_uz_material and s.meaning_uz == s.meaning_uz_material)
    normalised = sum(1 for s in senses if s.meaning_uz_material and s.meaning_uz != s.meaning_uz_material)
    print(f"Uzbek: translated {translated}, copied verbatim {copied}, copied+normalised {normalised}")
    reasons = Counter(r for s in senses for r in s.review_reasons)
    print(f"needs_review: {sum(s.needs_review for s in senses)} senses; by reason: {dict(reasons)}")
    rank1_conflict = sum(1 for s in senses if "ngsl_conflict" in s.review_reasons and s.sense_rank == 1)
    print(f"  ngsl_conflict on rank-1 senses: {rank1_conflict}")
    print(f"  pos_mismatch on rank-1 senses: "
          f"{sum(1 for s in senses if 'pos_mismatch' in s.review_reasons and s.sense_rank == 1)}")
    lex_cefr = Counter(lx.cefr for lx in lexemes.values())
    for name, counts in (("senses", Counter(s.cefr for s in senses)), ("lexemes", lex_cefr)):
        graded = sum(v for k, v in counts.items() if k)
        share = 100 * (counts.get("C1", 0) + counts.get("C2", 0)) / max(1, graded)
        print(f"CEFR {name}: {dict(sorted(counts.items(), key=str))}; C1+C2 {share:.1f}%")
    print(f"CEFR: {dict(sorted(Counter(s.cefr for s in senses).items(), key=str))}; "
          f"null cefr {sum(s.cefr is None for s in senses)}, empty uz "
          f"{sum(not s.meaning_uz for s in senses)}, empty def {sum(not s.definition_en for s in senses)}")
    no_sense = [lx.lemma for lx in lexemes.values()
                if not any(s.lexeme_id == lx.id for s in senses)]
    print(f"lexemes with no sense: {len(no_sense)} {no_sense[:20]}")

    rows_per_sense = Counter(r.sense_id for r in rows)

    def table(items):
        print("| lemma | pos | rank | definition_en | meaning_uz | alt | cefr | source | rows | reasons |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for s in items:
            lx = lexemes[s.lexeme_id]
            print(f"| {lx.lemma} | {lx.pos} | {s.sense_rank} | {_cell(s.definition_en, 70)} | "
                  f"{_cell(s.meaning_uz, 40)} | {_cell(s.meaning_uz_alt, 30)} | {s.cefr} | "
                  f"{s.source_id} | {rows_per_sense.get(s.id, 0)} | {','.join(s.review_reasons)} |")

    print("\n20 random senses:")
    table(random.Random(5).sample(senses, min(20, len(senses))))
    for lemma in NAMED:
        print(f"\n{lemma}:")
        table(sorted((s for s in senses if lexemes[s.lexeme_id].lemma == lemma),
                     key=lambda s: (lexemes[s.lexeme_id].pos, s.sense_rank)))


# --- Main --------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--make-sample", type=Path)
    parser.add_argument("--sample-size", type=int, default=200)
    parser.add_argument("--ids", type=Path, help="sample json from --make-sample")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--unit", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--usage-log", type=Path)
    parser.add_argument("--report", type=Path, help="sample json, or 'all'")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.make_sample:
        await make_sample(args.make_sample, args.sample_size)
        return
    if args.report:
        await report(None if str(args.report) == "all"
                     else json.loads(args.report.read_text()))
        return

    async with async_session_factory() as session:
        query = sa_select(Lexeme.id).order_by(Lexeme.lemma, Lexeme.pos)
        if args.ids:
            wanted = [uuid.UUID(x["id"]) for x in json.loads(args.ids.read_text())["lexemes"]]
            query = query.where(Lexeme.id.in_(wanted))
        elif not args.all:
            parser.error("give --ids, --all, --make-sample or --report")
        if not args.force:
            query = query.where(Lexeme.enriched_at.is_(None))
        ids = list((await session.exec(query)).scalars().all())
    if args.limit:
        ids = ids[: args.limit]
    print(f"{len(ids)} lexemes to enrich")
    if ids:
        await run(ids, args.unit, args.concurrency, args.usage_log)


if __name__ == "__main__":
    asyncio.run(main())
