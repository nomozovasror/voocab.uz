"""Cambridge Advanced Learner's Dictionary (CALD) definitions -- the command
line. The engine (index, matcher, mapper, translation v2, comparison judge,
apply/restore) is `app.services.lexicon_cald`; its docstring has the design
and the rules agreed with the owner. Run from ``backend/``::

    # phase 2a: the full run
    uv run python -m scripts.cald index --source ~/Desktop/vocabulary
    uv run python -m scripts.cald match
    uv run python -m scripts.cald revalidate --old-index <pilot index.json.gz>
    uv run python -m scripts.cald map --all [--concurrency 12]
    uv run python -m scripts.cald translate --v2 --all [--concurrency 12]  # incl. verify
    uv run python -m scripts.cald verify --all     # re-verify far-levelled mappings only
    uv run python -m scripts.cald apply                       # dry run, read only
    uv run python -m scripts.cald apply --confirm-db <dbname> # writes
    uv run python -m scripts.cald restore --all --confirm-db <dbname>
    uv run python -m scripts.cald restore --sense-id <uuid> ... --confirm-db <dbname>
    uv run python -m scripts.cald masking-report
    uv run python -m scripts.cald backup

    # phase 1: the 100-sense pilot (kept: its review page and dump)
    uv run python -m scripts.cald map --sample 100 --seed 7
    uv run python -m scripts.cald translate --sample 100 [--v2 --judge-model M ...]
    uv run python -m scripts.cald review-export
    uv run python -m scripts.cald dump

## Nothing CALD-derived is ever committed

Every artefact goes to :data:`PRIVATE_DIR` (gitignored as a directory); the
pilot's review page goes outside the repository altogether
(:data:`REVIEW_PATH`, on the Desktop). See the engine's docstring.

## Reads are read-only, writes are named

Every query of ``index``/``match``/``map``/``translate``/``apply`` (dry run)
/``masking-report`` runs inside :func:`readonly_connection` (``SET
TRANSACTION READ ONLY``: Postgres itself refuses a write). ``apply`` and
``restore`` write only with ``--confirm-db NAME``, and refuse unless NAME is
the database ``DATABASE_URL`` points at -- a typo'd or forgotten flag is a
dry run, never a write to the wrong database.

## Spend

Every model command adds its cost to :data:`USAGE_FILE`; the full-run
commands stop (:class:`app.services.lexicon_cald.BudgetExceeded`) once the
CALD total there reaches ``--budget`` (default
:data:`app.services.lexicon_cald.DEFAULT_BUDGET_USD`). Every answer was
logged before the stop, so the re-run after raising the budget resumes.

## The pilot (phase 1)

A stratified 100-sense sample (:func:`draw_sample`), mapped and translated
like the full run and shown to the owner as one self-contained HTML page.
Its review found the MAPPING good and round 1's translation not (the
translator saw only the definition; the same/different judge passed real
errors), which is why translation v2 and the comparison judge exist.
Round 1 (``translate`` without ``--v2``) and the review page stay for the
record; the full run never uses them.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import html
import json
import logging
import random
import shutil
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.services.lexicon_cald import (  # noqa: F401 - re-exported for the tests
    ACCEPTED_CONFIDENCES,
    CEFR_LEVELS,
    COMPARE_PROMPT,
    DECISIONS_FILE,
    INDEX_FILE,
    INDEX_VERSION,
    MATCH_FILE,
    MATCH_KINDS,
    MAX_CANDIDATES,
    PRIVATE_DIR,
    TRANSLATE_V2_PROMPT,
    USAGE_FILE,
    CaldIndex,
    DecisionLog,
    Lexicon,
    Match,
    OurSense,
    _hash,
    alias_is_same,
    ask_keyed,
    ask_map,
    build_index,
    candidate_fingerprints,
    clean_definition,
    combine_comparison,
    compare_key,
    compatible,
    effective_mapping,
    follow_pointers,
    hyphen_variants,
    load_examples,
    load_index_data,
    load_lexicon,
    map_key,
    model_cost,
    parse_compare_item,
    parse_entries,
    parse_map_answer,
    parse_v2_item,
    phrase_forms,
    pointer_candidates,
    pointer_target,
    readonly_connection,
    render_compare_item,
    render_v2_item,
    singular_candidates,
    spelling_variants,
    translate2_key,
    v2_entry,
    v2_state,
    xref_key,
)

logger = logging.getLogger("scripts.cald")

COVERAGE_FILE = "coverage.json"
SAMPLE_FILE = "sample.json"
#: Outside the repository on purpose: it is full of CALD text.
REVIEW_PATH = Path.home() / "Desktop" / "voocab-cald-pilot.html"
BACKUP_ROOT = Path.home() / "voocab-dev-backups"



# --- match -----------------------------------------------------------------------


def coverage_report(lexemes: list[dict], matches: dict[str, Match], *,
                    word_list_lexemes: set[str], saved_lexemes: set[str]) -> dict:
    """Counts by kind and by step, overall and for the lexemes a word list
    or a learner's saved word points at -- the two groups whose definitions
    a learner actually reads first."""
    def tally(ids) -> dict:
        kinds = Counter(matches[i].kind for i in ids)
        hows = Counter(matches[i].how for i in ids if matches[i].how)
        return {"total": len(ids), "kinds": dict(kinds), "how": dict(hows)}

    all_ids = [lx["id"] for lx in lexemes]
    headword_only = Counter()
    for lx in lexemes:
        m = matches[lx["id"]]
        if m.kind == "headword-only":
            headword_only[f"{lx['pos'] or '?'} -> {'/'.join(m.cald_classes)}"] += 1
    by_pos = defaultdict(Counter)
    for lx in lexemes:
        by_pos[lx["pos"] or "?"][matches[lx["id"]].kind] += 1
    none_sample = sorted(lx["lemma"] for lx in lexemes if matches[lx["id"]].kind == "none")
    variant_examples = defaultdict(list)
    for lx in lexemes:
        m = matches[lx["id"]]
        if m.kind == "variant" and len(variant_examples[m.how]) < 25:
            variant_examples[m.how].append(f"{lx['lemma']} ({lx['pos']}) -> {m.via}")
    return {
        "all": tally(all_ids),
        "word_list": tally([i for i in all_ids if i in word_list_lexemes]),
        "saved": tally([i for i in all_ids if i in saved_lexemes]),
        "by_pos": {k: dict(v) for k, v in sorted(by_pos.items())},
        "headword_only_pairs": dict(headword_only.most_common()),
        "variant_examples": dict(variant_examples),
        "none_count": len(none_sample),
        "none_sample": none_sample[:: max(1, len(none_sample) // 200)][:200],
    }


def _print_tally(name: str, tally: dict) -> None:
    total = tally["total"] or 1
    kinds = tally["kinds"]
    parts = "  ".join(f"{k} {kinds.get(k, 0):>6} ({kinds.get(k, 0) / total:.1%})"
                      for k in MATCH_KINDS)
    print(f"{name:10} {tally['total']:>6}  {parts}")


async def cmd_match(out_dir: Path = PRIVATE_DIR) -> None:
    index = CaldIndex(load_index_data(out_dir))
    lexicon = await load_lexicon()
    matches = {lx["id"]: index.match(lx["lemma"], lx["pos"]) for lx in lexicon.lexemes}
    sense_lexeme = {s.id: s.lexeme_id for s in lexicon.senses}
    saved_lexemes = {sense_lexeme[s] for s in lexicon.saved_senses if s in sense_lexeme}
    report = coverage_report(lexicon.lexemes, matches,
                             word_list_lexemes=lexicon.word_list_lexemes,
                             saved_lexemes=saved_lexemes)
    matched_senses = [s for s in lexicon.senses if matches[s.lexeme_id].kind in ("exact", "variant")]
    report["senses"] = {
        "total": len(lexicon.senses), "in_matched_lexemes": len(matched_senses),
        "word_list_in_matched": sum(s.id in lexicon.word_list_senses for s in matched_senses),
        "word_list_total": sum(s.id in lexicon.word_list_senses for s in lexicon.senses),
        "saved_in_matched": sum(s.id in lexicon.saved_senses for s in matched_senses),
        "saved_total": sum(s.id in lexicon.saved_senses for s in lexicon.senses),
    }
    counts = [len(m.refs) for m in matches.values() if m.refs]
    report["candidates_per_lexeme"] = {
        "max": max(counts, default=0), "mean": round(sum(counts) / max(1, len(counts)), 1),
        "over_40": sum(c > 40 for c in counts),
    }
    report["built_at"] = datetime.now(timezone.utc).isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    table = {lx["id"]: {"lemma": lx["lemma"], "pos": lx["pos"], **matches[lx["id"]].to_json()}
             for lx in lexicon.lexemes}
    with gzip.open(out_dir / MATCH_FILE, "wt", encoding="utf-8") as fh:
        json.dump(table, fh, ensure_ascii=False)
    (out_dir / COVERAGE_FILE).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print("lexemes (no proper nouns, no function words)")
    for name in ("all", "word_list", "saved"):
        _print_tally(name, report[name])
    print(f"variant steps: {report['all']['how']}")
    print(f"senses: {report['senses']}")
    print(f"headword-only pos pairs (not matched): {report['headword_only_pairs']}")
    print(f"candidates per matched lexeme: {report['candidates_per_lexeme']}")
    print(f"written: {out_dir / MATCH_FILE}, {out_dir / COVERAGE_FILE}")


def load_matches(out_dir: Path = PRIVATE_DIR) -> dict[str, dict]:
    path = out_dir / MATCH_FILE
    if not path.exists():
        raise SystemExit(f"{path} not found -- run `match` first")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def write_usage(out_dir: Path, cmd: str, usage) -> None:
    total = sum(model_cost(m, u) for m, u in usage.by_model.items())
    record = {
        "at": datetime.now(timezone.utc).isoformat(), "cmd": cmd,
        "total_cost_usd": round(total, 6),
        "by_model": {m: {"requests": u.requests, "failures": u.failures,
                         "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                         "cost_usd": round(model_cost(m, u), 6)} for m, u in usage.by_model.items()},
        "by_step": {s: {"requests": u.requests, "input_tokens": u.input_tokens,
                        "output_tokens": u.output_tokens} for s, u in usage.by_step.items()},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / USAGE_FILE).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    for model, u in usage.by_model.items():
        print(f"  {model:24} {u.requests:4} req ({u.failures} failed)  in {u.input_tokens:8,}"
              f"  out {u.output_tokens:7,}  ${model_cost(model, u):.4f}")
    print(f"  total ${total:.4f}")


# --- The sample ----------------------------------------------------------------------

#: Share of the sample each stratum gets, in the order they are drawn (a
#: sense drawn by an earlier stratum is not drawn again). ``saved`` and
#: ``word_list`` are what learners read first; ``siblings`` takes EVERY
#: sense of a few multi-sense lexemes, because the full run lives or dies on
#: telling one lexeme's senses apart -- two of our senses mapped to one CALD
#: sense would end up with the same definition; ``variant`` makes sure the
#: owner sees what the spelling/plural/idiom rules matched, which a uniform
#: draw would almost never show (they are a few percent of matches).
STRATA: tuple[tuple[str, float], ...] = (
    ("saved", 0.15), ("word_list", 0.30), ("material", 0.20), ("siblings", 0.10),
    ("variant", 0.10), ("other", 0.15),
)


def draw_sample(senses: list[OurSense], matches: dict[str, dict], lexicon: Lexicon,
                n: int, seed: int) -> list[tuple[OurSense, str]]:
    """``n`` senses of matched lexemes, stratified by :data:`STRATA`,
    deterministic for a given ``seed`` and database. A stratum short of
    senses leaves its slots to ``other``."""
    rng = random.Random(seed)
    eligible = sorted((s for s in senses
                       if matches.get(s.lexeme_id, {}).get("kind") in ("exact", "variant")),
                      key=lambda s: s.id)
    taken: dict[str, str] = {}

    def take(pool: list[OurSense], quota: int, stratum: str) -> None:
        pool = [s for s in pool if s.id not in taken]
        for sense in rng.sample(pool, min(quota, len(pool))):
            taken[sense.id] = stratum

    quotas = {name: round(n * share) for name, share in STRATA}
    take([s for s in eligible if s.id in lexicon.saved_senses], quotas["saved"], "saved")
    take([s for s in eligible if s.id in lexicon.word_list_senses], quotas["word_list"],
         "word_list")
    take([s for s in eligible if s.id in lexicon.material_senses], quotas["material"],
         "material")
    by_lexeme: dict[str, list[OurSense]] = defaultdict(list)
    for sense in eligible:
        by_lexeme[sense.lexeme_id].append(sense)
    multi = sorted(lx for lx, group in by_lexeme.items() if 2 <= len(group) <= 4
                   and any(s.id in lexicon.word_list_senses or s.id in lexicon.material_senses
                           for s in group))
    rng.shuffle(multi)
    room = quotas["siblings"]
    for lexeme_id in multi:
        group = [s for s in by_lexeme[lexeme_id] if s.id not in taken]
        if len(group) < 2 or len(group) > room:
            continue
        for sense in group:
            taken[sense.id] = "siblings"
        room -= len(group)
        if room < 2:
            break
    take([s for s in eligible if matches[s.lexeme_id]["kind"] == "variant"],
         quotas["variant"], "variant")
    take(eligible, n - len(taken), "other")
    order = {s.id: s for s in eligible}
    chosen = [(order[i], stratum) for i, stratum in taken.items()]
    chosen.sort(key=lambda t: ([name for name, _ in STRATA].index(t[1]), t[0].lemma, t[0].id))
    return chosen[:n]


def load_sample(out_dir: Path, n: int | None = None) -> dict:
    path = out_dir / SAMPLE_FILE
    if not path.exists():
        raise SystemExit(f"{path} not found -- run `map --sample N` first")
    sample = json.loads(path.read_text(encoding="utf-8"))
    if n is not None and sample["n"] != n:
        raise SystemExit(f"the saved sample has {sample['n']} senses, not {n} "
                         f"(map --sample {n} --resample to draw a new one)")
    return sample



async def cmd_map(n: int, seed: int, resample: bool, out_dir: Path = PRIVATE_DIR) -> None:
    from app.services import lexicon_enrich as le

    index = CaldIndex(load_index_data(out_dir))
    matches = load_matches(out_dir)
    sample_path = out_dir / SAMPLE_FILE
    if sample_path.exists() and not resample:
        sample = load_sample(out_dir)
        if sample["n"] != n or sample["seed"] != seed:
            raise SystemExit(f"a sample of {sample['n']} (seed {sample['seed']}) already exists; "
                             f"pass --resample to replace it")
        print(f"reusing the saved sample ({n} senses, seed {seed})")
    else:
        lexicon = await load_lexicon()
        drawn = draw_sample(lexicon.senses, matches, lexicon, n, seed)
        examples = await load_examples([s.id for s, _ in drawn])
        items = []
        for sense, stratum in drawn:
            m = matches[sense.lexeme_id]
            items.append({
                "sense_id": sense.id, "lexeme_id": sense.lexeme_id, "lemma": sense.lemma,
                "pos": sense.pos, "stratum": stratum, "sense_rank": sense.sense_rank,
                "definition_en": sense.definition_en, "meaning_uz": sense.meaning_uz,
                "meaning_uz_alt": sense.meaning_uz_alt, "cefr": sense.cefr,
                "source_id": sense.source_id, "example": examples.get(sense.id, ""),
                "in_word_list": sense.id in lexicon.word_list_senses,
                "saved": sense.id in lexicon.saved_senses,
                "match_kind": m["kind"], "match_how": m["how"], "match_via": m["via"],
                "refs": m["refs"][:MAX_CANDIDATES], "refs_cut": max(0, len(m["refs"]) - MAX_CANDIDATES),
            })
        sample = {"n": n, "seed": seed, "run_id": uuid.uuid4().hex[:12],
                  "drawn_at": datetime.now(timezone.utc).isoformat(), "items": items}
        out_dir.mkdir(parents=True, exist_ok=True)
        sample_path.write_text(json.dumps(sample, indent=1, ensure_ascii=False))
        print(f"drew {len(items)} senses: {dict(Counter(i['stratum'] for i in items))}")

    log = DecisionLog(out_dir / DECISIONS_FILE)
    model = le.MODEL_MAIN
    todo = []
    for item in sample["items"]:
        cands = index.candidates([r for r in item["refs"] if r in index.senses])
        for i, cand in enumerate(cands, 1):
            cand["cid"] = f"c{i}"
        key = map_key(item, cands)
        if log.get("map", key) is None:
            todo.append((item, cands, key))
    print(f"{len(sample['items']) - len(todo)} answers reused from the log, {len(todo)} to ask")
    usage = le.UsageLog()
    gemini = le.Gemini(usage)
    try:
        answers = await ask_map(gemini, model, [(item, cands) for item, cands, _ in todo])
    finally:
        await gemini.aclose()
    for item, cands, key in todo:
        answer = answers.get(item["sense_id"])
        payload = {"sense_id": item["sense_id"], "lemma": item["lemma"], "pos": item["pos"],
                   "model": model, "candidates": len(cands), "answered": answer is not None}
        if answer is not None:
            payload.update(answer)
            if answer["ref"]:
                _, sense = index.senses[answer["ref"]]
                payload["cald_definition"] = sense["def"]
                payload["cald_level"] = sense["level"]
        log.put("map", key, payload)
    summary = Counter()
    for item in sample["items"]:
        record = log.latest("map", item["sense_id"])
        if record is None or not record.get("answered"):
            summary["no answer"] += 1
        elif record["ref"] is None:
            summary["none"] += 1
        else:
            summary[f"mapped/{record['confidence']}"] += 1
    print(f"map: {dict(sorted(summary.items()))}")
    write_usage(out_dir, "map", usage)


# --- translate ----------------------------------------------------------------------


def translate_key(item: dict, ref: str, cald_definition: str) -> str:
    """What a translate record answers: this sense, this CALD sense and
    definition, this old pair. Anything else is a different question."""
    old_uz = item["meaning_uz"]
    return (f"{item['sense_id']}|{ref}|"
            f"{_hash(cald_definition, old_uz, item['meaning_uz_alt'] or old_uz)}")


def current_translation(log: DecisionLog, item: dict, index: CaldIndex) -> dict | None:
    """The translate record for the sense's CURRENT mapping, or None --
    never a record left over from a mapping or a definition since changed."""
    mapped = log.latest("map", item["sense_id"])
    if not mapped or not mapped.get("ref") or mapped["ref"] not in index.senses:
        return None
    _, cald = index.senses[mapped["ref"]]
    return log.get("translate", translate_key(item, mapped["ref"], cald["def"]))


async def cmd_translate(n: int, out_dir: Path = PRIVATE_DIR) -> None:
    """For every mapped sense of the sample: the production translation step
    on the CALD definition (new pair + its double judge) and the OLD pair
    judged twice against the same CALD definition -- see the module
    docstring."""
    from app.services import lexicon_enrich as le

    sample = load_sample(out_dir, n)
    log = DecisionLog(out_dir / DECISIONS_FILE)
    index = CaldIndex(load_index_data(out_dir))
    todo = []
    for item in sample["items"]:
        mapped = log.latest("map", item["sense_id"])
        if not mapped or not mapped.get("answered") or not mapped.get("ref"):
            continue
        _, cald = index.senses[mapped["ref"]]
        old_uz = item["meaning_uz"]
        old_alt = item["meaning_uz_alt"] or old_uz
        key = translate_key(item, mapped["ref"], cald["def"])
        if log.get("translate", key) is None:
            todo.append((item, mapped["ref"], cald["def"], old_uz, old_alt, key))
    print(f"{len(todo)} mapped senses to translate")
    if not todo:
        _translate_summary(sample, log, index)
        return
    usage = le.UsageLog()
    gemini = le.Gemini(usage)
    works = []
    for item, ref, definition, *_ in todo:
        planned = le.Sense(id=uuid.UUID(item["sense_id"]), definition_en=definition[: le.DEF_MAX],
                           translate=True)
        works.append(le.LexemeWork(id=uuid.UUID(item["lexeme_id"]), lemma=item["lemma"],
                                   pos=item["pos"], is_phrase=" " in item["lemma"],
                                   frequency_band=None, oewn=[], senses=[], rows=[],
                                   plan=[planned]))
    olds = [(i, t) for i, t in enumerate(todo) if t[3]]
    try:
        await le.step_translate(gemini, works)
        old_results = await le.judge_twice(gemini, [
            le.JudgeItem(label=f"{t[0]['lemma']} ({t[0]['pos'] or '?'})", definition=t[2],
                         a=t[4], b=t[3]) for _, t in olds])
    finally:
        await gemini.aclose()
    old_by_index = {i: result for (i, _), result in zip(olds, old_results)}
    for i, ((item, ref, definition, old_uz, old_alt, key), work) in enumerate(zip(todo, works)):
        new = work.plan[0]
        old_verdict, old_better = old_by_index.get(i, (None, ""))
        log.put("translate", key, {
            "sense_id": item["sense_id"], "lemma": item["lemma"], "pos": item["pos"], "ref": ref,
            "cald_definition": definition,
            "new_uz": new.meaning_uz, "new_alt": new.meaning_uz_alt, "new_verdict": new.judge,
            "old_uz": old_uz, "old_alt": item["meaning_uz_alt"],
            "old_single": not item["meaning_uz_alt"], "old_verdict": old_verdict,
            "old_better": old_better, "note": work.note.strip(),
            "models": {"main": le.MODEL_MAIN, "alt": le.MODEL_ALT, "judge": le.MODEL_JUDGE},
        })
    _translate_summary(sample, log, index)
    write_usage(out_dir, "translate", usage)


def _translate_summary(sample: dict, log: DecisionLog, index: CaldIndex) -> None:
    verdicts = {"old": Counter(), "new": Counter()}
    for item in sample["items"]:
        record = current_translation(log, item, index)
        if record:
            verdicts["old"][str(record["old_verdict"])] += 1
            verdicts["new"][str(record["new_verdict"])] += 1
    print(f"judge on the CALD definition -- old Uzbek: {dict(verdicts['old'])}; "
          f"new Uzbek: {dict(verdicts['new'])}")



async def cmd_translate_v2(n: int, judge_models: list[str], out_dir: Path = PRIVATE_DIR) -> None:
    """Round 2 on the SAME sample: pointers followed first (agreed rule 2),
    then both production translators run the v2 prompt (agreed rule 4) on
    every effectively-mapped sense, then each judge model compares the old
    pair with the new one twice (positions swapped). Every answer is logged
    before the next step; a re-run asks only what is missing."""
    from app.services import lexicon_enrich as le

    sample = load_sample(out_dir, n)
    log = DecisionLog(out_dir / DECISIONS_FILE)
    index = CaldIndex(load_index_data(out_dir))
    usage = le.UsageLog()
    gemini = le.Gemini(usage)
    try:
        followed = await follow_pointers(sample, log, index, gemini, le.MODEL_MAIN)
        print(f"pointers: {dict(followed)}")
        entries = []
        for item in sample["items"]:
            mapping = effective_mapping(log, item, index)
            if mapping["decision"] == "mapped":
                entries.append(v2_entry(item, mapping["ref"], index))
        for model in (le.MODEL_MAIN, le.MODEL_ALT):
            todo = [e for e in entries if log.get("translate2", translate2_key(e, model)) is None]
            got = await ask_keyed(gemini, model, TRANSLATE_V2_PROMPT, todo, render_v2_item,
                                  parse_v2_item, step="cald-translate-v2", reply_key="items")
            for entry in todo:
                answer = got.get(entry["id"])
                log.put("translate2", translate2_key(entry, model), {
                    "sense_id": entry["id"], "lemma": entry["lemma"], "ref": entry["ref"],
                    "model": model, "answered": answer is not None, **(answer or {})})
            print(f"translate v2 {model}: asked {len(todo)}, answered {len(got)}")
        states = [v2_state(log, item, index) for item in sample["items"]]
        pairs = [s["entry"] for s in states if s and s["entry"]["new_uz"] and s["entry"]["old_uz"]]
        for judge in judge_models:
            todo = [e for e in pairs if log.get("compare", compare_key(e, judge)) is None]
            runs = []
            for swap in (False, True):
                runs.append(await ask_keyed(
                    gemini, judge, COMPARE_PROMPT, [dict(e, swap=swap) for e in todo],
                    render_compare_item, parse_compare_item, step=f"cald-compare:{judge}",
                    reply_key="verdicts", batch=25, per_item_tokens=120))
            for entry in todo:
                per_run = [r.get(entry["id"]) for r in runs]
                log.put("compare", compare_key(entry, judge), {
                    "sense_id": entry["id"], "lemma": entry["lemma"], "ref": entry["ref"],
                    "judge_model": judge, "per_run": per_run, **combine_comparison(per_run)})
            print(f"compare {judge}: asked {len(todo)}")
    finally:
        await gemini.aclose()
    print_round2_summary(sample, log, index)
    write_usage(out_dir, "translate-v2", usage)


def round2_counts(sample: dict, log: DecisionLog, index: CaldIndex) -> dict:
    counts = {"decision": Counter(), "flag_main": Counter(), "flag_alt": Counter(),
              "kept_but_changed": 0, "unanswered": Counter(), "compare": defaultdict(Counter)}
    for item in sample["items"]:
        counts["decision"][effective_mapping(log, item, index)["decision"]] += 1
        state = v2_state(log, item, index)
        if not state:
            continue
        for side, record in (("main", state["main"]), ("alt", state["alt"])):
            if not record or not record.get("answered"):
                counts["unanswered"][side] += 1
                continue
            counts[f"flag_{side}"][record["flag"]] += 1
            if side == "main" and record["flag"] == "kept" and record["changed"]:
                counts["kept_but_changed"] += 1
        if not state["entry"]["old_uz"]:
            counts["compare"]["(no old Uzbek)"]["not compared"] += 1
        for judge, record in state["compare"].items():
            c = counts["compare"][judge]
            c[f"keep {record['keep']}"] += 1
            c[f"loose keep {record['loose_keep']}"] += 1
            c["wrong_new (both runs)"] += record["wrong_new"] == 2
            c["wrong_new (any run)"] += record["wrong_new"] > 0
            c["wrong_old (both runs)"] += record["wrong_old"] == 2
            c["old better (both runs)"] += record["old_better"] == 2
            c["new better (both runs)"] += record["new_better"] == 2
            for flag in record["flags"]:
                c[flag] += 1
    return counts


def print_round2_summary(sample: dict, log: DecisionLog, index: CaldIndex) -> None:
    counts = round2_counts(sample, log, index)
    print(f"effective mapping: {dict(counts['decision'])}")
    print(f"v2 flags -- main: {dict(counts['flag_main'])}; alt: {dict(counts['flag_alt'])}; "
          f"main 'kept' but text changed: {counts['kept_but_changed']}; "
          f"unanswered: {dict(counts['unanswered'])}")
    for judge, c in counts["compare"].items():
        print(f"compare {judge}: {dict(sorted(c.items()))}")


# --- review-export --------------------------------------------------------------------


def review_rows(sample: dict, log: DecisionLog, index: CaldIndex) -> list[dict]:
    """One plain dict per sampled sense -- everything the page and the text
    dump show, so :func:`render_review` and :func:`render_dump` are pure
    functions of their input (and testable without CALD, a database or a
    model). The decision is the EFFECTIVE mapping (:func:`effective_mapping`
    -- a pointer followed, an unaccepted confidence dropped); ``v1_*`` is
    round 1's translation, ``v2`` round 2's (None before round 2 ran)."""
    rows = []
    for number, item in enumerate(sample["items"], 1):
        mapping = effective_mapping(log, item, index)
        translated = current_translation(log, item, index)
        state = v2_state(log, item, index)
        cands = index.candidates(item["refs"])
        row = {
            "n": number, "sense_id": item["sense_id"], "lemma": item["lemma"],
            "pos": item["pos"], "stratum": item["stratum"], "match_how": item["match_how"],
            "match_via": item["match_via"], "old_def": item["definition_en"],
            "old_uz": item["meaning_uz"], "old_alt": item["meaning_uz_alt"],
            "old_cefr": item["cefr"] or "", "source_id": item["source_id"],
            "example": item["example"], "decision": mapping["decision"], "ref": mapping["ref"] or "",
            "confidence": mapping["confidence"], "reason": mapping["reason"], "cald": None,
            "pointer": None, "cefr_final": item["cefr"] or "", "cefr_source": "ours",
            "v1_uz": "", "v1_alt": "", "old_verdict": None, "new_verdict": None, "v2": None,
            "candidates": [dict(c, chosen=False) for c in cands], "refs_cut": item.get("refs_cut", 0),
        }
        chosen = {mapping["ref"], mapping["pointer_ref"]} - {None}
        for cand in row["candidates"]:
            cand["chosen"] = cand["ref"] in chosen
        if mapping["pointer_ref"]:
            row["pointer"] = index.candidates([mapping["pointer_ref"]])[0]
        if mapping["decision"] == "mapped":
            cald = index.candidates([mapping["ref"]])[0]
            row["cald"] = cald
            if cald["level"]:
                row["cefr_final"], row["cefr_source"] = cald["level"], "cald"
        if translated:
            row.update(v1_uz=translated["new_uz"], v1_alt=translated["new_alt"],
                       old_verdict=translated["old_verdict"],
                       new_verdict=translated["new_verdict"])
        if state:
            main, alt = state["main"] or {}, state["alt"] or {}
            row["v2"] = {
                "uz": state["entry"]["new_uz"], "alt": state["entry"]["new_alt"],
                "flag": main.get("flag", ""), "reason": main.get("reason", ""),
                "changed": main.get("changed", False),
                "alt_flag": alt.get("flag", ""), "alt_reason": alt.get("reason", ""),
                "compare": {judge: {k: rec[k] for k in ("keep", "loose_keep", "runs", "old_better",
                                                         "new_better", "equal", "wrong_old",
                                                         "wrong_new", "flags")}
                            | {"reasons": [r["reason"] if r else "" for r in rec["per_run"]]}
                            for judge, rec in state["compare"].items()},
            }
        rows.append(row)
    return rows


REVIEW_CSS = """
:root { color-scheme: light; --ink:#1d2433; --soft:#5b6475; --line:#d9dee7; --bg:#f6f7f9;
  --card:#fff; --ok:#1f7a4d; --bad:#b3261e; --warn:#8a5a00; --accent:#2f5bd3; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
header.top { position:sticky; top:0; z-index:5; background:var(--card); border-bottom:1px solid var(--line);
  padding:12px 20px; display:flex; flex-wrap:wrap; gap:12px 20px; align-items:center; }
header.top h1 { font-size:17px; margin:0; }
header.top .stats { color:var(--soft); font-size:13px; }
header.top select, header.top button { font:inherit; font-size:14px; padding:5px 10px; }
header.top button { background:var(--accent); color:#fff; border:0; border-radius:6px; cursor:pointer; }
main { max-width:1180px; margin:0 auto; padding:16px 20px 80px; }
.intro { color:var(--soft); font-size:13px; margin:0 0 16px; }
section.row { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:14px 16px; margin:0 0 14px; }
section.row.done { border-left:4px solid var(--ok); }
.row-head { display:flex; flex-wrap:wrap; gap:6px 10px; align-items:baseline; margin-bottom:10px; }
.row-head .n { color:var(--soft); font-variant-numeric:tabular-nums; }
.row-head .lemma { font-size:18px; font-weight:650; }
.tag { font-size:12px; color:var(--soft); border:1px solid var(--line); border-radius:999px; padding:0 8px; }
.cols { display:grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap:14px; }
@media (max-width: 900px) { .cols { grid-template-columns: 1fr; } }
.col h3 { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--soft); margin:0 0 6px; }
.col p { margin:0 0 6px; }
.def { font-size:15px; }
.uz { font-weight:600; }
.alt { font-weight:400; color:var(--soft); }
.meta { font-size:13px; color:var(--soft); }
.ex { font-size:13px; color:var(--soft); font-style:italic; }
.none { color:var(--warn); }
.v-same { color:var(--ok); font-weight:600; } .v-different { color:var(--bad); font-weight:600; }
.v-unsure { color:var(--warn); font-weight:600; } .v-null { color:var(--soft); }
.conf-high { color:var(--ok); } .conf-medium { color:var(--warn); } .conf-low { color:var(--bad); }
details { margin:10px 0 0; font-size:13px; }
details ol { margin:6px 0 0; padding-left:22px; }
details li.chosen { font-weight:650; }
details .gw { color:var(--soft); }
.answers { display:flex; flex-wrap:wrap; gap:10px 18px; margin-top:12px; padding-top:10px;
  border-top:1px dashed var(--line); align-items:flex-start; }
fieldset { border:1px solid var(--line); border-radius:8px; padding:6px 10px; margin:0; }
legend { font-size:13px; color:var(--soft); padding:0 4px; }
fieldset label { margin-right:12px; cursor:pointer; }
.note { flex:1 1 260px; display:flex; flex-direction:column; font-size:13px; color:var(--soft); }
.note textarea { font:inherit; font-size:14px; min-height:38px; padding:6px; border:1px solid var(--line);
  border-radius:6px; resize:vertical; }
"""

REVIEW_JS = """
(function () {
  var KEY = document.body.getAttribute('data-storage-key');
  var RUN = document.body.getAttribute('data-run');
  function load() { try { return JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { return {}; } }
  function save(s) { try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
  var state = load();
  var rows = Array.prototype.slice.call(document.querySelectorAll('section.row'));
  function questions(row) {
    return Array.prototype.slice.call(row.querySelectorAll('fieldset')).map(function (f) {
      return f.getAttribute('data-q'); });
  }
  function complete(row) {
    var a = state[row.getAttribute('data-id')] || {};
    var qs = questions(row);
    return qs.length > 0 && qs.every(function (q) { return !!a[q]; });
  }
  function refresh() {
    var done = 0;
    rows.forEach(function (row) {
      var ok = complete(row); row.classList.toggle('done', ok); if (ok) done++; });
    document.getElementById('progress').textContent = done + ' / ' + rows.length;
    applyFilter();
  }
  rows.forEach(function (row) {
    var id = row.getAttribute('data-id'); var a = state[id] || {};
    questions(row).forEach(function (q) {
      if (!a[q]) return;
      var el = row.querySelector('input[name="' + q + '-' + id + '"][value="' + a[q] + '"]');
      if (el) el.checked = true;
    });
    var note = row.querySelector('textarea');
    if (note && a.note) note.value = a.note;
  });
  document.addEventListener('change', function (e) {
    var t = e.target; if (!t.matches('input[type=radio]')) return;
    var row = t.closest('section.row'); var id = row.getAttribute('data-id');
    var q = t.closest('fieldset').getAttribute('data-q');
    state[id] = state[id] || {}; state[id][q] = t.value; save(state); refresh();
  });
  document.addEventListener('input', function (e) {
    var t = e.target; if (!t.matches('textarea')) return;
    var id = t.closest('section.row').getAttribute('data-id');
    state[id] = state[id] || {}; state[id].note = t.value; save(state);
  });
  function applyFilter() {
    var f = document.getElementById('filter').value;
    rows.forEach(function (row) {
      var show = true;
      if (f === 'mapped' || f === 'none' || f === 'unanswered') show = row.getAttribute('data-decision') === f;
      else if (f === 'low' || f === 'medium' || f === 'high') show = row.getAttribute('data-confidence') === f;
      else if (f === 'todo') show = !complete(row);
      else if (f === 'flagged') show = /different|unsure/.test(row.getAttribute('data-verdicts'));
      else if (f === 'kept' || f === 'adjusted' || f === 'replaced') show = row.getAttribute('data-flag') === f;
      else if (f === 'keep-old') show = /\\bold\\b/.test(row.getAttribute('data-keep'));
      else if (f === 'disputed') show = /disputed|both_wrong/.test(row.getAttribute('data-keep'));
      row.style.display = show ? '' : 'none';
    });
  }
  document.getElementById('filter').addEventListener('change', applyFilter);
  document.getElementById('export').addEventListener('click', function () {
    var out = {};
    rows.forEach(function (row) {
      var id = row.getAttribute('data-id'); var a = state[id] || {};
      out[id] = { lemma: row.getAttribute('data-lemma'), pos: row.getAttribute('data-pos'),
        decision: row.getAttribute('data-decision'), ref: row.getAttribute('data-ref') || null };
      questions(row).forEach(function (q) { out[id][q] = a[q] || null; });
      out[id].note = a.note || '';
    });
    var blob = new Blob([JSON.stringify({ run: RUN, exported_at: new Date().toISOString(),
      answers: out }, null, 1)], { type: 'application/json' });
    var link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'voocab-cald-pilot-answers-' + RUN.replace(/:/g, '-') + '.json';
    document.body.appendChild(link); link.click(); link.remove();
  });
  refresh();
})();
"""

_VERDICT_UZ = {"same": "bir xil / same", "different": "farq qiladi / different",
               "unsure": "aniq emas / unsure", None: "javob yo'q / no verdict"}


def _e(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _verdict(value: str | None) -> str:
    cls = f"v-{value}" if value else "v-null"
    return f'<span class="{cls}">{_e(_VERDICT_UZ.get(value, value))}</span>'


def _xref(cand: dict) -> str:
    if cand.get("xref_only"):
        return (f'→ {_e(cand["def"])} <span class="tag">havola, ta\'rif emas / '
                f'cross-reference, not a definition</span>')
    return _e(cand["def"])


def _radios(question: str, sense_id: str, legend: str) -> str:
    opts = (("yes", "ha / yes"), ("no", "yo'q / no"), ("unsure", "bilmayman / unsure"))
    inner = "".join(
        f'<label><input type="radio" name="{_e(question)}-{_e(sense_id)}" value="{v}"> {_e(label)}</label>'
        for v, label in opts)
    return f'<fieldset data-q="{_e(question)}"><legend>{_e(legend)}</legend>{inner}</fieldset>'


def _pair_html(uz: str, alt: str) -> str:
    alt_html = f'<span class="alt"> · {_e(alt)}</span>' if alt and alt != uz else ""
    return f'<p class="uz">{_e(uz) or "—"}{alt_html}</p>'


def _compare_html(judge: str, c: dict) -> str:
    better = (f'yangi/new {c["new_better"]}, eski/old {c["old_better"]}, teng/equal {c["equal"]}'
              f' (of {c["runs"]})')
    keep_cls = "v-same" if c["keep"] == "new" else "v-different"
    flags = f' <span class="tag">{_e(", ".join(c["flags"]))}</span>' if c["flags"] else ""
    reasons = "".join(f"<br>· {_e(r)}" for r in c.get("reasons", []) if r)
    return (f'<p class="meta"><b>{_e(judge)}</b>: better {better}; wrong old {c["wrong_old"]}, '
            f'wrong new {c["wrong_new"]} → <span class="{keep_cls}">keep {_e(c["keep"])}</span>'
            f'{flags}{reasons}</p>')


def _render_row(row: dict) -> str:
    sid = row["sense_id"]
    example = f'<p class="ex">Matndan / passage: “{_e(row["example"])}”</p>' if row["example"] else ""
    old = (f'<div class="col old"><h3>Bizdagi (eski) / ours (old)</h3>'
           f'<p class="def">{_e(row["old_def"]) or "—"}</p>'
           f'{_pair_html(row["old_uz"], row["old_alt"])}'
           f'<p class="meta">CEFR: {_e(row["old_cefr"]) or "—"} · manba / source: {_e(row["source_id"])}</p>'
           f'{example}</div>')
    v2 = row.get("v2")
    if row["decision"] == "mapped":
        cald = row["cald"]
        head = " · ".join(x for x in (cald["gw"], cald["pos"] or "idiom") if x)
        phrase = f'<p class="meta">ibora / phrase: {_e(cald["phrase"])}</p>' if cald.get("phrase") else ""
        cald_ex = f'<p class="ex">“{_e(cald["ex"])}”</p>' if cald.get("ex") else ""
        pointer = ""
        if row.get("pointer"):
            pointer = (f'<p class="meta">havola orqali / followed from the pointer '
                       f'“{_e(row["pointer"]["def"])}” ({_e(row["pointer"]["ref"])})</p>')
        level_note = (f'CEFR: CALD {_e(cald["level"] or "—")} · bizda / ours {_e(row["old_cefr"] or "—")}'
                      f' → <b>{_e(row["cefr_final"] or "—")}</b> ({_e(row["cefr_source"])})')
        middle = (f'<div class="col cald"><h3>Cambridge — {_e(cald["hw"])}</h3>'
                  f'<p class="meta">{_e(head)}</p>{phrase}<p class="def">{_xref(cald)}</p>{cald_ex}'
                  f'{pointer}<p class="meta">{level_note}</p>'
                  f'<p class="meta">Model: <span class="conf-{_e(row["confidence"])}">{_e(row["confidence"])}</span>'
                  f' — {_e(row["reason"])}</p></div>')
        v1 = (f'<p class="meta">v1:</p>{_pair_html(row["v1_uz"], row["v1_alt"])}'
              f'<p class="meta">v1 hakam / judge: eski / old {_verdict(row["old_verdict"])} · '
              f'yangi / new {_verdict(row["new_verdict"])}</p>')
        if v2:
            alt_flag = (f' · alt: {_e(v2["alt_flag"])} — {_e(v2["alt_reason"])}'
                        if v2.get("alt_flag") else "")
            compares = "".join(_compare_html(j, c) for j, c in v2["compare"].items())
            right = (f'<div class="col new"><h3>O\'zbekcha v2 / Uzbek v2</h3>'
                     f'{_pair_html(v2["uz"], v2["alt"])}'
                     f'<p class="meta"><span class="tag">{_e(v2["flag"] or "—")}</span> '
                     f'{_e(v2["reason"])}{alt_flag}</p>{compares}{v1}</div>')
            uz_legend = "v2 o'zbekcha to'g'rimi? / v2 Uzbek is correct?"
        else:
            right = f'<div class="col new"><h3>Yangi o\'zbekcha / new Uzbek</h3>{v1}</div>'
            uz_legend = "Yangi o'zbekcha to'g'rimi? / new Uzbek is correct?"
        questions = (_radios("same", sid, "CALD ma'nosi bir xilmi? / CALD sense is the same meaning?")
                     + _radios("uz", sid, uz_legend))
    elif row["decision"] == "none":
        pointer = ""
        if row.get("pointer"):
            pointer = (f'<p class="meta">havola / pointer: “{_e(row["pointer"]["def"])}” '
                       f'({_e(row["pointer"]["ref"])})</p>')
        middle = (f'<div class="col cald"><h3>Cambridge</h3><p class="none">Mos ma\'no yo\'q / '
                  f'no CALD sense is applied</p>{pointer}<p class="meta">Model: '
                  f'<span class="conf-{_e(row["confidence"])}">{_e(row["confidence"])}</span> — '
                  f'{_e(row["reason"])}</p><p class="meta">Eski ta\'rif qoladi / the old definition '
                  f'stays.</p></div>')
        right = '<div class="col new"><h3>Yangi o\'zbekcha / new Uzbek</h3><p class="meta">—</p></div>'
        questions = _radios("none_correct", sid,
                            "“Mos ma'no yo'q” to'g'rimi? (pastdagi ro'yxatga qarang) / "
                            "is “none” right? (see the list below)")
    else:
        middle = ('<div class="col cald"><h3>Cambridge</h3><p class="none">Model javob bermadi / '
                  'no usable model answer</p></div>')
        right = '<div class="col new"><h3>Yangi o\'zbekcha / new Uzbek</h3><p class="meta">—</p></div>'
        questions = ""
    items = "".join(
        f'<li class="{"chosen" if c["chosen"] else ""}"><span class="gw">[{_e(c["pos"] or "idiom")}'
        f'{" · " + _e(c["gw"]) if c["gw"] else ""}{" · " + _e(c["level"]) if c["level"] else ""}]</span> '
        f'{"<i>" + _e(c["phrase"]) + ":</i> " if c.get("phrase") else ""}{_xref(c)}'
        f'{" ✓" if c["chosen"] else ""}</li>'
        for c in row["candidates"])
    cut = f" (+{row['refs_cut']} ko'rsatilmadi / not shown)" if row.get("refs_cut") else ""
    details = (f'<details><summary>Barcha Cambridge ma\'nolari / all candidate CALD senses '
               f'({len(row["candidates"])}){cut}</summary><ol>{items}</ol></details>')
    verdicts = f'{row["old_verdict"] or ""} {row["new_verdict"] or ""}'
    keeps = " ".join(f'{c["keep"]} {" ".join(c["flags"])}' for c in (v2 or {}).get("compare", {}).values())
    via = f' → {_e(row["match_via"])}' if row["match_via"] and row["match_via"] != row["lemma"] else ""
    return (
        f'<section class="row" data-id="{_e(sid)}" data-lemma="{_e(row["lemma"])}" '
        f'data-pos="{_e(row["pos"])}" data-ref="{_e(row["ref"])}" data-decision="{_e(row["decision"])}" '
        f'data-confidence="{_e(row["confidence"])}" data-verdicts="{_e(verdicts)}" '
        f'data-flag="{_e((v2 or {}).get("flag", ""))}" data-keep="{_e(keeps)}">'
        f'<div class="row-head"><span class="n">#{row["n"]}</span>'
        f'<span class="lemma">{_e(row["lemma"])}</span><span class="tag">{_e(row["pos"] or "?")}</span>'
        f'<span class="tag">{_e(row["stratum"])}</span>'
        f'<span class="tag">{_e(row["match_how"])}{via}</span></div>'
        f'<div class="cols">{old}{middle}{right}</div>{details}'
        f'<div class="answers">{questions}<label class="note">Izoh / note'
        f'<textarea id="note-{_e(sid)}" rows="1"></textarea></label></div></section>'
    )


def render_review(rows: list[dict], *, run_id: str, round_tag: str = "",
                  title: str = "voocab.uz — CALD pilot") -> str:
    """The review page: one self-contained HTML file, no request to anything
    outside it (no font, no script, no stylesheet, no image), so it opens
    from the Desktop with the network off and leaks nothing it shows.
    Answers live in ``localStorage`` under a key that carries ``run_id`` --
    a new pilot never shows an old pilot's answers, and ``round_tag`` keeps
    a second review round of the same sample apart from the first -- and
    leave the page only through "Export answers", a JSON download keyed by
    sense id."""
    store = f"{run_id}:{round_tag}" if round_tag else run_id
    counts = Counter(r["decision"] for r in rows)
    conf = Counter(r["confidence"] for r in rows if r["decision"] == "mapped")
    stats = (f'{len(rows)} ma\'no / senses · mos / mapped {counts.get("mapped", 0)} '
             f'(high {conf.get("high", 0)}, medium {conf.get("medium", 0)}, low {conf.get("low", 0)}) · '
             f'yo\'q / none {counts.get("none", 0)} · javobsiz / unanswered {counts.get("unanswered", 0)}')
    body = "".join(_render_row(r) for r in rows)
    return (
        "<!doctype html><html lang=\"uz\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{_e(title)}</title><style>{REVIEW_CSS}</style></head>"
        f'<body data-storage-key="voocab-cald-pilot:{_e(store)}" data-run="{_e(store)}">'
        f'<header class="top"><h1>{_e(title)}</h1><span class="stats">{_e(stats)}</span>'
        '<span class="stats">Javob berildi / answered: <b id="progress">0</b></span>'
        '<select id="filter"><option value="all">Hammasi / all</option>'
        '<option value="todo">Javobsiz / not answered yet</option>'
        '<option value="mapped">Mos / mapped</option><option value="none">Yo\'q / none</option>'
        '<option value="unanswered">Model javob bermagan / no model answer</option>'
        '<option value="high">high</option><option value="medium">medium</option>'
        '<option value="low">low</option>'
        '<option value="flagged">v1 hakam: farq/aniq emas / v1 judge flagged</option>'
        '<option value="kept">v2 kept</option><option value="adjusted">v2 adjusted</option>'
        '<option value="replaced">v2 replaced</option>'
        '<option value="keep-old">v2 taqqoslash: eski qoladi / compare: keep old</option>'
        '<option value="disputed">v2 taqqoslash: bahsli / compare: disputed</option></select>'
        '<button id="export" type="button">Javoblarni yuklab olish / Export answers</button></header>'
        '<main><p class="intro">Har bir qator — bizning bitta ma\'nomiz. Model Cambridge ma\'nolaridan '
        'birini tanladi (yoki “yo\'q” dedi). Javoblar shu brauzerda saqlanadi; tugatgach '
        '“Export answers” tugmasini bosing. / Each row is one of our senses; the model chose one '
        'Cambridge sense (or none). Answers are kept in this browser; press “Export answers” when '
        f'done.</p>{body}</main><script>{REVIEW_JS}</script></body></html>'
    )


def cmd_review_export(out: Path = REVIEW_PATH, out_dir: Path = PRIVATE_DIR) -> None:
    sample = load_sample(out_dir)
    log = DecisionLog(out_dir / DECISIONS_FILE)
    index = CaldIndex(load_index_data(out_dir))
    rows = review_rows(sample, log, index)
    round_tag = "r2" if any(r["v2"] for r in rows) else ""
    out.write_text(render_review(rows, run_id=sample["run_id"], round_tag=round_tag),
                   encoding="utf-8")
    print(f"wrote {out} ({len(rows)} rows: {dict(Counter(r['decision'] for r in rows))}"
          f"{', round ' + round_tag if round_tag else ''})")


DUMP_FILE = "pilot_round2.txt"


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _pair_plain(uz: str, alt: str) -> str:
    if not uz:
        return "-"
    return uz + (f"  |  alt: {alt}" if alt and alt != uz else "")


def render_dump(rows: list[dict]) -> str:
    """The round-2 review as plain text, one block per row: lemma, pos, the
    CALD definition (guideword, pointer), the passage sentence (<= 100
    characters), old / v1 / v2 Uzbek, the v2 flag and the comparison
    verdicts. Lives in the private directory -- it is CALD text."""
    blocks = []
    for row in rows:
        head = (f"#{row['n']} {row['lemma']} ({row['pos'] or '?'})  [{row['stratum']}]  "
                f"map: {row['decision']}{' ' + row['confidence'] if row['confidence'] else ''}")
        lines = [head]
        if row["decision"] == "mapped":
            cald = row["cald"]
            gw = f"[{cald['gw']}] " if cald["gw"] else ""
            lines.append(f"  CALD:    {gw}{cald['def']}  ({row['ref']}; CEFR {cald['level'] or '-'}"
                         f" vs ours {row['old_cefr'] or '-'})")
            if row.get("pointer"):
                lines.append(f"  pointer: \"{row['pointer']['def']}\" ({row['pointer']['ref']}) followed")
        else:
            if row.get("pointer"):
                lines.append(f"  pointer: \"{row['pointer']['def']}\" ({row['pointer']['ref']})")
            lines.append(f"  reason:  {row['reason']}")
        lines.append(f"  ours:    {_clip(row['old_def'], 160)}")
        if row["example"]:
            lines.append(f"  example: {_clip(row['example'], 100)}")
        lines.append(f"  old uz:  {_pair_plain(row['old_uz'], row['old_alt'])}")
        if row["decision"] == "mapped":
            lines.append(f"  v1 uz:   {_pair_plain(row['v1_uz'], row['v1_alt'])}   "
                         f"(v1 judge old={row['old_verdict']} new={row['new_verdict']})")
            v2 = row.get("v2")
            if v2:
                lines.append(f"  v2 uz:   {_pair_plain(v2['uz'], v2['alt'])}")
                lines.append(f"  flag:    {v2['flag'] or '-'} -- {v2['reason']}"
                             + (f"   (alt: {v2['alt_flag']} -- {v2['alt_reason']})"
                                if v2.get("alt_flag") else ""))
                for judge, c in v2["compare"].items():
                    flags = f" [{', '.join(c['flags'])}]" if c["flags"] else ""
                    lines.append(f"  judge:   {judge}: better new {c['new_better']} / old "
                                 f"{c['old_better']} / equal {c['equal']} of {c['runs']}; wrong "
                                 f"old {c['wrong_old']}, wrong new {c['wrong_new']} -> keep "
                                 f"{c['keep']}{flags}")
                    for reason in c.get("reasons", []):
                        if reason:
                            lines.append(f"           · {_clip(reason, 160)}")
            else:
                lines.append("  v2 uz:   (not run)")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def cmd_dump(out: Path | None = None, out_dir: Path = PRIVATE_DIR) -> None:
    sample = load_sample(out_dir)
    log = DecisionLog(out_dir / DECISIONS_FILE)
    index = CaldIndex(load_index_data(out_dir))
    out = out or out_dir / DUMP_FILE
    out.write_text(render_dump(review_rows(sample, log, index)), encoding="utf-8")
    print(f"wrote {out}")


# --- Phase 2a: revalidate the pilot, the full run, apply, restore -----------------------

#: The pilot's map key (MAP_VERSION 2: refs, not content) -- read only, to
#: find the pilot's records when carrying them forward.
_PILOT_MAP_VERSION = 2


def _pilot_map_key(item: dict) -> str:
    return (f"{item['sense_id']}|"
            f"{_hash(_PILOT_MAP_VERSION, item['refs'], item['definition_en'], item['example'])}")


def _pilot_xref_key(item: dict, pointer_ref: str, candidates: list[str]) -> str:
    return f"{item['sense_id']}|{pointer_ref}|{_hash(candidates)}"


_LOG_FIELDS = ("kind", "key", "at")


def revalidate_pilot(sample: dict, log: DecisionLog, old: CaldIndex, new: CaldIndex) -> Counter:
    """Carry the pilot's map (and pointer-follow) answers into the full run
    ONLY where the question is provably the same under the corrected source:
    the lexeme's candidate refs are the same list AND every candidate --
    headword, pos, guideword, definition, phrase, pointer-ness -- reads the
    same in the old index and the new (:func:`candidate_fingerprints`), and
    the chosen sense's definition is the one the record was answered with.
    A ref whose definition changed or moved is NOT trusted: the sense is
    left for ``map --all`` to ask again. Carried records keep the answer and
    say ``carried_from``; nothing is paid. Translation and comparison
    records need no carrying -- their keys already hold the CALD text."""
    counts: Counter = Counter()
    for item in sample["items"]:
        record = log.get("map", _pilot_map_key(item))
        if record is None:
            counts["no pilot record"] += 1
            continue
        new_refs = new.match(item["lemma"], item["pos"]).refs[:MAX_CANDIDATES]
        if new_refs != item["refs"]:
            counts["re-ask: candidates changed"] += 1
            continue
        if not all(r in old.senses for r in item["refs"]):
            counts["re-ask: not in the old index"] += 1
            continue
        old_cands, new_cands = old.candidates(item["refs"]), new.candidates(new_refs)
        if candidate_fingerprints(old_cands) != candidate_fingerprints(new_cands):
            counts["re-ask: a candidate's content changed"] += 1
            continue
        chosen = record.get("ref")
        if chosen and record.get("cald_definition") not in (None, new.senses[chosen][1]["def"]):
            counts["re-ask: the chosen definition changed"] += 1
            continue
        key = map_key(item, new_cands)
        if log.get("map", key) is None:
            log.put("map", key, {**{k: v for k, v in record.items() if k not in _LOG_FIELDS},
                                 "carried_from": record["key"]})
            counts["carried"] += 1
        else:
            counts["already carried"] += 1
        if chosen and new.senses[chosen][1].get("xref_only"):
            old_targets = pointer_candidates(old, chosen, item["pos"])
            new_targets = pointer_candidates(new, chosen, item["pos"])
            followed = log.get("xref", _pilot_xref_key(item, chosen, old_targets))
            same = (followed is not None and old_targets == new_targets
                    and all(r in old.senses for r in old_targets)
                    and candidate_fingerprints(old.candidates([chosen, *old_targets]))
                    == candidate_fingerprints(new.candidates([chosen, *new_targets])))
            if same:
                xkey = xref_key(item, chosen, new_targets, new)
                if log.get("xref", xkey) is None:
                    log.put("xref", xkey, {**{k: v for k, v in followed.items()
                                              if k not in _LOG_FIELDS},
                                           "carried_from": followed["key"]})
                counts["pointer carried"] += 1
            else:
                counts["pointer re-ask"] += 1
    return counts


def cmd_revalidate(old_index: Path, out_dir: Path = PRIVATE_DIR) -> None:
    sample = load_sample(out_dir)
    log = DecisionLog(out_dir / DECISIONS_FILE)
    with gzip.open(old_index, "rt", encoding="utf-8") as fh:
        old = CaldIndex(json.load(fh))
    new = CaldIndex(load_index_data(out_dir))
    counts = revalidate_pilot(sample, log, old, new)
    print(f"pilot decisions against the corrected source: {dict(counts)}")


def _progress(step: str, done: int, total: int) -> None:
    print(f"  {step}: {done}/{total}", flush=True)


async def _full_run(step: str, *, budget_usd: float, concurrency: int, judge: str,
                    limit: int | None = None, out_dir: Path = PRIVATE_DIR) -> None:
    """``map --all`` (step ``map``), ``verify --all`` (``verify``: the
    far-levelled mappings asked again) or ``translate --v2 --all``
    (``translate``: pointers, re-verify, both translators, the comparison
    judge). Read-only on the database; every answer logged as it comes;
    stops at the budget."""
    from app.services import lexicon_cald as engine
    from app.services import lexicon_enrich as le

    index = CaldIndex(load_index_data(out_dir))
    log = DecisionLog(out_dir / DECISIONS_FILE)
    items = await engine.load_items(index, log=log)
    matched = [i for i in items if i["refs"]]
    print(f"{len(items)} senses, {len(matched)} with CALD candidates")
    if limit:
        matched = matched[:limit]
        print(f"--limit: the first {len(matched)} of them only")
    usage = le.UsageLog()
    gemini = le.Gemini(usage)
    budget = engine.Budget(limit=budget_usd, before=engine.logged_spend(out_dir), usage=usage)
    print(f"CALD spend so far ${budget.before:.4f}, budget ${budget_usd:.2f}")
    try:
        if step == "map":
            counts = await engine.run_map(matched, index, log, gemini, budget=budget,
                                          concurrency=concurrency, progress=_progress)
            print(f"map: {dict(counts)}")
        elif step == "verify":
            counts = await engine.run_verify(matched, index, log, gemini, judge, budget=budget,
                                             concurrency=concurrency, progress=_progress)
            print(f"re-verify ({judge}): {dict(counts)}")
        else:
            budget.check()
            followed = await follow_pointers({"items": matched}, log, index, gemini,
                                             le.MODEL_MAIN, keyed=True, concurrency=concurrency)
            print(f"pointers: {dict(followed)}")
            counts = await engine.run_verify(matched, index, log, gemini, judge, budget=budget,
                                             concurrency=concurrency, progress=_progress)
            print(f"re-verify ({judge}): {dict(counts)}")
            entries = engine.v2_entries(matched, index, log, judge)
            print(f"{len(entries)} senses take a CALD definition")
            counts = await engine.run_translate(entries, log, gemini, budget=budget,
                                                concurrency=concurrency, progress=_progress)
            print(f"translate v2: {dict(counts)}")
            pairs = engine.compare_entries(entries, log)
            counts = await engine.run_compare(pairs, log, gemini, judge, budget=budget,
                                              concurrency=concurrency, progress=_progress)
            print(f"compare ({judge}): {len(pairs)} pairs, {dict(counts)}")
    except engine.BudgetExceeded as exc:
        print(f"STOPPED: {exc}")
    finally:
        await gemini.aclose()
        engine.record_usage(out_dir, f"{step}-all", usage)
        for model, u in usage.by_model.items():
            print(f"  {model:24} {u.requests:5} req ({u.failures} failed)  in {u.input_tokens:10,}"
                  f"  out {u.output_tokens:9,}  ${model_cost(model, u):.4f}")
        print(f"  this run ${engine.usage_cost(usage):.4f}; CALD total ${budget.spent():.4f}")
    if step in ("map", "verify"):
        plans = engine.plan_items(matched, index, log, judge)
        print(f"effective mapping now: {dict(Counter(p.decision for p in plans))}")
    if step in ("verify", "translate"):
        plans = engine.plan_items(matched, index, log, judge)
        report = render_verify_report(plans, index)
        (out_dir / VERIFY_REPORT_FILE).write_text(report, encoding="utf-8")
        print("\n".join(report.splitlines()[:8]))
        print(f"written: {out_dir / VERIFY_REPORT_FILE}")


VERIFY_REPORT_FILE = "verify_report.txt"
VERIFY_EXAMPLES = 20


def render_verify_report(plans, index: CaldIndex) -> str:
    """The re-verification's outcome -- PRIVATE (CALD text): counts, and up to
    :data:`VERIFY_EXAMPLES` senses per outcome with both definitions, both
    levels and the two runs' reasons."""
    from app.services import lexicon_cald as engine

    asked = [p for p in plans if p.verify is not None or p.decision == "unverified"]
    outcome = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for plan in asked:
        why = (plan.verify or {}).get("why") or "not asked yet"
        outcome[why] += 1
        if len(examples[why]) >= VERIFY_EXAMPLES or not plan.verify:
            continue
        item = plan.item
        record = plan.verify
        ref = record.get("ref") or ""
        block, sense = index.senses[ref] if ref in index.senses else ({"gw": ""}, {"def": "?",
                                                                                "level": None})
        reasons = " | ".join(f"{r['verdict']}: {r['reason']}" for r in record.get("per_run") or []
                             if r)
        examples[why].append(
            f"{item['lemma']} ({item['pos'] or '?'}) ours {item['cefr'] or '-'}"
            f" -> CALD {sense['level'] or '-'} [{ref}]\n"
            f"      ours: {item['definition_en']}\n"
            f"      CALD: {'[' + block['gw'] + '] ' if block['gw'] else ''}{sense['def']}\n"
            f"      runs: {reasons}")
    lines = ["CALD re-verification report -- PRIVATE (CALD text). Not committed.",
             f"built {datetime.now(timezone.utc).isoformat()}",
             f"mapped senses whose CALD level is {engine.VERIFY_BANDS}+ bands from ours: "
             f"{len(asked)}",
             f"  kept (same in both runs, or same + unsure): {outcome.get('same', 0)}",
             f"  dropped -- 'different' in a run: {outcome.get('different', 0)}",
             f"  dropped -- 'unsure' in both runs: {outcome.get('unsure', 0)}",
             f"  undecided (a run missing; asked again next time): "
             f"{outcome.get('incomplete', 0) + outcome.get('not asked yet', 0)}"]
    for why in ("different", "unsure", "same"):
        lines += ["", f"== {why}: up to {VERIFY_EXAMPLES} examples"]
        lines += [f"  {line}" for line in examples.get(why, [])]
    return "\n".join(lines) + "\n"


def _database_name() -> str:
    from sqlalchemy.engine import make_url

    from app.core.config import settings

    return make_url(settings.database_url).database or ""


async def _plan_from_db(judge: str, out_dir: Path = PRIVATE_DIR):
    from app.services import lexicon_cald as engine

    index = CaldIndex(load_index_data(out_dir))
    log = DecisionLog(out_dir / DECISIONS_FILE)
    async with readonly_connection() as conn:
        items = await engine.load_items(index, conn=conn, log=log)
        plans = engine.plan_items(items, index, log, judge)
        mapped = [p.sense_id for p in plans if p.decision == "mapped"]
        levels = await engine.load_material_levels(mapped, conn=conn)
    return index, plans, levels


async def cmd_apply(confirm_db: str | None, judge: str, out_dir: Path = PRIVATE_DIR) -> None:
    """Dry run (read only, the default) or, with ``--confirm-db`` naming the
    database ``DATABASE_URL`` points at, the write. Either way the summary
    of what the plan does is printed first."""
    from app.core.database import async_session_factory
    from app.services import lexicon_cald as engine

    database = _database_name()
    _, plans, levels = await _plan_from_db(judge, out_dir)
    print(f"database {database!r}: {'APPLY' if confirm_db else 'dry run (read only)'}")
    engine.print_summary(engine.summarise(plans, levels))
    if not confirm_db:
        print("nothing written; pass --confirm-db <name> to write")
        return
    if confirm_db != database:
        raise SystemExit(f"--confirm-db {confirm_db!r} is not the database DATABASE_URL points at "
                         f"({database!r}); nothing written")
    async with async_session_factory() as session:
        counts = await engine.apply_plans(session, plans)
        await session.commit()
    print(f"applied: {dict(counts)}")
    lexemes = {uuid.UUID(p.item["lexeme_id"]) for p in plans if p.decision == "mapped"}
    async with async_session_factory() as session:
        await engine.recompute_letter_hints(session, lexemes)
    print(f"needs_letter_hint recomputed ({len(lexemes)} lexemes touched)")


async def cmd_restore(sense_ids: list[str] | None, confirm_db: str | None) -> None:
    from sqlalchemy import text

    from app.core.database import async_session_factory
    from app.services import lexicon_cald as engine

    database = _database_name()
    async with readonly_connection() as conn:
        where = "cald_applied_at is not null"
        count = (await conn.execute(text(f"select count(*) from lexeme_senses where {where}"))
                 ).scalar_one()
    print(f"database {database!r}: {count} senses carry a CALD definition; restoring "
          f"{'all' if sense_ids is None else len(sense_ids)}")
    if confirm_db != database:
        raise SystemExit(f"pass --confirm-db {database!r} to write (got {confirm_db!r}); "
                         f"nothing written")
    async with async_session_factory() as session:
        counts, lexemes = await engine.restore_senses(session, sense_ids)
        await session.commit()
    print(f"restored: {dict(counts)}")
    async with async_session_factory() as session:
        await engine.recompute_letter_hints(session, lexemes)
    print("needs_letter_hint recomputed")


# --- The masking report (no code change: numbers for the owner) ------------------------

MASKING_REPORT_FILE = "masking_report.txt"
MASKING_EXAMPLES = 30
_INFLECTION_ENDINGS = ("s", "es", "ed", "d", "ing", "er", "ers", "est", "ies", "ied", "ly")


def masking_categories(definition: str, lemma: str) -> tuple[set[str], str, int, int]:
    """Which kinds of word `practice._mask_definition` blanks in
    ``definition`` for ``lemma`` (as the definition-kind gap asks it: the
    answer is the lemma itself): ``headword`` (the lemma, or the lemma with
    an inflectional ending; a phrase named whole), ``family`` (another word
    sharing the 5-letter prefix rule -- a derivational relative), and
    ``component`` (one word of a multi-word or hyphenated lemma). Returns
    ``(categories, masked text, mask count, words left)``."""
    from app.services import practice

    masked, count, remaining = practice._mask_definition(definition, lemma, lemma)
    cats: set[str] = set()
    if not count:
        return cats, masked, count, remaining
    components = practice._phrase_components(lemma)
    text = definition
    if len(components) > 1 and practice._find_surface(text, lemma) is not None:
        cats.add("headword")
    for word in practice._DEFINITION_WORD_RE.findall(text):
        low = word.lower()
        if len(components) > 1:
            if any(practice._matches_lemma_family(word, part) for part in components):
                cats.add("component")
            continue
        if not practice._matches_lemma_family(word, lemma):
            continue
        base = lemma.lower()
        stem = base[:-1] if base.endswith(("e", "y")) else base
        if low == base or any(low in (base + e, stem + e, base + base[-1:] + e)
                              for e in _INFLECTION_ENDINGS):
            cats.add("headword")
        else:
            cats.add("family")
    return cats, masked, count, remaining


def render_masking_report(plans) -> str:
    from app.services import practice

    def tally(pairs):
        counts: Counter = Counter()
        examples: dict[str, list[str]] = defaultdict(list)
        for plan, definition in pairs:
            cats, masked, count, remaining = masking_categories(definition, plan.item["lemma"])
            counts["definitions"] += 1
            if count:
                counts["masked (any)"] += 1
            if practice._needs_readability_fallback(count, remaining) and count:
                counts["readability fallback (recall -> recognise)"] += 1
            for cat in sorted(cats):
                counts[cat] += 1
                if len(examples[cat]) < MASKING_EXAMPLES:
                    examples[cat].append(f"{plan.item['lemma']} ({plan.item['pos'] or '?'}): "
                                         f"{definition}\n      -> {masked}")
        return counts, examples

    mapped = [p for p in plans if p.decision == "mapped"]
    new_counts, examples = tally([(p, p.definition) for p in mapped])
    old_counts, _ = tally([(p, p.item["definition_en"]) for p in mapped])
    lines = ["CALD masking report -- PRIVATE (CALD text). Not committed.",
             f"built {datetime.now(timezone.utc).isoformat()}",
             "",
             "practice._mask_definition(definition, lemma, lemma) -- the definition-kind gap,",
             "where the answer is the lemma. Categories (a definition may be in several):",
             "  headword  -- the lemma itself, an inflected form of it, or a phrase lemma named whole",
             "  family    -- another word passing the 5-letter-prefix family rule (derivational)",
             "  component -- one word of a multi-word / hyphenated lemma",
             "",
             f"{'':44}{'CALD (would-be)':>16}{'ours (before)':>16}"]
    for key in ("definitions", "masked (any)", "headword", "family", "component",
                "readability fallback (recall -> recognise)"):
        lines.append(f"  {key:42}{new_counts.get(key, 0):>16}{old_counts.get(key, 0):>16}")
    for cat in ("headword", "family", "component"):
        lines += ["", f"== {cat}: {MASKING_EXAMPLES} examples (CALD definition -> masked)"]
        lines += [f"  {line}" for line in examples.get(cat, [])]
    return "\n".join(lines) + "\n"


async def cmd_masking_report(judge: str, out_dir: Path = PRIVATE_DIR) -> None:
    _, plans, _ = await _plan_from_db(judge, out_dir)
    report = render_masking_report(plans)
    path = out_dir / MASKING_REPORT_FILE
    path.write_text(report, encoding="utf-8")
    print("\n".join(report.splitlines()[:20]))
    print(f"written: {path}")


# --- backup --------------------------------------------------------------------------


def cmd_backup(out_dir: Path = PRIVATE_DIR, review: Path = REVIEW_PATH) -> Path:
    """Copy the private directory (and the pilot's review page) to
    ``~/voocab-dev-backups/cald-<date>/``: gitignored means no clone, push or
    other checkout has it, so the only copy would otherwise be this
    worktree's."""
    target = BACKUP_ROOT / f"cald-{datetime.now(timezone.utc).date().isoformat()}"
    shutil.copytree(out_dir, target, dirs_exist_ok=True)
    if review.exists():
        shutil.copy2(review, target / review.name)
    print(f"backed up to {target}")
    return target


# --- Main ------------------------------------------------------------------------------


async def main() -> None:
    from app.services import lexicon_cald as engine

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    ix = sub.add_parser("index")
    ix.add_argument("--source", type=Path, required=True)
    sub.add_parser("match")
    rv_ = sub.add_parser("revalidate", help="carry the pilot's answers where still valid")
    rv_.add_argument("--old-index", type=Path, required=True)
    mp = sub.add_parser("map")
    which = mp.add_mutually_exclusive_group(required=True)
    which.add_argument("--sample", type=int)
    which.add_argument("--all", action="store_true")
    mp.add_argument("--seed", type=int, default=7)
    mp.add_argument("--resample", action="store_true")
    vf = sub.add_parser("verify", help="ask again: far-levelled mappings, same meaning?")
    vf.add_argument("--all", action="store_true", required=True)
    vf.add_argument("--judge-model", default=engine.JUDGE_MODEL)
    tr = sub.add_parser("translate")
    which = tr.add_mutually_exclusive_group(required=True)
    which.add_argument("--sample", type=int)
    which.add_argument("--all", action="store_true")
    tr.add_argument("--v2", action="store_true",
                    help="round 2: follow pointers, v2 prompt, comparison judge")
    tr.add_argument("--judge-model", dest="judge_models", action="append",
                    help="comparison judge model(s) for --v2; --all takes one (default "
                         f"{engine.JUDGE_MODEL}), --sample defaults to lexicon_enrich.MODEL_JUDGE")
    for p in (mp, tr, vf):
        p.add_argument("--limit", type=int, help="--all: only the first N senses (a smoke test)")
        p.add_argument("--concurrency", type=int, default=12)
        p.add_argument("--budget", type=float, default=engine.DEFAULT_BUDGET_USD,
                       help="stop when the CALD total in usage.jsonl reaches this (USD)")
    ap = sub.add_parser("apply", help="dry run unless --confirm-db names the database")
    ap.add_argument("--confirm-db")
    rs = sub.add_parser("restore")
    which = rs.add_mutually_exclusive_group(required=True)
    which.add_argument("--all", action="store_true")
    which.add_argument("--sense-id", dest="sense_ids", action="append")
    rs.add_argument("--confirm-db")
    sub.add_parser("masking-report")
    for p in (ap, sub.choices["masking-report"]):
        p.add_argument("--judge-model", default=engine.JUDGE_MODEL)
    dp = sub.add_parser("dump")
    dp.add_argument("--out", type=Path)
    rv = sub.add_parser("review-export")
    rv.add_argument("--out", type=Path, default=REVIEW_PATH)
    sub.add_parser("backup")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if args.cmd == "index":
        index = build_index(args.source.expanduser())
        blocks = sum(len(b) for b in index["headwords"].values())
        senses = sum(len(b["senses"]) for bs in index["headwords"].values() for b in bs)
        levelled = sum(1 for bs in index["headwords"].values() for b in bs for s in b["senses"]
                       if s["level"])
        print(f"index: {len(index['headwords'])} headwords, {blocks} blocks, {senses} defined "
              f"senses ({levelled} with a CEFR level), {len(index['aliases'])} aliases, "
              f"{len(index['pron'])} pronounced headwords -> {PRIVATE_DIR / INDEX_FILE}")
    elif args.cmd == "match":
        await cmd_match()
    elif args.cmd == "revalidate":
        cmd_revalidate(args.old_index.expanduser())
    elif args.cmd == "map" and args.all:
        await _full_run("map", budget_usd=args.budget, concurrency=args.concurrency,
                        judge=engine.JUDGE_MODEL, limit=args.limit)
    elif args.cmd == "map":
        await cmd_map(args.sample, args.seed, args.resample)
    elif args.cmd == "verify":
        await _full_run("verify", budget_usd=args.budget, concurrency=args.concurrency,
                        judge=args.judge_model, limit=args.limit)
    elif args.cmd == "translate" and args.all:
        if not args.v2:
            raise SystemExit("the full run translates with --v2 only")
        judges = args.judge_models or [engine.JUDGE_MODEL]
        if len(judges) != 1:
            raise SystemExit("--all takes one --judge-model")
        await _full_run("translate", budget_usd=args.budget, concurrency=args.concurrency,
                        judge=judges[0], limit=args.limit)
    elif args.cmd == "translate" and args.v2:
        from app.services import lexicon_enrich as le

        await cmd_translate_v2(args.sample, args.judge_models or [le.MODEL_JUDGE])
    elif args.cmd == "translate":
        await cmd_translate(args.sample)
    elif args.cmd == "apply":
        await cmd_apply(args.confirm_db, args.judge_model)
    elif args.cmd == "restore":
        await cmd_restore(None if args.all else args.sense_ids, args.confirm_db)
    elif args.cmd == "masking-report":
        await cmd_masking_report(args.judge_model)
    elif args.cmd == "dump":
        cmd_dump(args.out)
    elif args.cmd == "review-export":
        cmd_review_export(args.out)
    elif args.cmd == "backup":
        cmd_backup()


if __name__ == "__main__":
    asyncio.run(main())
