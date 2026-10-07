"""One-off lexicon fixes (2026-09-28, extended 2026-09-29), each a
subcommand, each re-runnable.

Run from ``backend/``::

    uv run python -m scripts.lexicon_cleanup ngsl            # step 1
    uv run python -m scripts.lexicon_cleanup proper-nouns --classify out.json
    uv run python -m scripts.lexicon_cleanup proper-nouns --apply out.json
    uv run python -m scripts.lexicon_cleanup stale-oewn      # names left as OEWN senses
    uv run python -m scripts.lexicon_cleanup list-only       # step 2a
    uv run python -m scripts.lexicon_cleanup rejudge         # step 3
    uv run python -m scripts.lexicon_cleanup retranslate --trial   # step 4
    uv run python -m scripts.lexicon_cleanup retranslate --decide  # step 4
    uv run python -m scripts.lexicon_cleanup hide-proper-nouns        # A
    uv run python -m scripts.lexicon_cleanup function-words --apply   # C2
    uv run python -m scripts.lexicon_cleanup wordnet-provenance       # B
    uv run python -m scripts.lexicon_cleanup restore-retranslation \\
        --file app/data/lexicon_trials/retranslate-2026-09-29.json    # C1

Every model call goes through `app.services.lexicon_enrich`'s own client and
steps, so the prompts, retries and cost accounting are production's. The
four added 2026-09-29 (`hide-proper-nouns`, `function-words`,
`wordnet-provenance`, `restore-retranslation`) make no model call at all.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import delete as sa_delete
from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlalchemy import update as sa_update
from sqlmodel import select

from app.core.database import async_session_factory
from app.models.lexicon import (
    LOCKED_DEFINITION_SOURCES,
    Lexeme,
    LexemeSense,
    TranslationReport,
)
from app.models.vocabulary import LookupEvent, MaterialVocabulary, SavedWord
from app.services import lexicon_enrich as le
from app.services import lexicon_hints
from app.services.lexicon import is_excluded_word

logger = logging.getLogger("scripts.lexicon_cleanup")


def print_usage(usage: le.UsageLog) -> None:
    for model, u in usage.by_model.items():
        print(f"  {model:24} {u.requests:5} req ({u.failures} failed)  "
              f"in {u.input_tokens:9,}  out {u.output_tokens:8,}  ${u.cost(model):.4f}")
    print(f"  total ${usage.total_cost():.4f}")


async def _reason_counts(session) -> Counter:
    rows = (await session.exec(sa_select(LexemeSense.review_reasons))).scalars().all()
    return Counter(r for reasons in rows for r in reasons)


def _is_locked(sense: LexemeSense) -> bool:
    """A CALD sense or a reviewer's rewrite of one (`LOCKED_DEFINITION_SOURCES`):
    none of these one-off commands may rewrite, strip or delete it. Run
    `scripts/cald.py restore` first if one really must be redone."""
    return sense.definition_source in LOCKED_DEFINITION_SOURCES


async def _locked_senses(session, lexeme_id: uuid.UUID) -> int:
    """How many of the lexeme's senses are locked (`_is_locked`)."""
    return (await session.exec(sa_select(func.count()).select_from(LexemeSense).where(
        LexemeSense.lexeme_id == lexeme_id,
        LexemeSense.definition_source.in_(LOCKED_DEFINITION_SOURCES)))).scalar_one()


def _set_reasons(sense: LexemeSense, reasons: list[str]) -> None:
    sense.review_reasons = list(dict.fromkeys(reasons))
    sense.needs_review = bool(sense.review_reasons)


# --- Step 1: ngsl_conflict ------------------------------------------------------


async def recompute_ngsl() -> None:
    """``ngsl_conflict`` recomputed on every sense with the narrowed rule
    (`lexicon_enrich.ngsl_conflict`), rank 1 only; nothing else touched."""
    async with async_session_factory() as session:
        before = (await _reason_counts(session))["ngsl_conflict"]
        rows = (await session.exec(
            select(LexemeSense, Lexeme.frequency_band, Lexeme.is_proper_noun)
            .join(Lexeme, Lexeme.id == LexemeSense.lexeme_id)
        )).all()
        changed = 0
        for sense, band, proper in rows:
            want = (sense.sense_rank == 1 and not proper
                    and le.ngsl_conflict(sense.cefr, band))
            has = "ngsl_conflict" in sense.review_reasons
            if want == has:
                continue
            reasons = [r for r in sense.review_reasons if r != "ngsl_conflict"]
            if want:
                reasons.append("ngsl_conflict")
            _set_reasons(sense, reasons)
            session.add(sense)
            changed += 1
        await session.commit()
        after = (await _reason_counts(session))["ngsl_conflict"]
    print(f"ngsl_conflict: {before} -> {after} ({changed} senses changed)")


# --- Step 2b: proper nouns --------------------------------------------------------

PROPER_PROMPT = """Below are headwords from an English learner's dictionary,
each with its part of speech, its main definition and, where the word was
met in reading passages, how it was written there.

Which of them are PROPER NOUNS -- the name of one specific person, place,
organisation, company, brand or product, event, ship, work or deity (Alan,
Google, Texas, Nasdaq, Brexit)? A headword whose definition describes a
specific named thing ("a male given name", "a specific technology company")
is one.

These are NOT proper nouns: days, months, languages, nationalities and their
adjectives (German, Monday, English), common nouns and verbs that began as
names (google = to search the web, sandwich), abbreviations of ordinary
words (DNA, TV), and any ordinary word whose definition here happens to be
a strange rare sense.

{items}

Reply with JSON only: {{"proper": ["w3", "w17"]}} -- the ids of the proper
nouns only; [] if none."""


def _parse_proper(text: str) -> dict | None:
    """``{"proper": [...]}``, or a bare list -- ``[]`` is a real "none"."""
    value = le._json_value(text)
    if isinstance(value, list):
        return {"proper": value}
    return value if isinstance(value, dict) and isinstance(value.get("proper"), list) else None


async def classify_proper(out: Path, batch: int = 150) -> None:
    async with async_session_factory() as session:
        lexemes = (await session.exec(select(Lexeme).order_by(Lexeme.lemma, Lexeme.pos))).all()
        firsts = {s.lexeme_id: s for s in (await session.exec(
            select(LexemeSense).where(LexemeSense.sense_rank == 1))).all()}
        surfaces: dict = defaultdict(Counter)
        for lexeme_id, surface in (await session.exec(
                select(MaterialVocabulary.lexeme_id, MaterialVocabulary.surface))).all():
            surfaces[lexeme_id][surface] += 1
    usage = le.UsageLog()
    gemini = le.Gemini(usage)
    found: dict[str, dict] = {}

    def line(i: int, lx: Lexeme) -> str:
        sense = firsts.get(lx.id)
        seen = ", ".join(f"{w} x{n}" for w, n in surfaces[lx.id].most_common(3))
        return (f"w{i}: {lx.lemma} ({lx.pos or '?'}) -- "
                f"{(sense.definition_en if sense else '')[:160]}"
                + (f"  [written: {seen}]" if seen else ""))

    async def one(chunk: list[Lexeme]) -> None:
        text = "\n".join(line(i, lx) for i, lx in enumerate(chunk, 1))
        reply = await gemini.ask(le.MODEL_MAIN, PROPER_PROMPT.format(items=text),
                                 step="proper", max_tokens=3000, parse=_parse_proper)
        ids = reply.get("proper") if reply else None
        if not isinstance(ids, list):
            print("  no answer for a batch; re-run to fill it", flush=True)
            return
        for wid in ids:
            if isinstance(wid, str) and wid[1:].isdigit() and 1 <= int(wid[1:]) <= len(chunk):
                lx = chunk[int(wid[1:]) - 1]
                sense = firsts.get(lx.id)
                found[str(lx.id)] = {"lemma": lx.lemma, "pos": lx.pos,
                                     "definition": sense.definition_en if sense else "",
                                     "written": dict(surfaces[lx.id])}

    chunks = [lexemes[i:i + batch] for i in range(0, len(lexemes), batch)]
    semaphore = asyncio.Semaphore(8)

    async def guarded(chunk):
        async with semaphore:
            await one(chunk)

    try:
        await asyncio.gather(*(guarded(c) for c in chunks))
    finally:
        await gemini.aclose()
    out.write_text(json.dumps(found, indent=1, ensure_ascii=False))
    print(f"{len(found)} proper nouns of {len(lexemes)} lexemes -> {out}")
    print_usage(usage)


#: Reasons that only mean something for a graded sense.
CEFR_REASONS = {"ngsl_conflict", "material_level_gap"}


async def _references(session, lexeme_id: uuid.UUID) -> dict[str, int]:
    sense_ids = select(LexemeSense.id).where(LexemeSense.lexeme_id == lexeme_id)
    rows = (await session.exec(sa_select(func.count()).select_from(MaterialVocabulary)
                               .where(MaterialVocabulary.lexeme_id == lexeme_id))).scalar_one()
    saved = (await session.exec(sa_select(func.count()).select_from(SavedWord)
                                .where(SavedWord.lexeme_sense_id.in_(sense_ids)))).scalar_one()
    reports = (await session.exec(sa_select(func.count()).select_from(TranslationReport)
                                  .where(TranslationReport.lexeme_sense_id.in_(sense_ids)))
               ).scalar_one()
    return {"rows": rows, "saved": saved, "reports": reports}


async def delete_lexeme(session, lexeme_id: uuid.UUID) -> bool:
    """A lexeme nothing points at: its senses, then itself. REFUSED (False,
    with a message) when one of its senses is a CALD / reviewed one -- the
    dictionary text and its `*_pre_cald` backup would go with it."""
    if await _locked_senses(session, lexeme_id):
        print(f"  not deleted, has a CALD/reviewed sense: {lexeme_id}")
        return False
    await session.execute(sa_delete(LexemeSense).where(LexemeSense.lexeme_id == lexeme_id))
    await session.execute(sa_delete(Lexeme).where(Lexeme.id == lexeme_id))
    return True


async def mark_proper(session, lexeme: Lexeme) -> bool:
    """Mark ``lexeme`` a name and null its CEFR. REFUSED (False, with a
    message) when it has a CALD / reviewed sense: nulling its level would
    undo the dictionary's (or the reviewer's) grade."""
    if await _locked_senses(session, lexeme.id):
        print(f"  not marked proper, has a CALD/reviewed sense: {lexeme.lemma}")
        return False
    lexeme.is_proper_noun = True
    lexeme.cefr = None
    session.add(lexeme)
    for sense in (await session.exec(select(LexemeSense).where(
            LexemeSense.lexeme_id == lexeme.id))).all():
        sense.cefr = None
        _set_reasons(sense, [r for r in sense.review_reasons if r not in CEFR_REASONS])
        session.add(sense)
    return True


async def apply_proper(path: Path) -> None:
    """``path``: ``{lexeme_id: {...}}`` -- the reviewed list. No material
    row, no saved word and no report: deleted. Anything else: kept and
    marked (`Lexeme.is_proper_noun`, CEFR NULL on the lexeme and every
    sense, CEFR-based reasons dropped)."""
    wanted = json.loads(path.read_text())
    deleted, marked = [], []
    async with async_session_factory() as session:
        for key, info in wanted.items():
            lexeme = await session.get(Lexeme, uuid.UUID(key))
            if lexeme is None:
                continue
            refs = await _references(session, lexeme.id)
            if not any(refs.values()):
                if await delete_lexeme(session, lexeme.id):
                    deleted.append(lexeme.lemma)
            elif await mark_proper(session, lexeme):
                marked.append((lexeme.lemma, refs))
        await session.commit()
    print(f"deleted {len(deleted)}: {deleted}")
    print(f"marked {len(marked)}: {[m[0] for m in marked]}")
    print(f"  with a saved word: {[m[0] for m in marked if m[1]['saved']]}")


# --- Stale OEWN senses: capitalised-name synsets the loader now drops -------------


async def stale_oewn(apply: bool) -> None:
    """Lexemes WITH material rows holding a sense whose OEWN synset the fixed
    loader no longer lists for their (lemma, pos) -- `Town` the architect as
    `town`'s OEWN top sense. Re-enriched with production's `enrich`, which
    deletes an unused OEWN sense that is no longer the top one and adds the
    real top sense. List-only lexemes are `list-only`'s job."""
    oewn = le.load_oewn()
    async with async_session_factory() as session:
        rows = (await session.exec(
            select(Lexeme.id, Lexeme.lemma, Lexeme.pos, LexemeSense.oewn_synset_id)
            .join(LexemeSense, LexemeSense.lexeme_id == Lexeme.id)
            .where(LexemeSense.oewn_synset_id.is_not(None))
        )).all()
        with_rows = set((await session.exec(
            sa_select(MaterialVocabulary.lexeme_id).distinct())).scalars().all())
    ids = sorted({lid for lid, lemma, pos, syn in rows if lid in with_rows
                  and syn not in {e["synset"] for e in oewn.get((lemma, pos), [])}}, key=str)
    print(f"{len(ids)} material lexemes hold a dropped OEWN synset")
    if not apply or not ids:
        return
    usage = le.UsageLog()
    gemini = le.Gemini(usage)
    try:
        for chunk in [ids[i:i + 10] for i in range(0, len(ids), 10)]:
            await le.enrich(async_session_factory, gemini, chunk, oewn)
        async with async_session_factory() as session:
            await lexicon_hints.recompute_for_lexemes(session, ids)
            await session.commit()
    finally:
        await gemini.aclose()
    print_usage(usage)


# --- Step 2a: list-only lexemes -------------------------------------------------

CHOOSE_PROMPT = """For each English headword below, WordNet lists one main
sense per part of speech and has no frequency data to rank them. Choose the
sense an English learner meets MOST OFTEN in everyday and general reading.

{items}

Reply with JSON only: {{"pick": {{"w1": "n", "w2": "v", ...}}}}"""


async def _choose_pos(gemini, lemmas: list[tuple[str, list[tuple[str, dict]]]]) -> dict[str, str]:
    picks: dict[str, str] = {}
    for chunk in [lemmas[i:i + 40] for i in range(0, len(lemmas), 40)]:
        text = "\n".join(
            f"w{i}: {lemma}\n" + "\n".join(f"    {pos}: {sense['definition'][:160]}"
                                         for pos, sense in options)
            for i, (lemma, options) in enumerate(chunk, 1))
        reply = await gemini.ask(le.MODEL_MAIN, CHOOSE_PROMPT.format(items=text),
                                 step="choose-pos", max_tokens=2000)
        got = reply.get("pick") if reply and isinstance(reply.get("pick"), dict) else {}
        for i, (lemma, options) in enumerate(chunk, 1):
            pos = str(got.get(f"w{i}") or "").strip().lower()
            if pos in {p for p, _ in options}:
                picks[lemma] = pos
    return picks


async def list_only(apply: bool, out: Path | None) -> None:
    """Step 2a -- see `app.services.lexicon_enrich.top_sense_any_pos`.

    Every lexeme with no material row gets the lemma's most frequent OEWN
    synset across all parts of speech, pos AND definition together, as its
    rank-1 (only) sense; a lemma OEWN does not know gets pos + definition
    from one model request (`GAP_PROMPT`, pos "?"). Where the pos changes
    the lexeme is re-keyed; where (lemma, new pos) already exists the
    list-only duplicate is merged into it (deleted -- it has no rows, and
    the survivor already carries that pos's OEWN top sense). A changed sense
    is graded and translated (two translators, judge twice) as usual."""
    oewn = le.load_oewn()
    index = le.pos_index(oewn)
    usage = le.UsageLog()
    gemini = le.Gemini(usage)
    async with async_session_factory() as session:
        with_rows = set((await session.exec(
            sa_select(MaterialVocabulary.lexeme_id).distinct())).scalars().all())
        lexemes = [lx for lx in (await session.exec(
            select(Lexeme).where(Lexeme.is_proper_noun.is_(False))
            .order_by(Lexeme.lemma, Lexeme.pos))).all() if lx.id not in with_rows]
        senses_of: dict = defaultdict(list)
        for sense in (await session.exec(select(LexemeSense).where(
                LexemeSense.lexeme_id.in_([lx.id for lx in lexemes])))).all():
            senses_of[sense.lexeme_id].append(sense)
        keys = set((await session.exec(select(Lexeme.lemma, Lexeme.pos))).all())
    # A lexeme with a CALD / reviewed sense is left alone: this command
    # deletes `senses[1:]` and rewrites the first.
    skipped = {lx.id: lx for lx in lexemes if any(_is_locked(s) for s in senses_of[lx.id])}
    if skipped:
        print(f"skipped, has a CALD/reviewed sense: {len(skipped)} "
              f"({[lx.lemma for lx in list(skipped.values())[:10]]}...)")
        lexemes = [lx for lx in lexemes if lx.id not in skipped]

    target: dict[uuid.UUID, dict] = {}
    undecided, gaps = [], []
    for lx in lexemes:
        top = le.top_sense_any_pos(oewn, index, lx.lemma)
        if top is None:
            gaps.append(lx)
            continue
        pos, sense, decided = top
        if not decided:
            options = sorted(((p, oewn[(lx.lemma, p)][0]) for p in index[lx.lemma]),
                             key=lambda t: le.POS_PRIORITY.index(t[0])
                             if t[0] in le.POS_PRIORITY else 99)
            undecided.append((lx, options))
            continue
        target[lx.id] = {"pos": pos, "sense": sense, "how": "count"}

    try:
        picks = await _choose_pos(gemini, [(lx.lemma, opts) for lx, opts in undecided])
        for lx, options in undecided:
            pos = picks.get(lx.lemma) or options[0][0]
            target[lx.id] = {"pos": pos, "sense": oewn[(lx.lemma, pos)][0],
                             "how": "model-pick" if lx.lemma in picks else "tie-order"}
        gap_defs: dict[uuid.UUID, tuple[str, str]] = {}
        for chunk in [gaps[i:i + 40] for i in range(0, len(gaps), 40)]:
            words = "\n".join(f"w{i}: {lx.lemma} (?)" for i, lx in enumerate(chunk, 1))
            reply = await gemini.ask(le.MODEL_MAIN, le.GAP_PROMPT.format(words=words),
                                     step="gap", max_tokens=4000)
            defs = reply.get("defs") if reply and isinstance(reply.get("defs"), dict) else {}
            for i, lx in enumerate(chunk, 1):
                item = defs.get(f"w{i}")
                if isinstance(item, dict):
                    pos = str(item.get("pos") or "").strip().lower()
                    gap_defs[lx.id] = (pos if pos in le.POS_WORDS | {"phr"} else "",
                                       str(item.get("def") or "").strip())
        for lx in gaps:
            pos, definition = gap_defs.get(lx.id, ("", ""))
            if definition and pos:
                target[lx.id] = {"pos": pos, "definition": definition, "how": "gap"}

        # What changes.
        report: dict[str, list] = defaultdict(list)
        works: list[le.LexemeWork] = []
        merges: list[Lexeme] = []
        claimed = set(keys)
        for lx in lexemes:
            want = target.get(lx.id)
            senses = sorted(senses_of[lx.id], key=lambda s: s.sense_rank)
            first = senses[0] if senses else None
            if want is None:
                report["no-target" if lx in gaps else "?"].append(lx.lemma)
                continue
            new_pos = want["pos"]
            if "sense" in want:
                same = (first is not None and first.oewn_synset_id == want["sense"]["synset"]
                        and new_pos == lx.pos and len(senses) == 1)
            else:  # gap: only a pos change is a change -- the definition was
                # written by the same request shape the first time
                same = first is not None and new_pos == lx.pos and not first.oewn_synset_id
            if same:
                report[f"unchanged:{want['how']}"].append(lx.lemma)
                continue
            if new_pos != lx.pos and (lx.lemma, new_pos) in claimed:
                merges.append(lx)
                report["merged"].append(f"{lx.lemma} {lx.pos or '?'}->{new_pos}")
                continue
            claimed.discard((lx.lemma, lx.pos))
            claimed.add((lx.lemma, new_pos))
            kind = "pos-change" if new_pos != lx.pos else "def-change"
            report[f"{kind}:{want['how']}"].append(
                f"{lx.lemma} {lx.pos or '?'}->{new_pos}: "
                f"{(first.definition_en if first else '')[:50]!r} -> "
                f"{(want['sense']['definition'] if 'sense' in want else want['definition'])[:50]!r}")
            if "sense" in want:
                planned = le.Sense(
                    id=first.id if first else None,
                    definition_en=want["sense"]["definition"][:le.DEF_MAX],
                    oewn_synset_id=want["sense"]["synset"], oewn_rank=want["sense"]["rank"],
                    oewn_count=want["sense"].get("count", 0),
                    source_id="oewn", licence=le.OEWN_LICENCE, translate=True,
                )
            else:
                planned = le.Sense(id=first.id if first else None,
                                   definition_en=want["definition"][:le.DEF_MAX],
                                   source_id="model", licence=le.MODEL_LICENCE, translate=True)
            if first is not None:
                planned.review_reasons = [r for r in first.review_reasons
                                          if r not in le.COMPUTED_REASONS
                                          and r not in le.MATCH_REASONS]
            work = le.LexemeWork(id=lx.id, lemma=lx.lemma, pos=new_pos, is_phrase=lx.is_phrase,
                                 frequency_band=lx.frequency_band,
                                 oewn=oewn.get((lx.lemma, new_pos), []),
                                 senses=[], rows=[], plan=[planned])
            work.deleted = {s.id: None for s in senses[1:]}
            works.append(work)

        for key in sorted(report):
            print(f"{key}: {len(report[key])}")
        if out:
            out.write_text(json.dumps(report, indent=1, ensure_ascii=False))
        if not apply:
            return

        await le.step_cefr(gemini, works)
        await le.step_translate(gemini, works)
        for work in works:
            le.finalise(work)
        async with async_session_factory() as session:
            for lx in merges:
                refs = await _references(session, lx.id)
                if any(refs.values()):
                    print(f"  not merged, still referenced: {lx.lemma} {refs}")
                    continue
                await delete_lexeme(session, lx.id)  # refuses a CALD/reviewed lexeme
            await session.flush()
            for work in works:
                lexeme = await session.get(Lexeme, work.id)
                lexeme.pos = work.pos
                session.add(lexeme)
                await session.flush()
                await le.apply_work(session, work)
            await session.commit()
            await lexicon_hints.recompute_for_lexemes(session, [w.id for w in works])
            await session.commit()
        notes = Counter(n for w in works for n in w.note.split())
        print(f"written {len(works)}, merged {len(merges)}; notes {dict(notes)}")
    finally:
        await gemini.aclose()
        print_usage(usage)


# --- Step 3: re-judge every translated pair ------------------------------------


async def _judge_rows(gemini, rows, log: Path | None, slice_size: int = 500,
                      parallel: int = 4) -> list[tuple[str | None, str]]:
    """`le.judge_twice` over ``rows`` = ``[(label, definition, a, b)]``, in
    concurrent slices, progress appended to ``log``."""
    results: list = [None] * len(rows)
    semaphore = asyncio.Semaphore(parallel)
    done = 0

    async def one(start: int) -> None:
        nonlocal done
        async with semaphore:
            chunk = rows[start:start + slice_size]
            got = await le.judge_twice(gemini, [
                le.JudgeItem(label=r[0], definition=r[1], a=r[2], b=r[3]) for r in chunk])
            results[start:start + len(chunk)] = got
            done += len(chunk)
            if log:
                with log.open("a") as fh:
                    fh.write(f"{done}/{len(rows)} ${gemini.usage.total_cost():.4f}\n")

    await asyncio.gather(*(one(i) for i in range(0, len(rows), slice_size)))
    return results


def _judge_reasons(reasons: list[str], verdict: str | None) -> list[str]:
    if verdict is None:  # no answer: the earlier verdict stands
        return reasons
    kept = [r for r in reasons if r not in le.JUDGE_REASONS]
    if verdict == "different":
        kept.append("judge_different")
    elif verdict == "unsure":
        kept.append("judge_unsure")
    return kept


async def rejudge(out: Path, log: Path | None) -> None:
    """Every sense with two translations, judged twice with the new prompt
    (`le.JUDGE_PROMPT`, `le.combine_verdicts`); its judge_* reasons replaced
    by the result. The text itself is not touched (no A/B swap)."""
    async with async_session_factory() as session:
        before = await _reason_counts(session)
        pairs = (await session.exec(
            select(LexemeSense, Lexeme.lemma, Lexeme.pos)
            .join(Lexeme, Lexeme.id == LexemeSense.lexeme_id)
            .where(LexemeSense.meaning_uz != "", LexemeSense.meaning_uz_alt != "")
            .order_by(LexemeSense.id)
        )).all()
    print(f"{len(pairs)} translated pairs")
    usage = le.UsageLog()
    gemini = le.Gemini(usage)
    try:
        results = await _judge_rows(gemini, [
            (f"{lemma} ({pos or '?'})", sense.definition_en, sense.meaning_uz_alt,
             sense.meaning_uz) for sense, lemma, pos in pairs], log)
    finally:
        await gemini.aclose()
    verdicts = Counter(v for v, _ in results)
    async with async_session_factory() as session:
        for (sense, _, _), (verdict, _) in zip(pairs, results):
            row = await session.get(LexemeSense, sense.id)
            _set_reasons(row, _judge_reasons(row.review_reasons, verdict))
            session.add(row)
        await session.commit()
        after = await _reason_counts(session)
    out.write_text(json.dumps({str(s.id): v for (s, _, _), (v, _) in zip(pairs, results)}))
    print(f"verdicts: {dict(verdicts)}")
    for reason in ("judge_different", "judge_unsure"):
        print(f"{reason}: {before[reason]} -> {after[reason]}")
    print_usage(usage)


# --- Step 4: re-translate judge_different with the fixed prompt ------------------


async def retranslate_trial(out: Path, log: Path | None) -> None:
    """Every `judge_different` sense: the old pair is stashed in
    ``meaning_uz_prev``/``meaning_uz_alt_prev``, both translators run with the
    fixed prompt, and BOTH pairs are judged twice in the same run (the old
    one re-judged too, so old and new are measured alike -- the old share is
    not simply 100% by selection). Nothing is decided here."""
    async with async_session_factory() as session:
        rows = (await session.exec(
            select(LexemeSense, Lexeme)
            .join(Lexeme, Lexeme.id == LexemeSense.lexeme_id)
            .where(LexemeSense.review_reasons.contains(["judge_different"]),
                   LexemeSense.definition_source.not_in(LOCKED_DEFINITION_SOURCES))
            .order_by(LexemeSense.id)
        )).all()
        for sense, _ in rows:
            if not sense.meaning_uz_prev:
                sense.meaning_uz_prev = sense.meaning_uz
                sense.meaning_uz_alt_prev = sense.meaning_uz_alt
                session.add(sense)
        await session.commit()
    print(f"{len(rows)} judge_different senses; old pairs stashed")
    usage = le.UsageLog()
    gemini = le.Gemini(usage)
    works = []
    for sense, lexeme in rows:
        planned = le.Sense(id=sense.id, definition_en=sense.definition_en, translate=True)
        works.append(le.LexemeWork(id=lexeme.id, lemma=lexeme.lemma, pos=lexeme.pos,
                                   is_phrase=lexeme.is_phrase,
                                   frequency_band=lexeme.frequency_band, oewn=[],
                                   senses=[], rows=[], plan=[planned]))
    try:
        await le.step_translate(gemini, works)  # new pair + its double judge
        old = await _judge_rows(gemini, [
            (f"{lx.lemma} ({lx.pos or '?'})", s.definition_en, s.meaning_uz_alt_prev
             or s.meaning_uz_alt, s.meaning_uz_prev or s.meaning_uz) for s, lx in rows], log)
    finally:
        await gemini.aclose()
    trial = {}
    for (sense, lexeme), work, (old_verdict, _) in zip(rows, works, old):
        new = work.plan[0]
        trial[str(sense.id)] = {
            "lemma": lexeme.lemma, "pos": lexeme.pos, "definition": sense.definition_en,
            "old_uz": sense.meaning_uz_prev or sense.meaning_uz,
            "old_alt": sense.meaning_uz_alt_prev or sense.meaning_uz_alt,
            "old_verdict": old_verdict, "new_uz": new.meaning_uz, "new_alt": new.meaning_uz_alt,
            "new_verdict": new.judge,
        }
    out.write_text(json.dumps(trial, indent=1, ensure_ascii=False))
    _trial_summary(trial)
    print_usage(usage)


def _trial_summary(trial: dict) -> tuple[float, float]:
    def share(key: str) -> float:
        answered = [t[key] for t in trial.values() if t[key] is not None]
        return sum(v == "different" for v in answered) / max(1, len(answered))
    for key in ("old_verdict", "new_verdict"):
        print(f"{key}: {dict(Counter(t[key] for t in trial.values()))}")
    old, new = share("old_verdict"), share("new_verdict")
    print(f"different share: old {old:.1%} -> new {new:.1%} "
          f"(relative drop {(old - new) / old if old else 0:.1%})")
    return old, new


#: Keep the new translations only if the `different` share drops by at least
#: this much, relative to the old pairs judged the same way in the same run.
KEEP_THRESHOLD = 0.30


async def retranslate_decide(trial_path: Path) -> None:
    trial = json.loads(trial_path.read_text())
    old, new = _trial_summary(trial)
    keep = old > 0 and (old - new) / old >= KEEP_THRESHOLD
    print(f"decision: {'KEEP new' if keep else 'RESTORE old'} (threshold "
          f"{KEEP_THRESHOLD:.0%} relative drop)")
    async with async_session_factory() as session:
        for key, t in trial.items():
            sense = await session.get(LexemeSense, uuid.UUID(key))
            if sense is None:
                continue
            if _is_locked(sense):
                print(f"  skipped, CALD/reviewed sense: {t.get('lemma', key)}")
                continue
            if keep and t["new_uz"]:
                sense.meaning_uz, sense.meaning_uz_alt = t["new_uz"], t["new_alt"]
                verdict = t["new_verdict"]
            else:
                sense.meaning_uz, sense.meaning_uz_alt = t["old_uz"], t["old_alt"]
                verdict = t["old_verdict"]
            _set_reasons(sense, _judge_reasons(sense.review_reasons, verdict))
            sense.meaning_uz_prev = sense.meaning_uz_alt_prev = ""
            session.add(sense)
        await session.commit()
        print(f"reasons now: {dict(await _reason_counts(session))}")


def _restore_shape(sense: LexemeSense, t: dict) -> None:
    sense.meaning_uz, sense.meaning_uz_alt = t["old_uz"], t["old_alt"]
    _set_reasons(sense, _judge_reasons(sense.review_reasons, t["old_verdict"]))


async def restore_retranslation(path: Path, sense_ids: list[str] | None) -> None:
    """(C1) Put back the OLD ``meaning_uz``/``meaning_uz_alt`` pair a
    retranslation trial replaced, from the durable copy at ``path`` -- see
    ``app/data/lexicon_trials/README.md``. ``meaning_uz_prev``/
    ``meaning_uz_alt_prev`` are cleared to ``""`` the moment `retranslate
    --decide` runs (whichever way it decided), so this file is the only way
    back once that has happened -- unlike `retranslate_decide` above, which
    still has both pairs on the row and can choose between them.

    ``sense_ids`` omitted restores every sense the trial touched; given,
    restores only those (validated against the file, not merely accepted as
    IDs -- a sense this trial never touched has no `old_uz` here to restore
    to).
    """
    trial = json.loads(path.read_text())
    wanted = set(sense_ids) if sense_ids else set(trial)
    unknown = sorted(wanted - set(trial))
    if unknown:
        print(f"not in this trial file, skipped: {unknown}")
    restored, missing = [], []
    async with async_session_factory() as session:
        for key in sorted(wanted & set(trial)):
            t = trial[key]
            sense = await session.get(LexemeSense, uuid.UUID(key))
            if sense is None:
                missing.append(t["lemma"])
                continue
            if _is_locked(sense):
                print(f"  skipped, CALD/reviewed sense: {t['lemma']}")
                continue
            _restore_shape(sense, t)
            session.add(sense)
            restored.append(t["lemma"])
        await session.commit()
    print(f"restored {len(restored)}: {restored}")
    if missing:
        print(f"sense no longer exists, skipped: {missing}")


# --- A: hide every proper noun's material row -------------------------------


async def hide_proper_nouns() -> None:
    """(A) ``MaterialVocabulary.hidden = true`` for every row whose lexeme is
    a proper noun (`Lexeme.is_proper_noun`). `app.services.lexicon.link_row`
    only sets this going forward; this is the one-off backfill for rows
    written before that rule existed -- including the row a learner's own
    live lookup created (a lookup still answers the learner; it must not
    leave a gloss in the passage for everyone else). Idempotent: only rows
    not already hidden are touched, so a re-run reports zero.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            sa_update(MaterialVocabulary)
            .where(
                MaterialVocabulary.lexeme_id.in_(
                    sa_select(Lexeme.id).where(Lexeme.is_proper_noun.is_(True))
                ),
                MaterialVocabulary.hidden.is_(False),
            )
            .values(hidden=True)
        )
        await session.commit()
    print(f"hidden {result.rowcount} material_vocabulary row(s) on a proper noun")


# --- B: backfill each OEWN sense's SemCor rank ------------------------------


async def wordnet_provenance() -> None:
    """(B) Backfill ``LexemeSense.oewn_rank`` for every EXISTING
    ``oewn``-sourced sense -- ``apply_work`` only started persisting it once
    that column existed; this is the one-off pass for senses P2 wrote
    before that. Matched by ``(lexeme.lemma, lexeme.pos, sense
    .oewn_synset_id)`` against the current extract, the identical lookup
    `load_works` already does for a fresh enrichment run. What this makes
    possible: `app.services.lexicon_licences.sources` can show Princeton
    WordNet 3.1 on the public licences page because the data actually used
    it, not as a permanent hand-written claim.
    """
    oewn = le.load_oewn()
    async with async_session_factory() as session:
        rows = (await session.exec(
            select(LexemeSense.id, LexemeSense.oewn_rank, LexemeSense.oewn_count,
                  LexemeSense.oewn_synset_id, Lexeme.lemma, Lexeme.pos)
            .join(Lexeme, Lexeme.id == LexemeSense.lexeme_id)
            .where(LexemeSense.oewn_synset_id.is_not(None))
        )).all()
    print(f"{len(rows)} senses carry an OEWN synset")
    updated = missing = 0
    async with async_session_factory() as session:
        for sense_id, current_rank, current_count, synset_id, lemma, pos in rows:
            entry = next((e for e in oewn.get((lemma, pos), []) if e["synset"] == synset_id), None)
            if entry is None:
                missing += 1
                continue
            if current_rank != entry["rank"] or current_count != entry["count"]:
                await session.execute(
                    sa_update(LexemeSense).where(LexemeSense.id == sense_id)
                    .values(oewn_rank=entry["rank"], oewn_count=entry["count"])
                )
                updated += 1
        await session.commit()
    print(f"updated {updated}; {missing} synset(s) no longer in the current extract")


# --- C2: function words and single-letter tokens ----------------------------


async def function_words(apply: bool) -> None:
    """(C2) Every EXISTING lexeme `app.services.lexicon.is_excluded_word`
    now refuses -- a single letter, or one of `lexicon.FUNCTION_WORDS`. A
    lexeme nothing points at (no material row, no saved word, no open
    translation report) is DELETED; one that IS referenced is KEPT and
    MARKED (`Lexeme.is_function_word`), and its material rows are HIDDEN --
    the identical treatment `proper-nouns --apply` gives a proper noun, for
    the same reason (see `mark_proper`). A referencing SAVED WORD is
    reported, never deleted silently: the learner is still studying it, and
    `_practisable_clause` already keeps it out of every queue regardless.

    Dry run by default (no ``--apply``): reports what WOULD happen without
    writing anything, since this deletes lexemes and that is not something
    to discover after the fact.
    """
    async with async_session_factory() as session:
        lexemes = (await session.exec(select(Lexeme))).all()
    candidates = [lx for lx in lexemes if is_excluded_word(lx.lemma)]
    print(f"{len(candidates)} function-word/single-letter lexeme(s) found")
    deleted, marked, saved_hits = [], [], []
    async with async_session_factory() as session:
        for stub in candidates:
            lexeme = await session.get(Lexeme, stub.id)
            refs = await _references(session, lexeme.id)
            if not any(refs.values()):
                deleted.append(lexeme.lemma)
                if apply and not await delete_lexeme(session, lexeme.id):
                    deleted.pop()
            else:
                marked.append(lexeme.lemma)
                if refs["saved"]:
                    saved_hits.append((lexeme.lemma, refs["saved"]))
                if apply:
                    lexeme.is_function_word = True
                    session.add(lexeme)
                    await session.execute(
                        sa_update(MaterialVocabulary)
                        .where(MaterialVocabulary.lexeme_id == lexeme.id)
                        .values(hidden=True)
                    )
        if apply:
            await session.commit()
    prefix = "" if apply else "would "
    print(f"{prefix}deleted {len(deleted)}: {deleted}")
    print(f"{prefix}marked {len(marked)}: {marked}")
    if saved_hits:
        print(f"saved words on a kept lexeme (never deleted): {saved_hits}")
    if not apply:
        print("dry run -- pass --apply to write")


# --- Main -----------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ngsl")
    proper = sub.add_parser("proper-nouns")
    proper.add_argument("--classify", type=Path)
    proper.add_argument("--apply", type=Path)
    stale = sub.add_parser("stale-oewn")
    stale.add_argument("--apply", action="store_true")
    lonly = sub.add_parser("list-only")
    lonly.add_argument("--apply", action="store_true")
    lonly.add_argument("--out", type=Path)
    rj = sub.add_parser("rejudge")
    rj.add_argument("--out", type=Path, required=True)
    rj.add_argument("--log", type=Path)
    rt = sub.add_parser("retranslate")
    rt.add_argument("--trial", type=Path)
    rt.add_argument("--decide", type=Path)
    rt.add_argument("--log", type=Path)
    rr = sub.add_parser("restore-retranslation")
    rr.add_argument("--file", type=Path, required=True)
    rr.add_argument("--sense", dest="sense_ids", action="append")
    sub.add_parser("hide-proper-nouns")
    sub.add_parser("wordnet-provenance")
    fw = sub.add_parser("function-words")
    fw.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if args.cmd == "ngsl":
        await recompute_ngsl()
    elif args.cmd == "proper-nouns" and args.classify:
        await classify_proper(args.classify)
    elif args.cmd == "proper-nouns" and args.apply:
        await apply_proper(args.apply)
    elif args.cmd == "stale-oewn":
        await stale_oewn(args.apply)
    elif args.cmd == "list-only":
        await list_only(args.apply, args.out)
    elif args.cmd == "rejudge":
        await rejudge(args.out, args.log)
    elif args.cmd == "retranslate" and args.trial:
        await retranslate_trial(args.trial, args.log)
    elif args.cmd == "retranslate" and args.decide:
        await retranslate_decide(args.decide)
    elif args.cmd == "restore-retranslation":
        await restore_retranslation(args.file, args.sense_ids)
    elif args.cmd == "hide-proper-nouns":
        await hide_proper_nouns()
    elif args.cmd == "wordnet-provenance":
        await wordnet_provenance()
    elif args.cmd == "function-words":
        await function_words(args.apply)


if __name__ == "__main__":
    asyncio.run(main())
