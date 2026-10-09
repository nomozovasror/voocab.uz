"""Cambridge Advanced Learner's Dictionary (CALD) definitions on the lexicon:
the engine. `scripts/cald.py` is its command line (index, match, map,
translate, apply, restore, the reports); `app.worker`'s lexicon loop calls
:func:`map_new_lexemes` for lexemes enriched after the full run. The rules
are summarised in `app/services/CLAUDE.md`, "CALD definitions"; this
docstring is the reasoning behind them.

## Nothing CALD-derived is ever committed

The GitHub repository is PUBLIC and CALD is a copyrighted dictionary. This
code may be committed; nothing it PRODUCES may be. Every artefact -- the
index, the match table, the decision log, usage, the reports -- goes to
:data:`PRIVATE_DIR` (``backend/app/data/private/cald/``, gitignored as a
whole directory, not file by file, so a new artefact cannot slip through by
having a name nobody listed). ``scripts/cald.py backup`` copies it to
``~/voocab-dev-backups/``: a gitignored directory is also one no clone, no
push and no other checkout will ever have. The DATABASE does hold CALD text
after ``apply`` (that is the point), and a database dump is as private as
this directory. Tests use invented entries only. (No CALD text in this
repository, docstrings included.)

## The matcher is a cascade, and a step only runs when the one before found nothing

A lexeme is ``(lemma, pos)``; a CALD entry is a page of BLOCKS, one per part
of speech and guideword (`bank` noun MONEY, noun RIVER, verb ...). The
matcher (:meth:`CaldIndex.match`) tries, in order, and stops at the first
step that yields a defined CALD sense of a COMPATIBLE part of speech:

1. ``exact`` -- the block's own headword (stress marks stripped) is the lemma.
2. ``alias`` -- CALD's ``aliases.json`` names the lemma as another form of a
   headword. That file is the scraper's SEARCH table, so a one-word alias
   counts only when its target is really the same word (:func:`alias_is_same`);
   a lemma whose search lands on another headword's page ends as ``none``
   with ``how = "alias-elsewhere"``.
3. ``cald-variant`` -- a block lists the lemma in its own ``variants`` field.
4. ``redirect`` -- the CALD page for the lemma shows a block of another
   spelling.
5. ``spelling`` -- British/American rules (:func:`spelling_variants`): -ise/
   -ize, -our/-or, -re/-er, -ence/-ense, l/ll, ae/oe/e (never word-final),
   -ogue/-og, and a short list of pairs no rule reaches.
6. ``idiom`` / ``idiom-sense`` -- multi-word lemmas only: both sides
   normalised (:func:`phrase_forms`: `sb`/`sth` dropped, possessives made one
   placeholder, parentheses optional, slash alternatives expanded, a leading
   article or `be` optional) and compared against CALD's multi-word
   headwords and then against the ``phrase`` senses inside every block.
   Before the hyphen rule, so a phrasal verb finds the verb pattern and not
   the closed compound noun.
7. ``hyphen`` -- `on-board`/`on board`/`onboard`.
8. ``plural`` -- nouns only: a block whose listed plural is the lemma, or a
   singular a rule gives (:func:`singular_candidates`).
9. ``verb-form`` -- verbs only: a block whose listed forms include the
   lemma; then ``phrasal-verb`` -- a one-word verb CALD defines only through
   its pattern is offered those phrasal-verb blocks.

A lemma CALD has only in an INCOMPATIBLE part of speech is ``headword-only``
and is NOT matched ("never match across a meaning-changing pos"). A lemma
CALD lists only as a form it never defines is ``no-definition``. Nothing a
step finds is a decision -- it is the list of candidate senses the mapper
chooses among, and the model may always say ``none``. A phrase sense inside
a block is a candidate only for a MULTI-WORD lemma, unless the word has
nothing else.

## The model CHOOSES a CALD sense; it never writes one

``map`` shows the model one of our senses (definition, Uzbek, pos, and one
sentence from a passage where learners met it in that sense) beside every
candidate CALD sense under a short id, and asks which one is the same
meaning, or ``none``. An answer that names no provided id is no answer,
asked once more on its own request and then recorded as unanswered -- never
turned into ``none``, which is a claim about the dictionary, not the API.

## The rules agreed with the owner (2026-10-07)

1. **High and medium mappings are applied** (:data:`ACCEPTED_CONFIDENCES`);
   ``low`` counts as ``none``. The CALD definition replaces ours, cleaned of
   its cross-reference markup (:func:`clean_definition`).
2. **A pointer-only CALD sense is followed one hop** to the target
   headword's sense in the same pos -- taken directly when there is one,
   chosen by the model among several -- and the followed ref is recorded
   (``xref``). A pointer that cannot be followed is ``none``
   (:func:`effective_mapping`).
3. **Two of our senses on one CALD sense both take it**; no link moves. The
   lookup popover and the word page show identical definitions ONCE
   (`lemma_senses.arrange`; the anchor sense wins).
4. **CEFR:** a CALD per-sense level replaces ours (``cefr_source='cald'``);
   no CALD level, ours stays (``'ours'``). Material rows
   (`material_vocabulary.cefr_level`) whose ``sense_id`` took a CALD level
   take it too, the previous value kept in ``cefr_level_pre_cald``.
   `SavedWordContext` snapshots are not touched. Refined after the full run
   (the owner, 2026-10-07): CALD's level is taken only within
   :data:`CEFR_CAP_BANDS` of ours (or where we have none); further away ours
   stays, ``cald_cefr`` keeps CALD's, and the review reason
   ``cald_cefr_far`` flags it -- English Vocabulary Profile levels measure
   what learners PRODUCE, so concrete everyday nouns come out C1/C2. And a
   mapping whose CALD level is :data:`VERIFY_BANDS`+ from ours is
   re-verified (:func:`run_verify`, :func:`verified_mapping`): ``different``
   in either of two runs, or ``unsure`` in both, makes it ``none``.
5. **Uzbek:** every sense whose definition changed to CALD gets translation
   v2 (:data:`TRANSLATE_V2_PROMPT`, both production translators,
   keep-or-adjust, seeing the CALD definition, guideword, passage sentence
   and our current pair), compared with the old pair by
   :data:`JUDGE_MODEL` twice, positions swapped (:data:`COMPARE_PROMPT`).
   **Loose keep rule:** the old pair stays if EITHER run says the old one
   is better or the new one is wrong (``loose_keep`` of
   :func:`combine_comparison`); otherwise the new pair. No verdict at all
   keeps the old pair. ``meaning_uz_material`` is never touched.
6. **Everything old is kept and restorable**: the first apply copies
   ``definition_en``, ``cefr``, ``meaning_uz``, ``meaning_uz_alt``,
   ``licence``, ``review_reasons`` and ``needs_review`` into their
   ``*_pre_cald`` columns (with ``cald_applied_at``); :func:`restore_senses`
   puts them back.
7. **A human decision locks the sense** (review fix): a sense Studio approved
   or fixed (``approved_at``, before or after the first apply) is skipped by
   :func:`apply_plans` and :func:`restore_senses` and never re-opened; a
   rewritten CALD definition becomes ``definition_source = 'human'``
   (:func:`is_locked`).

## Every model answer is kept, and a re-run pays only for new questions

Each answer is appended to :data:`DECISIONS_FILE` the moment it arrives,
keyed by what it was ASKED: the sense, our definition and passage sentence,
and the CONTENT of every candidate shown (:func:`candidate_fingerprints`)
-- not only the refs, because a ref is a position in the source file and a
corrected source moves things (``map`` and ``xref`` keys; MAP_VERSION 3).
A re-run asks only what the log does not already hold. Items are built from
a sense's BEFORE-CALD values (:func:`load_items`), so a re-run after
``apply`` asks the very same questions and apply is idempotent.

## Once applied, the lexicon does not drift back

`lexicon_enrich` never rewrites a ``cald``/``human`` sense's definition,
CEFR, Uzbek or review state (``Sense.locked``), never relabels its synset,
and never absorbs or deletes it (one that lost its rows stays and is flagged).
``source_id`` (where the SENSE came from: an OEWN
synset or a model sense) is left as it is -- ordering and the letter hint
read the synset -- while ``definition_source`` says whose TEXT the
definition is, and the licences page counts OEWN by that, so nothing claims
a CALD definition is WordNet's.
"""

from __future__ import annotations

import asyncio
import gc
import gzip
import hashlib
import json
import logging
import re
import time
import uuid
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger("app.services.lexicon_cald")

#: Gitignored as a directory (``backend/app/data/private/``) -- see the
#: module docstring. Everything CALD-derived lives here.
PRIVATE_DIR = Path(__file__).resolve().parents[1] / "data" / "private" / "cald"
INDEX_FILE = "index.json.gz"
MATCH_FILE = "matches.json.gz"
DECISIONS_FILE = "decisions.jsonl"
USAGE_FILE = "usage.jsonl"

#: 4: the source's entry/block-level ``pron`` (with ``ipa_variants``), a
#: phrasal verb's ``base_pron`` and a sense's own ``pron`` are kept per block
#: -- heteronyms (`record` noun/verb) differ by block. Phase 2b reads them
#: (:mod:`app.services.word_recordings`; the transcription is never stored
#: outside this private index).
INDEX_VERSION = 4
CEFR_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")

#: The comparison judge agreed for the full run: a third model, neither
#: translator (the pilot's calibration: it said "old is better" for all three
#: renderings known wrong, which `lexicon_enrich.MODEL_JUDGE` passed).
JUDGE_MODEL = "gemini-3.7-flash"


# --- Index ----------------------------------------------------------------------

#: CALD's part-of-speech labels -> the word class `Lexeme.pos` uses (``n``,
#: ``v``, ``adj``, ``adv``, ``prep``, ``conj``), or a class of CALD's own
#: that none of ours is (``excl``, ``det``, ``pron``, ``num``, ``affix``). A
#: phrasal, modal or auxiliary verb is a verb: the difference is grammar,
#: not meaning. A block with no pos is an idiom page when its headword is
#: several words (``idiom``); anything else -- no pos on a one-word page, or
#: a pos field that is really a scraping artefact (``B1``, ``informal``,
#: ``slang``) -- is ``?``, matched only by a lexeme that has no word class
#: of its own either (``phr`` or empty).
POS_CLASS: dict[str, str] = {
    "noun": "n",
    "verb": "v", "phrasal verb": "v", "modal verb": "v", "auxiliary verb": "v",
    "adjective": "adj", "adj": "adj",
    "adverb": "adv",
    "preposition": "prep",
    "conjunction": "conj",
    "exclamation": "excl",
    "determiner": "det", "predeterminer": "det",
    "pronoun": "pron",
    "number": "num", "ordinal number": "num",
    "prefix": "affix", "suffix": "affix",
}

_STRESS = re.compile(r"[ˈˌ·]")


def clean_text(value: object) -> str:
    """One line of CALD text as this module compares and shows it: stress
    marks gone (block headwords carry them -- ``ˌable-ˈbodied``), curly
    apostrophes made straight (our lemmas use ``'``), whitespace collapsed."""
    text = _STRESS.sub("", str(value or ""))
    for mark in ("’", "‘", "ʼ"):
        text = text.replace(mark, "'")
    return " ".join(text.split())


def _is_multiword(text: str) -> bool:
    return " " in text.strip()


def pos_class(raw_pos: object, headword: str) -> str:
    if raw_pos is None or raw_pos == "":
        return "idiom" if _is_multiword(headword) else "?"
    return POS_CLASS.get(str(raw_pos).strip().lower(), "?")


def first_example(sense: dict) -> str:
    """The first example sentence of a sense, whichever shape it is stored
    in (a string, or ``{"pattern", "text"}``), cut to 300 characters."""
    for item in sense.get("examples") or []:
        text = item.get("text") if isinstance(item, dict) else item
        text = clean_text(text)
        if text:
            return text[:300]
    return ""


def _pron(value: object) -> dict:
    """``{"uk": {"ipa", "audio", "ipa_variants"?}, "us": {...}}`` with empty
    parts dropped -- the audio path is CALD's own, relative to the source
    directory. ``ipa_variants`` (weak forms, other pronunciations) is a list
    of strings and kept only where the source has one."""
    out = {}
    if not isinstance(value, dict):
        return out
    for accent in ("uk", "us"):
        part = value.get(accent)
        if isinstance(part, dict):
            kept: dict = {k: str(part[k]) for k in ("ipa", "audio") if part.get(k)}
            variants = [str(v) for v in part.get("ipa_variants") or [] if v]
            if variants:
                kept["ipa_variants"] = variants
            if kept:
                out[accent] = kept
    return out


_XREF = re.compile(r"\(Cf\. ↑([^)]*)\)")
_XREF_RUN = set("ABCDEFGHIJKLMNOPQRSTUVWXYZÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÑÒÓÔÕÖØÙÚÛÜÝ0123456789 -'().!&/,")
_XREF_NOISE = re.compile(
    r"→|\([^)]*\)|\b(?:a|an|the|noun|verb|adjective|adverb|exclamation|plural|"
    r"preposition|pronoun|determiner|conjunction|or|and)\b", re.IGNORECASE)


def clean_definition(text: str) -> tuple[str, list[str], bool]:
    """CALD's cross-reference markup made readable (examples invented, in
    the markup's shape): ``ZOB(Cf. ↑zob)`` -> ``zob``, ``a small kind of
    ZOB(Cf. ↑zob)`` -> ``a small kind of zob``. Returns ``(text, targets,
    xref_only)``; ``xref_only`` is a "definition" that is nothing but a
    pointer to another headword, possibly with a pos and a topic (``ZOB(Cf.
    ↑zob) noun (TOPIC)``) -- 2 520 senses carry the markup and most are such
    pointers. Following one to the target's own definition is a phase-2
    decision; this phase only marks them, so the pilot can show them for
    what they are. (No CALD text in this repository, docstrings included.)"""
    targets = []
    out, last = [], 0
    for match in _XREF.finditer(text):
        start = match.start()
        while start > last and text[start - 1] in _XREF_RUN:
            start -= 1
        while start < match.start() and text[start] in " (),.":
            start += 1  # the run's own leading space/punctuation stays
        target = clean_text(match.group(1))
        targets.append(target)
        out.append(text[last:start] + target)
        last = match.end()
    if not targets:
        return text, [], False
    cleaned = clean_text("".join(out) + text[last:])
    rest = cleaned
    for target in targets:
        rest = rest.replace(target, " ")
    rest = _XREF_NOISE.sub(" ", rest)
    xref_only = not re.sub(r"[^A-Za-z]+", "", rest)
    return cleaned, targets, xref_only


#: A definition that opens with a parenthesis followed by a SPACE carries a
#: list whose label the extract lost: alternative forms, a symbol or an
#: abbreviation, verb forms, sometimes their transcription. The source's own
#: qualifiers ("(of a person) ...", "(in mathematics) ...") never have that
#: space, so they are left alone.
_LABEL_LOST_PREFIX = re.compile(r"^\(\s[^)]*\)\s*")


def strip_label_lost_prefix(text: str) -> str:
    """``text`` without a leading label-less list (see
    :data:`_LABEL_LOST_PREFIX`) -- what a learner reads and what TTS says.
    Applied when a plan is built, NOT in the index: the questions already
    asked carry the index's text in their keys, and changing it there would
    re-ask (and re-pay for) every lexeme that has such a candidate."""
    stripped = _LABEL_LOST_PREFIX.sub("", text, count=1)
    return stripped if stripped.strip() else text


def _senses(block: dict, ref_prefix: str) -> list[dict]:
    """A block's senses that HAVE a definition, each with its ref."""
    out = []
    for s_index, sense in enumerate(block.get("senses") or []):
        if not isinstance(sense, dict):
            continue
        definition, xref, xref_only = clean_definition(clean_text(sense.get("definition")))
        if not definition:
            continue
        level = str(sense.get("level") or "").strip().upper()
        record = {
            "ref": f"{ref_prefix}#{s_index}",
            "num": sense.get("num"),
            "level": level if level in CEFR_LEVELS else None,
            "def": definition,
            "ex": first_example(sense),
            "phrase": clean_text(sense.get("phrase")) or None,
            "labels": [str(x) for x in sense.get("labels") or []],
        }
        if xref:
            record["xref"] = xref
            record["xref_only"] = xref_only
        # A sense spoken differently from its block (a weak form, an
        # abbreviation's full word): rare, and kept only where present.
        for key, source_key in (("pron", "pron"), ("phrase_pron", "phrase_pron")):
            pron = _pron(sense.get(source_key))
            if pron:
                record[key] = pron
        out.append(record)
    return out


def _split_forms(value: object) -> list[str]:
    out = []
    for item in value if isinstance(value, list) else [value]:
        if isinstance(item, str):
            out += [clean_text(x) for x in re.split(r"[/,]", item)]
    return [x for x in out if x and not x.startswith("-")]


def _inflections(block: dict, raw_pos: object) -> list[str]:
    """Noun plurals (``forms``) or verb forms (``forms`` + ``verb_forms``:
    third person, -ing, past, past participle) -- what an inflected lemma
    of ours (`vertebrae`, `accused`) is matched back to its headword by."""
    if raw_pos == "noun":
        return _split_forms(block.get("forms"))
    if raw_pos in ("verb", "phrasal verb"):
        forms = _split_forms(block.get("forms"))
        verb_forms = block.get("verb_forms")
        if isinstance(verb_forms, dict):
            present = verb_forms.get("present_simple")
            if isinstance(present, dict):
                forms += _split_forms(present.get("he/she/it"))
            for key in ("present_participle", "past_simple", "past_participle"):
                forms += _split_forms(verb_forms.get(key))
        return list(dict.fromkeys(forms))
    return []


def parse_entries(entries: dict, aliases: dict) -> dict:
    """The compact index: ``{"version", "headwords": {entry key: [block]},
    "aliases": {alias: entry key}, "pron": {headword: [{"classes", "pron"}]},
    "undefined": {headword: [class, ...]}}``.

    A block keeps what the matcher, the mapper and phase 2 need -- pos and
    its class, guideword, its own headword, labels, variants, inflected
    forms, ``main_entry``/``base``, pronunciations -- and only its senses
    that HAVE a definition. A DERIVED sub-entry with a definition of its own
    (`busker` under `busk`) is a block too; most derived forms have none
    (`abandonment` under `abandon` is listed with examples only).

    A headword CALD lists but never defines -- a definition-less block, a
    derived form with examples only -- goes to ``undefined`` instead: it
    cannot give anybody a definition, but the coverage report must be able
    to say "CALD has this word, without a definition" rather than "CALD does
    not have it", and phase 2's audio import may still want its recording.

    ``ref`` is ``entry key#block#sense``, the block part ``<i>`` or, for a
    derived sub-entry, ``<i>.d<j>`` -- indices into the SOURCE file counted
    before anything is skipped, so a sense keeps its ref however this
    parser's filters change, for as long as ``entries.json`` is the same
    file.

    **Pronunciation is per block** (the fixed source, 2026-10-07): every
    block carries its own ``pron`` -- a heteronym's noun and verb blocks
    (`record`, `present`, `wind`, `lead`, `tear`) have different IPA and
    different recordings -- and a phrasal-verb block also its base verb's
    (``base_pron``). A block keeps ``pron`` (the entry's only where the block
    has none, ``pron_from`` saying which) and ``base_pron``; a sense keeps
    its own ``pron`` in the rare case it has one. ``pron`` at the top covers
    every headword with a recording, defined or not, as the DISTINCT
    pronunciations it has, each with the classes of the blocks that use it.
    Phase 2b (audio) reads these; nothing here imports audio.
    """
    headwords: dict[str, list[dict]] = {}
    pron_index: dict[str, list[dict]] = defaultdict(list)
    undefined: dict[str, set[str]] = defaultdict(set)

    def note_pron(hw: str, cls: str, pron: dict) -> None:
        for known in pron_index[hw.lower()]:
            if known["pron"] == pron:
                if cls not in known["classes"]:
                    known["classes"].append(cls)
                return
        pron_index[hw.lower()].append({"classes": [cls], "pron": pron})

    def make_block(key: str, block_id: str, block: dict, hw: str, *, own_hw: bool,
                   pron: dict, pron_from: str, derived: bool) -> dict | None:
        raw_pos = block.get("pos") if isinstance(block.get("pos"), str) else None
        if pron and hw:
            note_pron(hw, pos_class(raw_pos, hw), pron)
        senses = _senses(block, block_id)
        if not senses:
            if hw:
                undefined[hw.lower()].add(pos_class(raw_pos, hw))
            return None
        base = clean_text(block.get("base")) or None
        return {
            "id": block_id,
            "key": key,
            "hw": hw,
            "own_hw": own_hw,
            "pos": raw_pos,
            "cls": pos_class(raw_pos, hw),
            "gw": clean_text(block.get("guideword")),
            "labels": [str(x) for x in block.get("labels") or []],
            "variants": [
                {"word": clean_text(v.get("word")), "label": str(v.get("label") or "")}
                for v in block.get("variants") or []
                if isinstance(v, dict) and clean_text(v.get("word"))
            ],
            "forms": _inflections(block, raw_pos),
            "main": clean_text(block.get("main_entry")) or None,
            "base": base,
            # A page whose block is ANOTHER headword (the `advisor` page
            # shows `adviser`); not a phrasal verb page (`add up` shows `add
            # (sth) up`) and not a derived sub-entry.
            "redirect": own_hw and not derived and hw.lower() != key.lower() and not base,
            "derived": derived,
            "pron": pron,
            "pron_from": pron_from if pron else "",
            **({"base_pron": _pron(block.get("base_pron"))} if _pron(block.get("base_pron")) else {}),
            "senses": senses,
        }

    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        entry_hw = clean_text(entry.get("headword")) or key
        entry_pron = _pron(entry.get("pron"))
        blocks = []
        for b_index, block in enumerate(entry.get("blocks") or []):
            if not isinstance(block, dict):
                continue
            own_hw = clean_text(block.get("headword"))
            hw = own_hw or entry_hw
            block_pron = _pron(block.get("pron"))
            made = make_block(key, f"{key}#{b_index}", block, hw, own_hw=bool(own_hw),
                              pron=block_pron or entry_pron,
                              pron_from="block" if block_pron else "entry", derived=False)
            if made:
                blocks.append(made)
            for d_index, sub in enumerate(block.get("derived") or []):
                sub_hw = clean_text(sub.get("headword")) if isinstance(sub, dict) else ""
                if not sub_hw:
                    continue
                made = make_block(key, f"{key}#{b_index}.d{d_index}", sub, sub_hw, own_hw=True,
                                  pron=_pron(sub.get("pron")), pron_from="block", derived=True)
                if made:
                    blocks.append(made)
        if blocks:
            headwords[key] = blocks
    alias_index = {clean_text(a).lower(): str(k) for a, k in aliases.items()
                   if isinstance(a, str) and isinstance(k, str) and k in entries}
    return {"version": INDEX_VERSION, "headwords": headwords, "aliases": alias_index,
            "pron": dict(pron_index),
            "undefined": {hw: sorted(classes) for hw, classes in undefined.items()}}


def build_index(source: Path, out_dir: Path = PRIVATE_DIR) -> dict:
    entries_path = source / "data" / "entries.json"
    aliases_path = source / "data" / "aliases.json"
    raw = entries_path.read_bytes()
    entries = json.loads(raw)
    aliases = json.loads(aliases_path.read_text(encoding="utf-8")) if aliases_path.exists() else {}
    index = parse_entries(entries, aliases)
    index["source"] = str(source)
    index["entries_sha256"] = hashlib.sha256(raw).hexdigest()
    index["built_at"] = datetime.now(timezone.utc).isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_dir / INDEX_FILE, "wt", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, separators=(",", ":"))
    return index


def load_index_data(out_dir: Path = PRIVATE_DIR) -> dict:
    path = out_dir / INDEX_FILE
    if not path.exists():
        raise SystemExit(f"{path} not found -- run `index --source <dir>` first")
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    if data.get("version") != INDEX_VERSION:
        raise SystemExit(f"{path} is index version {data.get('version')}, this code reads "
                         f"{INDEX_VERSION} -- run `index --source <dir>` again")
    return data


# --- Normalisation rules ----------------------------------------------------------

#: Single substitutions between British and American spelling, applied one
#: occurrence at a time (:func:`spelling_variants`). Over-generation is
#: harmless by construction: a rewritten string counts only if CALD has it
#: as a headword in a compatible part of speech, and only for a lemma whose
#: own spelling found nothing.
SPELLING_SWAPS: tuple[tuple[str, str], ...] = (
    ("ise", "ize"), ("ize", "ise"), ("isa", "iza"), ("iza", "isa"),
    ("yse", "yze"), ("yze", "yse"), ("ysi", "yzi"), ("yzi", "ysi"),
    ("our", "or"), ("or", "our"),
    ("re", "er"), ("er", "re"), ("red", "ered"), ("ered", "red"),
    ("ring", "ering"), ("ering", "ring"),
    ("ence", "ense"), ("ense", "ence"),
    ("ll", "l"), ("l", "ll"),
    ("ae", "e"), ("e", "ae"), ("oe", "e"), ("e", "oe"),
    ("ogue", "og"), ("og", "ogue"),
    ("dgement", "dgment"), ("dgment", "dgement"),
    ("ageing", "aging"), ("aging", "ageing"),
)

#: Whole-word pairs no rule above reaches. Both directions are tried.
SPELLING_PAIRS: tuple[tuple[str, str], ...] = (
    ("gray", "grey"), ("plow", "plough"), ("mold", "mould"), ("molt", "moult"),
    ("aluminum", "aluminium"), ("program", "programme"), ("tire", "tyre"),
    ("curb", "kerb"), ("cozy", "cosy"), ("jewelry", "jewellery"),
    ("pajamas", "pyjamas"), ("artifact", "artefact"), ("ax", "axe"),
    ("skeptic", "sceptic"), ("skeptical", "sceptical"), ("skepticism", "scepticism"),
    ("sulfur", "sulphur"), ("mustache", "moustache"), ("toward", "towards"),
    ("afterward", "afterwards"), ("backward", "backwards"), ("donut", "doughnut"),
    ("yogurt", "yoghurt"), ("mollusk", "mollusc"), ("likable", "likeable"),
    ("livable", "liveable"), ("sizable", "sizeable"), ("whiskey", "whisky"),
)
_PAIR_MAP: dict[str, set[str]] = defaultdict(set)
for _a, _b in SPELLING_PAIRS:
    _PAIR_MAP[_a].add(_b)
    _PAIR_MAP[_b].add(_a)


#: Swaps never applied at the END of a word: a final -ae/-oe is a Latin
#: plural or a loanword (`marae`, `pilae`), not anaemia's British ae.
_NOT_FINAL = {"ae", "oe", "e"}


def _one_step(word: str) -> set[str]:
    out: set[str] = set()
    for old, new in SPELLING_SWAPS:
        start = word.find(old)
        while start >= 0:
            end = start + len(old)
            final = end == len(word) or word[end] == " "
            if not (final and (old in _NOT_FINAL and new in _NOT_FINAL)):
                out.add(word[:start] + new + word[end:])
            start = word.find(old, start + 1)
    tokens = word.split(" ")
    for i, token in enumerate(tokens):
        for other in _PAIR_MAP.get(token, ()):
            out.add(" ".join(tokens[:i] + [other] + tokens[i + 1:]))
    out.discard(word)
    return out


def spelling_variants(word: str, depth: int = 1) -> set[str]:
    """Every string ``depth`` British/American substitutions away from
    ``word`` (:data:`SPELLING_SWAPS`, :data:`SPELLING_PAIRS`). Depth 2
    exists for words that differ twice (`maneuver`/`manoeuvre`: oe and
    re/er); the caller tries it only when depth 1 found nothing."""
    word = word.lower()
    frontier, seen = {word}, {word}
    for _ in range(depth):
        nxt = set()
        for item in frontier:
            nxt |= _one_step(item)
        nxt -= seen
        seen |= nxt
        frontier = nxt
    seen.discard(word)
    return seen


def hyphen_variants(word: str) -> set[str]:
    """`on-board` -> `on board`, `onboard`; `chess board` -> `chess-board`,
    `chessboard` -- all separators at once, which is how compounds vary."""
    word = word.lower()
    out = set()
    if "-" in word:
        out |= {word.replace("-", " "), word.replace("-", "")}
    if " " in word:
        out |= {word.replace(" ", "-"), word.replace(" ", "")}
    out.discard(word)
    return out


#: Plural -> singular endings, tried longest first. Nouns only.
PLURAL_RULES: tuple[tuple[str, str], ...] = (
    ("ices", "ex"), ("ices", "ix"), ("eaux", "eau"), ("ies", "y"), ("ves", "f"),
    ("ves", "fe"), ("ses", "sis"), ("men", "man"), ("ae", "a"), ("es", ""),
    ("i", "us"), ("a", "um"), ("a", "on"), ("s", ""),
)
IRREGULAR_PLURALS: dict[str, str] = {
    "children": "child", "feet": "foot", "teeth": "tooth", "mice": "mouse",
    "geese": "goose", "lice": "louse",
}


def singular_candidates(word: str) -> list[str]:
    """Singulars a plural lemma may have (`vertebrae` -> `vertebra`,
    `criteria` -> `criterion`, `studies` -> `study`). Only the LAST word of
    a phrase is inflected (`identical twins` -> `identical twin`). Every
    candidate is a guess the caller checks against CALD's noun headwords."""
    word = word.lower()
    head, _, last = word.rpartition(" ")
    prefix = f"{head} " if head else ""
    out = []
    if last in IRREGULAR_PLURALS:
        out.append(prefix + IRREGULAR_PLURALS[last])
    for ending, replacement in PLURAL_RULES:
        if last.endswith(ending) and len(last) > len(ending) + 1:
            out.append(prefix + last[: -len(ending)] + replacement)
    return list(dict.fromkeys(c for c in out if c != word))


#: Object placeholders: dropped (ours rarely write them, CALD nearly always
#: does -- `take sb/sth for granted` vs `take for granted`).
OBJECT_WORDS = {"sb", "sth", "someone", "something", "somebody", "sb/sth", "sth/sb",
                "someone/something"}
#: Possessive placeholders: made ONE token rather than dropped, so `make
#: one's way` meets CALD's `make your way` and NOT the different idiom `make
#: way`.
POSSESSIVE_WORDS = {"one's", "your", "sb's", "someone's", "somebody's", "sth's",
                    "something's", "his", "her", "their", "its", "my", "our",
                    "oneself", "yourself", "himself", "herself", "themselves", "itself"}
_PUNCT = re.compile(r"[!?,.;:…\"“”]+")
_PARENS = re.compile(r"\(([^()]*)\)")
MAX_FORMS = 48


def phrase_forms(text: str) -> set[str]:
    """Every normalised form a multi-word expression can be compared by.

    Parentheses are optional (`(a) wug of the zob` -> with and without
    `a`; `icu (intensive care unit)` -> `icu`); `/` offers alternatives one
    word at a time (`zob notion/sense` -> `zob notion`, `zob sense`);
    objects are dropped and possessives become ``<poss>`` (see the two word
    sets above); a leading `a`/`an`/`the`, and a leading `be`, are optional.
    Bounded at :data:`MAX_FORMS` so a pathological slash-heavy idiom cannot
    blow the index up."""
    text = clean_text(text).lower()
    if not text:
        return set()
    bases = {_PARENS.sub(" ", text), _PARENS.sub(r"\1", text)}
    out: set[str] = set()
    for base in bases:
        base = _PUNCT.sub(" ", base)
        options = []
        for token in base.split():
            if "/" in token and token not in OBJECT_WORDS:
                options.append([t for t in token.split("/") if t] or [token])
            else:
                options.append([token])
        combos = 1
        for opt in options:
            combos *= len(opt)
        if combos > MAX_FORMS:
            options = [opt[:1] for opt in options]
        for choice in product(*options):
            readings = [list(choice)]
            # CALD's `in/out of keeping` is `in keeping` OR `out of
            # keeping`: an earlier alternative may also skip the word that
            # follows the slash group.
            for i, opt in enumerate(options):
                if len(opt) > 1 and choice[i] != opt[-1] and i + 1 < len(choice):
                    readings.append(list(choice[: i + 1]) + list(choice[i + 2:]))
            for reading in readings:
                words = []
                for token in reading:
                    if token in OBJECT_WORDS:
                        continue
                    words.append("<poss>" if token in POSSESSIVE_WORDS else token)
                for variant in _optional_lead(words):
                    if variant:
                        out.add(" ".join(variant))
            if len(out) >= MAX_FORMS:
                return out
    return out


def _optional_lead(words: list[str]) -> list[list[str]]:
    out = [words]
    if words and words[0] in ("a", "an", "the"):
        out.append(words[1:])
    if words and words[0] == "be":
        out.append(words[1:])
        if len(words) > 1 and words[1] in ("a", "an", "the"):
            out.append(words[2:])
    return out


def _within_one_edit(a: str, b: str) -> bool:
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i + (len(a) == len(b)):] == b[i + 1:]


def alias_is_same(alias: str, canonical: str) -> bool:
    """Whether an ``aliases.json`` line is a real variant of the same
    expression. That file is the scraper's SEARCH table, not a list of
    variants: for 975 one-word searches the extract has no page of their
    own (`aspect`, `answer`, `break`, `box`) and the alias names whatever
    page the search landed on instead (`aspect ratio`, `answer to`, `break
    time`). So a ONE-word alias counts only when its target is one word
    that a spelling rule, a hyphen, or a single edit reaches (`adapter` ->
    `adaptor`, `archive` -> `archives`); a MULTI-word alias -- an idiom's
    other wording (`a bird in the hand` for the whole proverb) -- counts as
    it stands."""
    alias, canonical = clean_text(alias).lower(), clean_text(canonical).lower()
    if _is_multiword(alias):
        return True
    if _is_multiword(canonical):
        return False
    return (canonical in spelling_variants(alias) or canonical in hyphen_variants(alias)
            or _within_one_edit(alias, canonical))


# --- The matcher -------------------------------------------------------------------

#: The order the cascade runs in -- see the module docstring for why.
MATCH_STEPS: tuple[str, ...] = (
    "exact", "alias", "cald-variant", "redirect", "spelling", "idiom", "idiom-sense",
    "hyphen", "plural", "verb-form", "phrasal-verb",
)
#: Every kind a lexeme can end up as. ``no-definition``: CALD lists the
#: word but never defines it (a derived form with examples only) -- the old
#: definition stays, exactly as for ``none``, but it is not the same claim.
MATCH_KINDS: tuple[str, ...] = ("exact", "variant", "headword-only", "no-definition", "none")


def compatible(our_pos: str, cls: str, multiword: bool) -> bool:
    """Whether a CALD block of class ``cls`` can be a sense of a lexeme of
    pos ``our_pos``. Our ``phr`` is a shape (several words), not a word
    class, so it takes any class but an affix; so does a lexeme with no pos
    at all. An idiom page (no pos, several words) fits any multi-word
    lexeme. Otherwise the classes must be equal -- `record` the noun never
    takes `record` the verb's senses."""
    if cls == "affix":
        return False
    if our_pos in ("phr", ""):
        return True
    if cls == "idiom":
        return multiword
    if cls == "?":
        return False
    return our_pos == cls


@dataclass
class Match:
    kind: str  # one of MATCH_KINDS
    how: str = ""  # one of MATCH_STEPS, "" for headword-only/none
    via: str = ""  # the CALD form the step matched
    refs: list[str] = field(default_factory=list)
    #: headword-only: CALD's classes for the lemma, none of them ours.
    cald_classes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        out = {"kind": self.kind, "how": self.how, "via": self.via, "refs": self.refs}
        if self.cald_classes:
            out["cald_classes"] = self.cald_classes
        return out


def _norm_def(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


class CaldIndex:
    """The parsed index with the lookups the matcher needs, built once per
    run from :func:`parse_entries`' output."""

    def __init__(self, data: dict) -> None:
        # `data` is NOT kept: everything the matcher reads is derived below,
        # and holding the raw dict (with its `pron` table, which only the
        # undefined headwords' share of is read) would keep what the caller
        # dropped alive.
        self.blocks: dict[str, dict] = {}
        self.senses: dict[str, tuple[dict, dict]] = {}
        self.by_form: dict[str, list[dict]] = defaultdict(list)
        self.redirects: dict[str, list[dict]] = defaultdict(list)
        self.by_variant: dict[str, list[dict]] = defaultdict(list)
        #: one-word verb -> its phrasal-verb blocks (`base`)
        self.by_base: dict[str, list[dict]] = defaultdict(list)
        #: noun plural / verb form -> the block it inflects
        self.by_inflection: dict[str, list[dict]] = defaultdict(list)
        self.undefined: dict[str, list[str]] = data.get("undefined", {})
        #: The recordings of the headwords CALD lists but never defines
        #: (`abandonment`: examples only), ``{headword: [{"classes", "pron"}]}``
        #: -- only those: the rest of the `pron` table is not kept (a defined
        #: headword's recording is on its blocks). Phase 2b's audio reads it.
        self.undefined_pron: dict[str, list[dict]] = {
            hw: entries for hw, entries in (data.get("pron") or {}).items()
            if hw in self.undefined}
        #: normalised phrase -> blocks whose headword is that phrase
        self.by_phrase: dict[str, list[dict]] = defaultdict(list)
        #: normalised phrase -> (block, sense) for `phrase` senses
        self.by_phrase_sense: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
        self.aliases: dict[str, str] = data.get("aliases", {})
        for key, blocks in data["headwords"].items():
            for block in blocks:
                self.blocks[block["id"]] = block
                for sense in block["senses"]:
                    self.senses[sense["ref"]] = (block, sense)
                    if sense.get("phrase"):
                        for form in phrase_forms(sense["phrase"]):
                            self.by_phrase_sense[form].append((block, sense))
                forms = {block["hw"].lower()}
                if block.get("base"):
                    forms.add(key.lower())  # `add up` for `add (sth) up`
                if block.get("redirect"):
                    self.redirects[key.lower()].append(block)
                for form in forms:
                    self.by_form[form].append(block)
                    if _is_multiword(form):
                        for phrase in phrase_forms(form):
                            self.by_phrase[phrase].append(block)
                if not block.get("redirect") and _is_multiword(key):
                    for phrase in phrase_forms(key):
                        if block not in self.by_phrase[phrase]:
                            self.by_phrase[phrase].append(block)
                for variant in block.get("variants") or []:
                    self.by_variant[variant["word"].lower()].append(block)
                for form in block.get("forms") or []:
                    self.by_inflection[form.lower()].append(block)
                if block.get("base") and block["cls"] == "v":
                    self.by_base[block["base"].lower()].append(block)

    # -- candidate senses -----------------------------------------------------

    def _refs(self, blocks: list[dict], our_pos: str, multiword: bool) -> list[str]:
        """Defined senses of the compatible blocks, de-duplicated by
        definition (a redirect page repeats its target's blocks; the
        canonical copy -- the one whose page IS its headword -- wins).

        For a one-word lemma a PHRASE sense (`keep your promise` in `keep`)
        is left out: it defines the phrase, not the word. Unless the word
        has nothing else -- CALD defines `accordance`, `culminate`, `devoid`
        and `brunt` ONLY through their pattern (`in accordance with sth`,
        `culminate in sth`), and there the pattern IS the word's meaning."""
        plain: dict[str, str] = {}
        phrased: dict[str, str] = {}
        ordered = sorted(blocks, key=lambda b: (b["redirect"], b["key"].lower() != b["hw"].lower()))
        for block in ordered:
            if not compatible(our_pos, block["cls"], multiword):
                continue
            for sense in block["senses"]:
                bucket = phrased if sense.get("phrase") and not multiword else plain
                bucket.setdefault(_norm_def(sense["def"]), sense["ref"])
        return list(dict.fromkeys((plain or phrased).values()))

    def exact_blocks(self, form: str) -> list[dict]:
        return self.by_form.get(form.lower(), [])

    def match(self, lemma: str, pos: str) -> Match:
        """See the module docstring: the steps of :data:`MATCH_STEPS` in
        order, the first that yields a candidate sense wins; nothing found is
        ``headword-only``, ``no-definition`` or ``none``."""
        lemma = clean_text(lemma).lower()
        pos = (pos or "").strip()
        multi = _is_multiword(lemma)

        def found(how: str, via: str, blocks: list[dict], *, via_block: bool = False,
                  refs: list[str] | None = None) -> Match | None:
            refs = refs if refs is not None else self._refs(blocks, pos, multi)
            if not refs:
                return None
            return Match(kind="exact" if how == "exact" else "variant", how=how,
                         via=self._via(refs) if via_block else via, refs=refs)

        def exact():
            return found("exact", lemma, self.exact_blocks(lemma))

        def alias():
            canonical = self.aliases.get(lemma)
            if canonical and alias_is_same(lemma, canonical):
                return found("alias", canonical, self.exact_blocks(canonical))
            return None

        def cald_variant():
            return found("cald-variant", lemma, self.by_variant.get(lemma, []), via_block=True)

        def redirect():
            return found("redirect", lemma, self.redirects.get(lemma, []), via_block=True)

        def spelling():
            for depth in (1, 2):
                for variant in sorted(spelling_variants(lemma, depth)):
                    hit = found("spelling", variant, self.exact_blocks(variant))
                    if hit:
                        return hit
            return None

        def idiom():
            if not multi:
                return None
            for form in sorted(phrase_forms(lemma)):
                blocks = self.by_phrase.get(form, [])
                if not _is_multiword(form):  # `the internet` -> `internet`
                    blocks = blocks + self.exact_blocks(form)
                hit = found("idiom", form, blocks)
                if hit:
                    return hit
            return None

        def idiom_sense():
            # A phrase sense defines the PHRASE, so the class of the block
            # it sits in (`on account of sth` inside `account` NOUN) says
            # nothing about the lexeme's pos: no compatibility test here.
            if not multi:
                return None
            refs, via = [], ""
            for form in sorted(phrase_forms(lemma)):
                for _, sense in self.by_phrase_sense.get(form, []):
                    if sense["ref"] not in refs:
                        refs.append(sense["ref"])
                        via = via or sense["phrase"]
            return found("idiom-sense", via, [], refs=refs) if refs else None

        def hyphen():
            for variant in sorted(hyphen_variants(lemma)):
                hit = found("hyphen", variant, self.exact_blocks(variant))
                if hit:
                    return hit
            return None

        def plural():
            if pos != "n":
                return None
            hit = found("plural", lemma, [b for b in self.by_inflection.get(lemma, [])
                                          if b["cls"] == "n"], via_block=True)
            for singular in [] if hit else singular_candidates(lemma):
                hit = found("plural", singular,
                            [b for b in self.exact_blocks(singular) if b["cls"] == "n"])
                if hit:
                    break
            return hit

        def verb_form():
            if pos != "v":
                return None
            return found("verb-form", lemma, [b for b in self.by_inflection.get(lemma, [])
                                              if b["cls"] == "v"], via_block=True)

        def phrasal_verb():
            # CALD defines `attribute`, `resort`, `hinge` ONLY as `attribute
            # sth to sb`, `resort to sth`, `hinge on sth`; a one-word verb
            # with nothing else is offered those (the model may still say
            # none -- `sum` is not `sum up`).
            if pos != "v" or multi:
                return None
            refs = self._refs(self.by_base.get(lemma, []), pos, True)
            return found("phrasal-verb", "", [], refs=refs, via_block=True) if refs else None

        steps = {"exact": exact, "alias": alias, "cald-variant": cald_variant,
                 "redirect": redirect, "spelling": spelling, "idiom": idiom,
                 "idiom-sense": idiom_sense, "hyphen": hyphen, "plural": plural,
                 "verb-form": verb_form, "phrasal-verb": phrasal_verb}
        for name in MATCH_STEPS:
            hit = steps[name]()
            if hit:
                return hit
        classes = sorted({b["cls"] for b in self.exact_blocks(lemma)})
        if classes:
            return Match(kind="headword-only", cald_classes=classes)
        if lemma in self.undefined:
            return Match(kind="no-definition", cald_classes=self.undefined[lemma])
        missing = Match(kind="none")
        if lemma in self.aliases:
            # The extract has no page for the word at all; its search lands
            # on another headword's page (`aspect` -> `aspect ratio`).
            missing.via = self.aliases[lemma]
            missing.how = "alias-elsewhere"
        return missing

    def _via(self, refs: list[str]) -> str:
        block, _ = self.senses[refs[0]]
        return block["hw"]

    def candidates(self, refs: list[str]) -> list[dict]:
        """Display records for a list of refs, in the order given."""
        out = []
        for ref in refs:
            block, sense = self.senses[ref]
            out.append({
                "ref": ref, "hw": block["hw"], "pos": block["pos"] or "", "cls": block["cls"],
                "gw": block["gw"], "def": sense["def"], "level": sense["level"],
                "phrase": sense.get("phrase"), "ex": sense.get("ex", ""),
                "xref_only": bool(sense.get("xref_only")),
            })
        return out


# --- Database (read only) -----------------------------------------------------------


@asynccontextmanager
async def readonly_connection():
    """A connection Postgres itself will not let write: the transaction is
    opened ``READ ONLY`` and rolled back at the end. See the module
    docstring -- phase 1 never writes, and this makes that a property of the
    connection rather than of the code. A plain SQLAlchemy connection, not a
    sqlmodel session: every query here is a fixed SELECT returning plain
    rows, never a model object."""
    from sqlalchemy import text

    from app.core.database import engine

    async with engine.connect() as conn:
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        try:
            yield conn
        finally:
            await conn.rollback()


@dataclass
class OurSense:
    id: str
    lexeme_id: str
    lemma: str
    pos: str
    sense_rank: int
    definition_en: str
    meaning_uz: str
    meaning_uz_alt: str
    cefr: str | None
    source_id: str


@dataclass
class Lexicon:
    lexemes: list[dict]  # {"id", "lemma", "pos"}
    senses: list[OurSense]
    saved_senses: set[str]
    word_list_senses: set[str]
    word_list_lexemes: set[str]
    material_senses: set[str]


async def load_lexicon() -> Lexicon:
    """Every vocabulary lexeme (no proper nouns, no function words -- neither
    is taught, so neither needs a CALD definition) with its senses,
    and which senses something points at."""
    from sqlalchemy import text

    async with readonly_connection() as conn:
        rows = (await conn.execute(text(
            "select id, lemma, pos from lexemes "
            "where not is_proper_noun and not is_function_word order by lemma, pos"))).all()
        lexemes = [{"id": str(r[0]), "lemma": r[1], "pos": r[2] or ""} for r in rows]
        keep = {lx["id"]: lx for lx in lexemes}
        senses = []
        for r in (await conn.execute(text(
                "select id, lexeme_id, sense_rank, definition_en, meaning_uz, meaning_uz_alt, "
                "cefr, source_id from lexeme_senses order by lexeme_id, sense_rank, id"))).all():
            lx = keep.get(str(r[1]))
            if lx is None:
                continue
            senses.append(OurSense(id=str(r[0]), lexeme_id=str(r[1]), lemma=lx["lemma"],
                                   pos=lx["pos"], sense_rank=r[2], definition_en=r[3] or "",
                                   meaning_uz=r[4] or "", meaning_uz_alt=r[5] or "",
                                   cefr=r[6], source_id=r[7] or ""))
        saved = {str(r[0]) for r in (await conn.execute(text(
            "select distinct lexeme_sense_id from saved_words "
            "where lexeme_sense_id is not null"))).all()}
        wl_rows = (await conn.execute(text(
            "select lexeme_id, sense_id from word_list_entries"))).all()
        material = {str(r[0]) for r in (await conn.execute(text(
            "select distinct sense_id from material_vocabulary where sense_id is not null"))).all()}
    sense_lexeme = {s.id: s.lexeme_id for s in senses}
    wl_senses = {str(r[1]) for r in wl_rows if r[1] is not None}
    wl_lexemes = {str(r[0]) for r in wl_rows if r[0] is not None}
    wl_lexemes |= {sense_lexeme[s] for s in wl_senses if s in sense_lexeme}
    return Lexicon(lexemes=lexemes, senses=senses, saved_senses=saved,
                   word_list_senses=wl_senses, word_list_lexemes=wl_lexemes,
                   material_senses=material)


async def load_example_candidates(sense_ids: list[str], conn=None) -> dict[str, list[str]]:
    """Every passage sentence a sense's `material_vocabulary` rows offer, in
    a FIXED order -- a visible row before a hidden one, the shortest first,
    then by text -- each cut to a window around the word
    (`lexicon_enrich.example_window`). The order must not depend on where
    Postgres keeps the rows: apply's own UPDATEs move them, and the sentence
    is part of every question's key (:func:`load_items` picks among these).
    On ``conn`` when given, else on a read-only connection of its own."""
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import ARRAY, UUID

    from app.services.lexicon_enrich import example_window

    if not sense_ids:
        return {}
    stmt = text(
        "select sense_id, example, surface, lemma from material_vocabulary "
        "where sense_id = any(:ids) and example <> '' "
        "order by sense_id, hidden, length(example), example, id"
    ).bindparams(bindparam("ids", type_=ARRAY(UUID(as_uuid=True))))
    params = {"ids": [uuid.UUID(s) for s in sense_ids]}
    if conn is not None:
        rows = (await conn.execute(stmt, params)).all()
    else:
        async with readonly_connection() as own:
            rows = (await own.execute(stmt, params)).all()
    out: dict[str, list[str]] = defaultdict(list)
    for sense_id, example, surface, lemma in rows:
        window = example_window(example, surface or "", lemma or "")
        if window not in out[str(sense_id)]:
            out[str(sense_id)].append(window)
    return dict(out)


async def load_examples(sense_ids: list[str], conn=None) -> dict[str, str]:
    """One passage sentence per sense: the first of
    :func:`load_example_candidates` (the pilot's sample)."""
    return {k: v[0] for k, v in (await load_example_candidates(sense_ids, conn)).items() if v}


# --- The decision log -----------------------------------------------------------------


def _hash(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:16]


class DecisionLog:
    """Append-only JSONL of every model answer this pilot paid for, keyed by
    ``(kind, key)`` -- the key says what was ASKED, so a changed question
    (another candidate list, another definition) is a new key and is asked
    again rather than answered from a stale record. The last record for a
    key wins."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.records: dict[tuple[str, str], dict] = {}
        #: (kind, sense id) -> newest record: :meth:`latest` without a scan
        #: (the full run's log holds tens of thousands of records).
        self._newest: dict[tuple[str, str], dict] = {}
        self._stamp = None
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._remember(json.loads(line))
            self._stamp = self._file_stamp()

    def _file_stamp(self):
        stat = self.path.stat()
        return (stat.st_size, stat.st_mtime_ns)

    def _remember(self, record: dict) -> None:
        self.records[(record["kind"], record["key"])] = record
        sense_id = record.get("sense_id")
        if sense_id is not None:
            slot = (record["kind"], sense_id)
            found = self._newest.get(slot)
            if found is None or record["at"] >= found["at"]:
                self._newest[slot] = record

    def stale(self) -> bool:
        """Whether another process appended since this copy was read (the
        worker keeps one log for its lifetime; the CLI may write meanwhile)."""
        if not self.path.exists():
            return self._stamp is not None
        return self._file_stamp() != self._stamp

    def get(self, kind: str, key: str) -> dict | None:
        return self.records.get((kind, key))

    def put(self, kind: str, key: str, payload: dict) -> dict:
        record = {"kind": kind, "key": key, **payload,
                  "at": datetime.now(timezone.utc).isoformat()}
        self._remember(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._stamp = self._file_stamp()
        return record

    def latest(self, kind: str, sense_id: str) -> dict | None:
        """The newest record of ``kind`` for a sense, whatever its key."""
        return self._newest.get((kind, sense_id))


def model_cost(model: str, usage) -> float:
    """`Usage.cost`, plus the models `lexicon_enrich.PRICES` does not carry
    (:data:`EXTRA_PRICES`) -- a model with no known price is reported at 0
    rather than guessed."""
    from app.services import lexicon_enrich as le

    price_in, price_out = le.PRICES.get(model) or EXTRA_PRICES.get(model) or (0.0, 0.0)
    return (usage.input_tokens * price_in + usage.output_tokens * price_out) / 1e6



# --- map ------------------------------------------------------------------------------

MAP_PROMPT = """You are moving an English-Uzbek learner's dictionary onto the
Cambridge Advanced Learner's Dictionary. Each item below is ONE sense from our
dictionary: the word, its part of speech, our English definition, our Uzbek
translation and, where we have one, a sentence from a reading passage in which
learners met the word in this sense. Under it are the Cambridge senses of the
same word, each with an id (c1, c2, ...), its part of speech and, in capitals,
Cambridge's guideword.

For each item choose the ONE Cambridge sense that is the SAME MEANING as our
sense -- the one a learner would recognise as the same thing. Our definition
says what our sense means; the Uzbek and the sentence help when the definition
is short or vague. Cambridge splits and joins meanings differently from us:
choose the sense that covers our meaning even if it is a little broader or
narrower, and lower the confidence to say so.

Answer "none" when no Cambridge sense is this meaning -- our sense is another
meaning of the word, a technical sense Cambridge does not list, or the word in
another part of speech. Do not pick the nearest sense just to pick something.
Never write a definition of your own: answer with one of the given ids or
"none".

confidence:
- "high": clearly the same meaning;
- "medium": the same meaning, but one side is clearly broader or narrower, or
  our definition is too vague to be sure;
- "low": a best guess.
reason: at most 20 words, in English.

{items}

Reply with JSON only:
{{"answers": {{"k1": {{"choice": "c2", "confidence": "high", "reason": "..."}},
  "k2": {{"choice": "none", "confidence": "high", "reason": "..."}}}}}}
Answer every item."""

CONFIDENCES = ("high", "medium", "low")
#: Candidates shown per item. `take` (v) has ~60 defined senses in CALD; a
#: longer list is cut (logged) rather than sent whole.
MAX_CANDIDATES = 70
MAP_BATCH_ITEMS = 6
#: Part of every map decision's key: a change to how an item is shown to
#: the model is a different question, asked again rather than answered from
#: a record made under the old rendering. 3: the key carries the CONTENT of
#: every candidate shown (:func:`candidate_fingerprints`), our Uzbek and the
#: sentence -- a ref is a position in the source file, and the corrected
#: source moved thousands of them.
MAP_VERSION = 3
MAP_BATCH_CANDIDATES = 140


def candidate_fingerprints(cands: list[dict]) -> list[list]:
    """Everything of a candidate the map prompt shows, in order -- what makes
    two questions the same question (:func:`map_key`)."""
    return [[c["ref"], c["hw"], c["pos"] or "", c["gw"] or "", c["def"], c.get("phrase") or "",
             bool(c.get("xref_only"))] for c in cands]


def map_key(item: dict, cands: list[dict]) -> str:
    """What a ``map`` record answers: this sense, as shown (definition, Uzbek,
    sentence), against these candidates as shown. ``cands`` are
    :meth:`CaldIndex.candidates` records."""
    return (f"{item['sense_id']}|"
            f"{_hash(MAP_VERSION, candidate_fingerprints(cands), item['definition_en'], item.get('meaning_uz') or '', item.get('meaning_uz_alt') or '', item.get('example') or '')}")


def render_map_item(key: str, item: dict, candidates: list[dict]) -> str:
    lines = [f"{key}  {item['lemma']} ({item['pos'] or '?'})",
             f"  Our definition: \"{item['definition_en']}\""]
    uz = item["meaning_uz"]
    if item.get("meaning_uz_alt") and item["meaning_uz_alt"] != uz:
        uz = f"{uz}  (also: {item['meaning_uz_alt']})"
    if uz:
        lines.append(f"  Our Uzbek: \"{uz}\"")
    if item.get("example"):
        lines.append(f"  Passage sentence: \"{item['example']}\"")
    lines.append("  Cambridge senses:")
    for cand in candidates:
        tag = cand["pos"] or "idiom"
        if cand.get("gw"):
            tag += f" · {cand['gw']}"
        if cand.get("phrase"):
            tag += f" · phrase \"{cand['phrase']}\""
        text = (f"(Cambridge gives no definition here, only a pointer to \"{cand['def']}\")"
                if cand.get("xref_only") else cand["def"])
        lines.append(f"    {cand['cid']} [{tag}] {text}")
    return "\n".join(lines)


def parse_map_answer(value: object, candidates: list[dict]) -> dict | None:
    """One item's answer as ``{"ref", "confidence", "reason"}`` (``ref`` is
    ``None`` for "none"), or ``None`` when it is not a usable answer: a
    choice that names no shown candidate is not quietly read as "none". A
    missing or unknown confidence is ``low`` -- an answer cannot be MORE
    certain than it said."""
    if isinstance(value, str):
        value = {"choice": value}
    if not isinstance(value, dict):
        return None
    choice = str(value.get("choice") or value.get("ref") or "").strip()
    by_cid = {c["cid"]: c for c in candidates}
    by_ref = {c["ref"]: c for c in candidates}
    if choice.lower() == "none":
        ref = None
    elif choice.lower() in by_cid:
        ref = by_cid[choice.lower()]["ref"]
    elif choice in by_ref:
        ref = choice
    else:
        return None
    confidence = str(value.get("confidence") or "").strip().lower()
    if confidence not in CONFIDENCES:
        confidence = "low"
    reason = " ".join(str(value.get("reason") or "").split())[:300]
    return {"ref": ref, "confidence": confidence, "reason": reason}


def _map_batches(items: list[tuple[dict, list[dict]]]) -> list[list[tuple[dict, list[dict]]]]:
    batches, current, count = [], [], 0
    for item, cands in items:
        if current and (len(current) >= MAP_BATCH_ITEMS or count + len(cands) > MAP_BATCH_CANDIDATES):
            batches.append(current)
            current, count = [], 0
        current.append((item, cands))
        count += len(cands)
    if current:
        batches.append(current)
    return batches


async def ask_map(gemini, model: str, items: list[tuple[dict, list[dict]]], *,
                  concurrency: int = 4, on_answers=None, before_request=None) -> dict[str, dict]:
    """sense id -> parsed answer for every item the model answered usably;
    items a reply skipped or garbled are asked once more on their own.
    ``on_answers(answers)`` is called with each request's answers as they
    arrive (the full run logs them there, so a stop loses nothing it paid
    for); ``before_request()`` runs before each request (the budget check
    -- it may raise)."""
    out: dict[str, dict] = {}

    async def ask(batch: list[tuple[dict, list[dict]]]) -> None:
        keyed = {f"k{i}": pair for i, pair in enumerate(batch, 1)}
        text = "\n\n".join(render_map_item(k, item, cands) for k, (item, cands) in keyed.items())
        if before_request is not None:
            before_request()
        reply = await gemini.ask(model, MAP_PROMPT.format(items=text), step="cald-map",
                                 max_tokens=2000 + 400 * len(batch))
        answers = reply.get("answers") if reply and isinstance(reply.get("answers"), dict) else {}
        got = {}
        for key, (item, cands) in keyed.items():
            parsed = parse_map_answer(answers.get(key), cands)
            if parsed is not None:
                got[item["sense_id"]] = parsed
        out.update(got)
        if on_answers is not None and got:
            on_answers(got)

    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(batch):
        async with semaphore:
            await ask(batch)

    await asyncio.gather(*(guarded(b) for b in _map_batches(items)))
    missing = [pair for pair in items if pair[0]["sense_id"] not in out]
    await asyncio.gather(*(guarded([pair]) for pair in missing))
    return out


# --- Round 2: what the pilot review settled -------------------------------------------

#: Mapping confidences the full run applies (agreed after the pilot
#: review): ``low`` is treated as ``none`` -- the old definition stays.
ACCEPTED_CONFIDENCES: tuple[str, ...] = ("high", "medium")

#: One English pos word in a pointer "definition" (``aerial noun``) -> the
#: class of the target block it points into.
_POINTER_POS = {"noun": "n", "verb": "v", "adjective": "adj", "adverb": "adv",
                "preposition": "prep", "exclamation": "excl", "pronoun": "pron",
                "determiner": "det", "conjunction": "conj"}
_POINTER_TOPIC = re.compile(r"\(([A-Z][A-Z ,/'&-]+)\)")


def pointer_target(sense: dict, block_cls: str) -> tuple[str, str, str]:
    """``(target headword, target class, topic hint)`` for a pointer-only
    sense (``xref_only``). The class is the pos word the pointer names
    (``aerial noun`` -> ``n``), else the class of the block the pointer sits
    in (`pee` verb -> `urinate` verb). The topic is a capitalised hint in
    brackets (``pop noun (MUSIC)``), used to narrow the target's blocks by
    guideword."""
    target = sense["xref"][0]
    rest = sense["def"].replace(target, " ", 1)
    cls = block_cls
    for word, word_cls in _POINTER_POS.items():
        if re.search(rf"\b{word}\b", rest.lower()):
            cls = word_cls
            break
    topic = _POINTER_TOPIC.search(rest)
    return target, cls, topic.group(1) if topic else ""


def pointer_candidates(index: CaldIndex, ref: str, our_pos: str) -> list[str]:
    """The senses a pointer can be followed to (agreed rule 2): the target
    headword's defined senses in the pointed-to class, narrowed to the
    blocks whose guideword matches the topic hint when one does, never a
    pointer again (one hop only -- a chain is "cannot resolve"), and only in
    a class compatible with OUR lexeme's pos."""
    block, sense = index.senses[ref]
    target, cls, topic = pointer_target(sense, block["cls"])
    multi = _is_multiword(target)
    blocks = [b for b in index.exact_blocks(target)
              if b["cls"] == cls and compatible(our_pos, b["cls"], multi)]
    if topic:
        narrowed = [b for b in blocks if b["gw"] and (topic.lower() in b["gw"].lower()
                                                     or b["gw"].lower() in topic.lower())]
        blocks = narrowed or blocks
    refs = [s["ref"] for b in blocks for s in b["senses"]
            if not s.get("xref_only") and not (s.get("phrase") and not multi)]
    return list(dict.fromkeys(refs))


#: Part of every pointer-follow key -- see :data:`MAP_VERSION`. 2: content,
#: not refs, and the sense as shown.
XREF_VERSION = 2


def xref_key(item: dict, pointer_ref: str, candidates: list[str], index: CaldIndex) -> str:
    shown = index.candidates([pointer_ref, *candidates])
    return (f"{item['sense_id']}|{pointer_ref}|"
            f"{_hash(XREF_VERSION, candidate_fingerprints(shown), item['definition_en'], item.get('meaning_uz') or '', item.get('meaning_uz_alt') or '', item.get('example') or '')}")


def map_record(log: DecisionLog, item: dict, index: CaldIndex, *, keyed: bool) -> dict | None:
    """The map answer for a sense: ``keyed`` (the full run) -- the record for
    the question as it stands now (:func:`map_key`), so a sense whose
    definition or candidates changed has none; else (the pilot's review) the
    newest record for the sense, whatever it was asked."""
    if keyed:
        refs = [r for r in item["refs"] if r in index.senses]
        return log.get("map", map_key(item, index.candidates(refs)))
    return log.latest("map", item["sense_id"])


def effective_mapping(log: DecisionLog, item: dict, index: CaldIndex, *,
                      keyed: bool = False) -> dict:
    """The mapping phase 2 APPLIES for one sense, under the agreed rules: the
    map answer (:func:`map_record`); a confidence outside
    :data:`ACCEPTED_CONFIDENCES` is ``none``; a pointer-only CALD sense is
    replaced by the sense it was followed to (``xref``), and one that could
    not be followed is ``none``. ``{"decision": mapped|none|unanswered,
    "ref", "pointer_ref", "confidence", "reason", "follow"}``."""
    out = {"decision": "unanswered", "ref": None, "pointer_ref": None, "confidence": "",
           "reason": "", "follow": None}
    mapped = map_record(log, item, index, keyed=keyed)
    if not mapped or not mapped.get("answered"):
        return out
    out["confidence"], out["reason"] = mapped.get("confidence", ""), mapped.get("reason", "")
    ref = mapped.get("ref")
    if not ref or ref not in index.senses:
        out["decision"] = "none"
        return out
    if out["confidence"] not in ACCEPTED_CONFIDENCES:
        out.update(decision="none", reason=f"[{out['confidence']} -- not applied] {out['reason']}")
        return out
    block, sense = index.senses[ref]
    if sense.get("xref_only"):
        out["pointer_ref"] = ref
        cands = pointer_candidates(index, ref, item["pos"])
        follow = log.get("xref", xref_key(item, ref, cands, index))
        out["follow"] = follow
        if not follow or not follow.get("ref") or follow["ref"] not in index.senses:
            out.update(decision="none",
                       reason=f"[pointer to \"{pointer_target(sense, block['cls'])[0]}\" "
                              f"not resolved] {out['reason']}")
            return out
        ref = follow["ref"]
    out.update(decision="mapped", ref=ref)
    return out


async def follow_pointers(sample: dict, log: DecisionLog, index: CaldIndex, gemini, model: str,
                          *, keyed: bool = False, concurrency: int = 4,
                          before_request=None) -> Counter:
    """Agreed rule 2 for every mapped sense (``sample["items"]``) whose
    chosen CALD sense is a pointer: one candidate is taken as it is
    (``single``), several are chosen among by the model with the same prompt
    the mapper uses (``model``), none -- or the model saying none -- is
    ``unresolved`` and the sense counts as ``none``. Each outcome is a
    ``xref`` record. A sense the model did not answer usably is NOT recorded
    (``unanswered``): the next run asks again."""
    counts: Counter = Counter()
    ask: list[tuple[dict, list[dict], str, str]] = []
    for item in sample["items"]:
        mapped = map_record(log, item, index, keyed=keyed)
        if (not mapped or not mapped.get("ref") or mapped.get("confidence") not in
                ACCEPTED_CONFIDENCES or mapped["ref"] not in index.senses):
            continue
        pointer_ref = mapped["ref"]
        if not index.senses[pointer_ref][1].get("xref_only"):
            continue
        cands = pointer_candidates(index, pointer_ref, item["pos"])
        key = xref_key(item, pointer_ref, cands, index)
        if log.get("xref", key):
            counts["reused"] += 1
            continue
        base = {"sense_id": item["sense_id"], "lemma": item["lemma"], "pointer_ref": pointer_ref,
                "target": pointer_target(index.senses[pointer_ref][1],
                                         index.senses[pointer_ref][0]["cls"])[0],
                "candidates": cands}
        if len(cands) <= 1:
            how = "single" if cands else "unresolved"
            log.put("xref", key, {**base, "ref": cands[0] if cands else None, "how": how})
            counts[how] += 1
            continue
        shown = index.candidates(cands)
        for i, cand in enumerate(shown, 1):
            cand["cid"] = f"c{i}"
        ask.append((item, shown, key, base))
    if ask:
        answers = await ask_map(gemini, model, [(item, shown) for item, shown, _, _ in ask],
                                concurrency=concurrency, before_request=before_request)
        for item, _, key, base in ask:
            answer = answers.get(item["sense_id"])
            if answer is None:
                counts["unanswered"] += 1
                continue
            ref = answer["ref"]
            log.put("xref", key, {**base, "ref": ref, "how": "model" if ref else "unresolved",
                                  "model": model, **({"confidence": answer["confidence"],
                                                      "reason": answer["reason"]} if answer else {})})
            counts["model" if ref else "unresolved"] += 1
    return counts


# --- Translation v2 ---------------------------------------------------------------------

#: Part of every v2 translation's key -- see `MAP_VERSION`.
TRANSLATE_V2_VERSION = 1
V2_FLAGS: tuple[str, ...] = ("kept", "adjusted", "replaced")

TRANSLATE_V2_PROMPT = """You are revising the Uzbek side of an English-Uzbek
learner's dictionary. The readers are Uzbek speakers learning English (IELTS
band 5-6).

Each item gives an English word, its part of speech, ONE sense of it -- a
definition from the Cambridge dictionary, with Cambridge's guideword in
capitals where it has one -- and, where we have one, a sentence from a reading
passage that uses the word in exactly this sense. It also gives the Uzbek our
dictionary has for the word now ("current"), with a second translator's
version where there is one ("alternative").

Give the Uzbek word or short phrase a good English-Uzbek dictionary would print
for the word IN THIS SENSE:
- If the current Uzbek is correct for this sense, KEEP it. You may adjust it --
  drop a synonym that belongs to another sense, fix the spelling, put a verb in
  the -moq form -- but do not rewrite a correct translation for style.
- Every synonym you give must fit THIS definition, not the word's other
  meanings ("lasting a long time" is not "stubborn").
- It must fit how the word is used in the sentence: an intransitive use ("the
  satellite smashed into a rocket") needs an intransitive Uzbek verb, a
  transitive use a transitive one.
- Use only real, standard modern Uzbek words, Latin script, with ' in o' and
  g'. Never invent a word or a form. Do not transliterate the English word
  unless Uzbek really uses that loanword. At most about eight words, synonyms
  separated by commas.

Say what you did: "kept" (the current Uzbek, unchanged), "adjusted" (the
current Uzbek, lightly corrected), or "replaced" (the current Uzbek was wrong
for this sense, or there was none), and why, in one short line of English.

{items}

Reply with JSON only:
{{"items": {{"k1": {{"uz": "...", "flag": "kept", "reason": "..."}}, ...}}}}"""

COMPARE_VERSION = 1
COMPARE_PROMPT = """Each item gives an English word, its part of speech, ONE
sense of it (a Cambridge dictionary definition, with its guideword where it has
one), a sentence from a reading passage that uses the word in this sense where
we have one, and two Uzbek renderings of the word in this sense, A and B. A
rendering is one line, or two lines from two translators separated by "/".

For each item decide:
- "wrong_a" / "wrong_b": true when that rendering is wrong for this sense --
  it, or any word or synonym in it, names another meaning of the English word
  or a different thing; it does not fit how the word is used in the sentence
  (a transitive Uzbek verb for an intransitive use, or the other way round); it
  contains a word that is not real, standard Uzbek; or it is a transliteration
  of the English that Uzbek does not use. Otherwise false.
- "better": the one a good bilingual dictionary would print for this sense:
  "a", "b", or "equal" when a learner would take away the same meaning from
  either.
- "reason": one short line in English.

{items}

Reply with JSON only:
{{"verdicts": {{"k1": {{"wrong_a": false, "wrong_b": true, "better": "a", "reason": "..."}},
  ...}}}}
Answer every item."""

#: USD per 1M tokens (input, output) for models `lexicon_enrich.PRICES` does
#: not carry, read from ai.google.dev/gemini-api/docs/pricing on 2026-10-07
#: (3.7 Flash doubles on 2027-01-01, as 3.8 Flash does). Only a judge
#: calibration run uses them.
EXTRA_PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.7-flash": (0.75, 3.75),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3.1-pro-preview": (2.00, 12.00),
}


def _uz_norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w' ,]+", " ", (text or "").lower()).split())


def _sense_line(cald: dict) -> str:
    gw = f"[{cald['gw']}] " if cald.get("gw") else ""
    return f"{gw}{cald['def']}"


def render_v2_item(key: str, entry: dict) -> str:
    lines = [f"{key}: {entry['lemma']} ({entry['pos'] or '?'})",
             f"  Sense: {_sense_line(entry['cald'])}"]
    if entry.get("example"):
        lines.append(f"  Passage: \"{entry['example']}\"")
    current, alt = entry["old_uz"], entry["old_alt"]
    if current:
        also = f" (alternative: \"{alt}\")" if alt and alt != current else ""
        lines.append(f"  Current Uzbek: \"{current}\"{also}")
    else:
        lines.append("  Current Uzbek: none")
    return "\n".join(lines)


def parse_v2_item(value: object, entry: dict) -> dict | None:
    """One translator's v2 answer, or None when unusable (no Uzbek). An
    unknown flag is replaced by what the text shows -- ``kept`` when it is
    the current Uzbek, else ``replaced`` (the claim of more change, never
    less) -- and ``flag_given`` says so. ``changed`` is the text fact, kept
    beside the model's own flag so a "kept" that was not is visible."""
    from app.services.lexicon_enrich import _clean_uz

    if isinstance(value, str):
        value = {"uz": value}
    if not isinstance(value, dict):
        return None
    uz = _clean_uz(value.get("uz")).rstrip(".").strip()
    if not uz:
        return None
    changed = _uz_norm(uz) != _uz_norm(entry["old_uz"])
    flag = str(value.get("flag") or "").strip().lower()
    given = flag in V2_FLAGS
    if not given:
        flag = "replaced" if changed else "kept"
    reason = " ".join(str(value.get("reason") or "").split())[:300]
    return {"uz": uz, "flag": flag, "flag_given": given, "changed": changed, "reason": reason}


def _pair_text(uz: str, alt: str) -> str:
    return f"\"{uz}\"" + (f" / \"{alt}\"" if alt and alt != uz else "")


def render_compare_item(key: str, entry: dict) -> str:
    """Run 1 shows OLD as A; run 2 (``swap``) shows NEW as A -- a judge that
    leans to one position leans both ways, instead of always for one side."""
    old, new = (entry["old_uz"], entry["old_alt"]), (entry["new_uz"], entry["new_alt"])
    a, b = (new, old) if entry["swap"] else (old, new)
    lines = [f"{key}: {entry['lemma']} ({entry['pos'] or '?'})",
             f"  Sense: {_sense_line(entry['cald'])}"]
    if entry.get("example"):
        lines.append(f"  Passage: \"{entry['example']}\"")
    lines += [f"  A: {_pair_text(*a)}", f"  B: {_pair_text(*b)}"]
    return "\n".join(lines)


def _truthy(value: object) -> bool:
    return value is True or str(value).strip().lower() in ("true", "yes", "1")


def parse_compare_item(value: object, entry: dict) -> dict | None:
    """One judge run's verdict for one item in OLD/NEW terms (A/B undone
    by ``swap``), or None when ``better`` is missing or unknown -- no
    verdict, never a guessed one."""
    if not isinstance(value, dict):
        return None
    better = str(value.get("better") or "").strip().lower()
    if better not in ("a", "b", "equal"):
        return None
    wrong_a, wrong_b = _truthy(value.get("wrong_a")), _truthy(value.get("wrong_b"))
    swap = entry["swap"]
    side = {"a": "new" if swap else "old", "b": "old" if swap else "new", "equal": "equal"}[better]
    return {"better": side, "wrong_old": wrong_b if swap else wrong_a,
            "wrong_new": wrong_a if swap else wrong_b,
            "reason": " ".join(str(value.get("reason") or "").split())[:300]}


def combine_comparison(runs: list[dict | None]) -> dict:
    """Two comparison runs -> the keep decision, under the rule proposed
    with the owner: keep the NEW pair unless the judges say the old one is
    better or the new one is wrong. "The judges say" is read as BOTH runs
    say it, the same evidence bar `lexicon_enrich.combine_verdicts` sets (one
    run alone flips ~13% of pairs); a single run saying so is not enough to
    revert but is flagged ``disputed`` for a human. ``loose_keep`` is the
    other reading (EITHER run reverts), reported so the choice between them
    is made on numbers. ``both_wrong``: every run calls both renderings
    wrong -- neither should be kept without a human."""
    answered = [r for r in runs if r]
    n = len(answered)
    old_better = sum(r["better"] == "old" for r in answered)
    new_better = sum(r["better"] == "new" for r in answered)
    equal = sum(r["better"] == "equal" for r in answered)
    wrong_old = sum(r["wrong_old"] for r in answered)
    wrong_new = sum(r["wrong_new"] for r in answered)
    revert = n == 2 and (old_better == 2 or wrong_new == 2)
    against_new = old_better + wrong_new > 0
    flags = []
    if n < 2:
        flags.append("no-verdict" if n == 0 else "one-run")
    if against_new and not revert:
        flags.append("disputed")
    if n and wrong_old == n and wrong_new == n:
        flags.append("both_wrong")
    return {"keep": "old" if revert else "new", "loose_keep": "old" if against_new else "new",
            "runs": n, "old_better": old_better, "new_better": new_better, "equal": equal,
            "wrong_old": wrong_old, "wrong_new": wrong_new, "flags": flags}


async def ask_keyed(gemini, model: str, template: str, entries: list[dict], render, parse, *,
                    step: str, reply_key: str, batch: int = 20, per_item_tokens: int = 250,
                    concurrency: int = 4, on_answers=None, before_request=None
                    ) -> dict[str, dict]:
    """``entry["id"]`` -> parsed answer, for every entry the model answered
    usably. Entries go in batches; any a reply skipped or garbled are asked
    once more, one per request, so one refused item cannot sink its
    neighbours. Still nothing is no answer -- the caller records that.
    ``on_answers``/``before_request``: as for :func:`ask_map`."""
    out: dict[str, dict] = {}
    semaphore = asyncio.Semaphore(concurrency)

    async def ask(chunk: list[dict]) -> None:
        keyed = {f"k{i}": entry for i, entry in enumerate(chunk, 1)}
        text = "\n\n".join(render(k, e) for k, e in keyed.items())
        async with semaphore:
            if before_request is not None:
                before_request()
            reply = await gemini.ask(model, template.format(items=text), step=step,
                                     max_tokens=1500 + per_item_tokens * len(chunk))
        got = reply.get(reply_key) if reply and isinstance(reply.get(reply_key), dict) else {}
        answered = {}
        for key, entry in keyed.items():
            parsed = parse(got.get(key), entry)
            if parsed is not None:
                answered[entry["id"]] = parsed
        out.update(answered)
        if on_answers is not None and answered:
            on_answers(answered)

    await asyncio.gather(*(ask(entries[i:i + batch]) for i in range(0, len(entries), batch)))
    missing = [e for e in entries if e["id"] not in out]
    await asyncio.gather(*(ask([e]) for e in missing))
    return out


def v2_entry(item: dict, ref: str, index: CaldIndex) -> dict:
    block, sense = index.senses[ref]
    return {"id": item["sense_id"], "lemma": item["lemma"], "pos": item["pos"],
            "cald": {"def": sense["def"], "gw": block["gw"]}, "example": item.get("example", ""),
            "old_uz": item["meaning_uz"], "old_alt": item["meaning_uz_alt"], "ref": ref}


def translate2_key(entry: dict, model: str) -> str:
    return (f"{entry['id']}|{entry['ref']}|{model}|"
            f"{_hash(TRANSLATE_V2_VERSION, entry['cald'], entry['example'], entry['old_uz'], entry['old_alt'])}")


def compare_key(entry: dict, judge_model: str) -> str:
    return (f"{entry['id']}|{entry['ref']}|{judge_model}|"
            f"{_hash(COMPARE_VERSION, entry['cald'], entry['example'], entry['old_uz'], entry['old_alt'], entry['new_uz'], entry['new_alt'])}")


def v2_state(log: DecisionLog, item: dict, index: CaldIndex) -> dict | None:
    """Everything round 2 holds for one sense under its CURRENT effective
    mapping: both translators' v2 answers, the new pair they make, and the
    comparison per judge model found in the log. None when the sense is not
    mapped or not translated yet."""
    from app.services import lexicon_enrich as le

    mapping = effective_mapping(log, item, index)
    if mapping["decision"] != "mapped":
        return None
    entry = v2_entry(item, mapping["ref"], index)
    main = log.get("translate2", translate2_key(entry, le.MODEL_MAIN))
    alt = log.get("translate2", translate2_key(entry, le.MODEL_ALT))
    if not main and not alt:
        return None
    main_uz = (main or {}).get("uz", "")
    alt_uz = (alt or {}).get("uz", "")
    # The production convention (`step_translate`): the stronger model's
    # answer leads, the other translator's is the alternative.
    entry["new_uz"], entry["new_alt"] = (main_uz, alt_uz) if main_uz else (alt_uz, "")
    judges = sorted({r.get("judge_model") for (k, _), r in log.records.items() if k == "compare"}
                    - {None})
    compares = {}
    for judge in judges:
        record = log.get("compare", compare_key(entry, judge))
        if record:
            compares[judge] = record
    return {"entry": entry, "main": main, "alt": alt, "compare": compares}



# --- Phase 2a: the full run -------------------------------------------------------------

#: Everything CALD may spend, the pilot included (USD; `usage.jsonl` is the
#: running total). The owner approved about $16 for the full run; the run
#: stops long before anything surprising.
DEFAULT_BUDGET_USD = 25.0
#: Which senses the run is about: every sense of a vocabulary lexeme (no
#: proper noun, no function word -- neither is taught).
_CALD_COLUMNS = ("definition_source", "cald_ref", "cald_applied_at", "definition_en_pre_cald",
                 "cefr_pre_cald", "meaning_uz_pre_cald", "meaning_uz_alt_pre_cald",
                 "licence_pre_cald", "review_reasons_pre_cald")


class BudgetExceeded(RuntimeError):
    """The CALD spend reached the budget. Every answer paid for is already
    in the decision log; raise the budget (or don't) and re-run."""


def logged_spend(out_dir: Path = PRIVATE_DIR) -> float:
    """Every CALD command's cost so far, from :data:`USAGE_FILE`."""
    path = out_dir / USAGE_FILE
    if not path.exists():
        return 0.0
    total = 0.0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            total += float(json.loads(line).get("total_cost_usd") or 0.0)
    return total


def usage_cost(usage) -> float:
    return sum(model_cost(m, u) for m, u in usage.by_model.items())


@dataclass
class Budget:
    """``limit`` against what the log already holds (``before``) plus this
    run's own :class:`lexicon_enrich.UsageLog`. ``limit <= 0``: no limit."""

    limit: float
    before: float
    usage: object

    def spent(self) -> float:
        return self.before + usage_cost(self.usage)

    def check(self) -> None:
        if self.limit > 0 and self.spent() >= self.limit:
            raise BudgetExceeded(f"CALD spend ${self.spent():.2f} reached the ${self.limit:.2f} "
                                 f"budget")


def record_usage(out_dir: Path, cmd: str, usage) -> dict | None:
    """Append one :data:`USAGE_FILE` record for a command that asked
    anything; None when it asked nothing."""
    if not any(u.requests or u.failures for u in usage.by_model.values()):
        return None
    record = {
        "at": datetime.now(timezone.utc).isoformat(), "cmd": cmd,
        "total_cost_usd": round(usage_cost(usage), 6),
        "by_model": {m: {"requests": u.requests, "failures": u.failures,
                         "input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                         "cost_usd": round(model_cost(m, u), 6)} for m, u in usage.by_model.items()},
        "by_step": {s: {"requests": u.requests, "input_tokens": u.input_tokens,
                        "output_tokens": u.output_tokens} for s, u in usage.by_step.items()},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / USAGE_FILE).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


async def _has_cald_columns(conn) -> bool:
    """Whether the CALD migration has run on this database. The dry run must
    work on a database it has not reached yet: there, nothing was applied."""
    from sqlalchemy import text

    found = (await conn.execute(text(
        "select count(*) from information_schema.columns where table_schema = current_schema() "
        "and table_name = 'lexeme_senses' and column_name = 'cald_applied_at'"))).scalar_one()
    return bool(found)


async def load_items(index: CaldIndex, *, lexeme_ids: list | None = None, conn=None,
                     log: DecisionLog | None = None) -> list[dict]:
    """One item per sense of every vocabulary lexeme (or of ``lexeme_ids``),
    AS IT WAS BEFORE CALD: a sense already applied is described by its
    ``*_pre_cald`` columns, so the questions asked about it -- and so their
    keys in the log -- are the same before and after ``apply`` (which is
    what makes apply idempotent and a re-run free). ``current`` holds what
    the row says now. ``refs`` are the lexeme's candidate CALD senses
    (:meth:`CaldIndex.match`, cut to :data:`MAX_CANDIDATES`); empty for a
    lexeme CALD does not match. ``example``: the passage sentence the log
    already holds an answer for, among the sense's candidates
    (:func:`load_example_candidates`) -- else the first of them -- so the
    question stays the one that was asked while the rows behind it are
    re-levelled, re-ordered or joined by another. Read only."""
    if conn is None:
        async with readonly_connection() as own:
            return await load_items(index, lexeme_ids=lexeme_ids, conn=own, log=log)
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import ARRAY, UUID

    has_cald = await _has_cald_columns(conn)
    extra = "".join(f", s.{c}" for c in _CALD_COLUMNS) if has_cald else ""
    where = "where not l.is_proper_noun and not l.is_function_word"
    params: dict = {}
    stmt_text = (
        "select s.id, s.lexeme_id, s.sense_rank, s.definition_en, s.meaning_uz, s.meaning_uz_alt, "
        "s.cefr, s.source_id, s.licence, s.review_reasons, l.lemma, l.pos, l.frequency_band, "
        "s.approved_at" + extra + " from lexeme_senses s join lexemes l on l.id = s.lexeme_id "
        + where)
    if lexeme_ids is not None:
        stmt_text += " and l.id = any(:ids)"
        params["ids"] = [uuid.UUID(str(i)) for i in lexeme_ids]
    stmt = text(stmt_text + " order by l.lemma, l.pos, s.sense_rank, s.id")
    if "ids" in params:
        stmt = stmt.bindparams(bindparam("ids", type_=ARRAY(UUID(as_uuid=True))))
    rows = (await conn.execute(stmt, params)).mappings().all()
    examples = await load_example_candidates([str(r["id"]) for r in rows], conn=conn)
    matches: dict[tuple[str, str], Match] = {}
    items = []
    for r in rows:
        applied = has_cald and r["cald_applied_at"] is not None
        key = (r["lemma"], r["pos"] or "")
        if key not in matches:
            matches[key] = index.match(r["lemma"], r["pos"] or "")
        match = matches[key]

        def before(column: str, current, _r=r, _applied=applied):
            return _r[f"{column}_pre_cald"] if _applied else current

        items.append({
            "sense_id": str(r["id"]), "lexeme_id": str(r["lexeme_id"]), "lemma": r["lemma"],
            "pos": r["pos"] or "", "sense_rank": r["sense_rank"],
            "frequency_band": r["frequency_band"],
            "definition_en": before("definition_en", r["definition_en"]) or "",
            "meaning_uz": before("meaning_uz", r["meaning_uz"]) or "",
            "meaning_uz_alt": before("meaning_uz_alt", r["meaning_uz_alt"]) or "",
            "cefr": before("cefr", r["cefr"]),
            "licence": before("licence", r["licence"]) or r["licence"],
            "review_reasons": list(before("review_reasons", r["review_reasons"]) or []),
            "source_id": r["source_id"], "approved": r["approved_at"] is not None,
            "applied": applied,
            "current": {"definition_en": r["definition_en"], "meaning_uz": r["meaning_uz"],
                        "meaning_uz_alt": r["meaning_uz_alt"], "cefr": r["cefr"],
                        "cald_ref": r["cald_ref"] if has_cald else None,
                        "definition_source": r["definition_source"] if has_cald else
                        ("oewn" if r["source_id"] == "oewn" else "model")},
            "example": "",
            "match_kind": match.kind, "match_how": match.how, "match_via": match.via,
            "refs": match.refs[:MAX_CANDIDATES], "refs_cut": max(0, len(match.refs) - MAX_CANDIDATES),
        })
        items[-1]["example"] = _sticky_example(items[-1], examples.get(str(r["id"]), []),
                                               index, log)
    return items


def _sticky_example(item: dict, candidates: list[str], index: CaldIndex,
                    log: DecisionLog | None) -> str:
    """The candidate sentence whose map question the log already answered,
    else the first (see :func:`load_items`)."""
    if not candidates:
        return ""
    refs = [r for r in item["refs"] if r in index.senses]
    if log is not None and refs and len(candidates) > 1:
        cands = index.candidates(refs)
        for example in candidates:
            if log.get("map", map_key(dict(item, example=example), cands)) is not None:
                return example
    return candidates[0]


def _chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def map_todo(items: list[dict], index: CaldIndex, log: DecisionLog
             ) -> list[tuple[dict, list[dict], str]]:
    """``(item, shown candidates, key)`` for every sense with candidates and
    no usable answer for the question as it stands. An earlier "unanswered"
    record is asked again -- it is a fact about the API, not the sense."""
    todo = []
    for item in items:
        refs = [r for r in item["refs"] if r in index.senses]
        if not refs:
            continue
        cands = index.candidates(refs)
        for i, cand in enumerate(cands, 1):
            cand["cid"] = f"c{i}"
        key = map_key(item, cands)
        record = log.get("map", key)
        if record is None or not record.get("answered"):
            todo.append((item, cands, key))
    return todo


class _Progress:
    def __init__(self, step: str, total: int, progress, every: int = 500) -> None:
        self.step, self.total, self.progress, self.every = step, total, progress, every
        self.done = 0

    def add(self, n: int) -> None:
        before = self.done
        self.done += n
        if self.progress is not None and (self.done // self.every > before // self.every
                                          or self.done >= self.total):
            self.progress(self.step, self.done, self.total)


async def run_map(items: list[dict], index: CaldIndex, log: DecisionLog, gemini, *,
                  budget: Budget | None = None, concurrency: int = 4, progress=None) -> Counter:
    """``map`` for every sense that needs it (:func:`map_todo`); each answer
    is logged the moment its request returns, and the budget is checked
    before every request -- a stop loses nothing it paid for. What stayed
    unanswered is logged as such (and asked again by the next run)."""
    from app.services import lexicon_enrich as le

    todo = map_todo(items, index, log)
    by_sense = {item["sense_id"]: (item, cands, key) for item, cands, key in todo}
    counts: Counter = Counter(to_ask=len(todo))
    ticker = _Progress("map", len(todo), progress)

    def payload(item: dict, cands: list[dict], answer: dict | None) -> dict:
        out = {"sense_id": item["sense_id"], "lemma": item["lemma"], "pos": item["pos"],
               "model": le.MODEL_MAIN, "candidates": len(cands), "answered": answer is not None}
        if answer is not None:
            out.update(answer)
            if answer["ref"]:
                _, sense = index.senses[answer["ref"]]
                out["cald_definition"] = sense["def"]
                out["cald_level"] = sense["level"]
        return out

    def logged(answers: dict[str, dict]) -> None:
        for sense_id, answer in answers.items():
            item, cands, key = by_sense[sense_id]
            log.put("map", key, payload(item, cands, answer))
        counts["answered"] += len(answers)
        ticker.add(len(answers))

    answers = await ask_map(gemini, le.MODEL_MAIN, [(i, c) for i, c, _ in todo],
                            concurrency=concurrency, on_answers=logged,
                            before_request=budget.check if budget is not None else None)
    for sense_id, (item, cands, key) in by_sense.items():
        if sense_id not in answers:
            log.put("map", key, payload(item, cands, None))
            counts["unanswered"] += 1
    return counts


def v2_entries(items: list[dict], index: CaldIndex, log: DecisionLog,
               judge: str = JUDGE_MODEL) -> list[dict]:
    """The v2 translation question of every sense whose definition becomes
    CALD's (:func:`verified_mapping`: run :func:`run_verify` first, or a
    far-levelled sense is not translated yet)."""
    out = []
    for item in items:
        mapping = verified_mapping(log, item, index, judge)
        if mapping["decision"] == "mapped":
            out.append(v2_entry(item, mapping["ref"], index))
    return out


async def run_translate(entries: list[dict], log: DecisionLog, gemini, *,
                        budget: Budget | None = None, concurrency: int = 4, progress=None
                        ) -> Counter:
    """Both production translators' v2 answer for every entry the log does
    not hold an answer for; logged as each request returns (see
    :func:`run_map`)."""
    from app.services import lexicon_enrich as le

    counts: Counter = Counter()
    for model in (le.MODEL_MAIN, le.MODEL_ALT):
        todo = [e for e in entries
                if not (log.get("translate2", translate2_key(e, model)) or {}).get("answered")]
        by_id = {e["id"]: e for e in todo}
        counts[f"{model}:to_ask"] = len(todo)
        ticker = _Progress(f"translate {model}", len(todo), progress)

        def record(entry: dict, answer: dict | None, _model: str = model) -> None:
            log.put("translate2", translate2_key(entry, _model), {
                "sense_id": entry["id"], "lemma": entry["lemma"], "ref": entry["ref"],
                "model": _model, "answered": answer is not None, **(answer or {})})

        def logged(answers: dict[str, dict], _model: str = model, _ticker=ticker,
                   _by_id=by_id) -> None:
            for entry_id, answer in answers.items():
                record(_by_id[entry_id], answer, _model)
            counts[f"{_model}:answered"] += len(answers)
            _ticker.add(len(answers))

        got = await ask_keyed(gemini, model, TRANSLATE_V2_PROMPT, todo, render_v2_item,
                              parse_v2_item, step="cald-translate-v2", reply_key="items",
                              concurrency=concurrency, on_answers=logged,
                              before_request=budget.check if budget is not None else None)
        for entry in todo:
            if entry["id"] not in got:
                record(entry, None)
                counts[f"{model}:unanswered"] += 1
    return counts


def new_pair(entry: dict, log: DecisionLog) -> tuple[str, str, dict, dict]:
    """``(new_uz, new_alt, main record, alt record)``: the production
    convention (`lexicon_enrich.step_translate`) -- the stronger model's
    answer leads, the other translator's is the alternative; one translator
    alone gives the pair with no alternative."""
    from app.services import lexicon_enrich as le

    main = log.get("translate2", translate2_key(entry, le.MODEL_MAIN)) or {}
    alt = log.get("translate2", translate2_key(entry, le.MODEL_ALT)) or {}
    main_uz = main.get("uz", "") if main.get("answered") else ""
    alt_uz = alt.get("uz", "") if alt.get("answered") else ""
    new_uz, new_alt = (main_uz, alt_uz) if main_uz else (alt_uz, "")
    return new_uz, new_alt, main, alt


def _pair_key(uz: str, alt: str) -> tuple[str, str]:
    first, second = _uz_norm(uz), _uz_norm(alt or "")
    return first, (second if second and second != first else "")


def same_pair(entry: dict) -> bool:
    """Old and new say the same thing letter for letter (case, spacing and
    punctuation aside): nothing for a judge to choose between."""
    return _pair_key(entry["old_uz"], entry["old_alt"]) == _pair_key(entry["new_uz"],
                                                                       entry["new_alt"])


def compare_entries(entries: list[dict], log: DecisionLog) -> list[dict]:
    """The entries the comparison judge must see: a new pair AND an old one,
    and the two not the same text."""
    out = []
    for entry in entries:
        new_uz, new_alt, _, _ = new_pair(entry, log)
        full = dict(entry, new_uz=new_uz, new_alt=new_alt)
        if new_uz and entry["old_uz"] and not same_pair(full):
            out.append(full)
    return out


#: Pairs judged together: both runs (positions swapped) of one batch are
#: asked, combined and logged before the batch is done.
COMPARE_BATCH = 25


async def run_compare(pairs: list[dict], log: DecisionLog, gemini, judge: str = JUDGE_MODEL, *,
                      budget: Budget | None = None, concurrency: int = 4, progress=None
                      ) -> Counter:
    """The comparison judge, twice per pair with old and new swapped between
    A and B, for every pair the log holds no verdict for (a record whose
    runs both failed is asked again). Batch by batch: a batch's two runs are
    combined (:func:`combine_comparison`) and logged as soon as both are in."""
    todo = [p for p in pairs if not (log.get("compare", compare_key(p, judge)) or {}).get("runs")]
    counts: Counter = Counter(to_ask=len(todo))
    ticker = _Progress(f"compare {judge}", len(todo), progress)
    semaphore = asyncio.Semaphore(max(1, concurrency // 2))
    check = budget.check if budget is not None else None

    async def judge_batch(batch: list[dict]) -> None:
        async with semaphore:
            runs = await asyncio.gather(*(ask_keyed(
                gemini, judge, COMPARE_PROMPT, [dict(e, swap=swap) for e in batch],
                render_compare_item, parse_compare_item, step=f"cald-compare:{judge}",
                reply_key="verdicts", batch=COMPARE_BATCH, per_item_tokens=120, concurrency=1,
                before_request=check) for swap in (False, True)))
        for entry in batch:
            per_run = [r.get(entry["id"]) for r in runs]
            combined = combine_comparison(per_run)
            log.put("compare", compare_key(entry, judge), {
                "sense_id": entry["id"], "lemma": entry["lemma"], "ref": entry["ref"],
                "judge_model": judge, "per_run": per_run, **combined})
            counts[f"runs:{combined['runs']}"] += 1
        ticker.add(len(batch))

    await asyncio.gather(*(judge_batch(b) for b in _chunks(todo, COMPARE_BATCH)))
    return counts


# --- Re-verification of far-levelled mappings (agreed 2026-10-07, after the full run) ---

#: A mapped sense whose CALD level is this many bands or more from ours, either
#: way, is asked again: is it the same meaning? (The owner's look at the
#: biggest jumps found a NARROWER CALD sense chosen -- a figurative or
#: business use for a plain one -- often enough to check the whole tail.)
VERIFY_BANDS = 2
#: CALD's level is TAKEN only within this many bands of ours (or where we
#: have none); further away ours stays and the sense is flagged
#: ``cald_cefr_far`` -- English Vocabulary Profile levels describe what
#: learners PRODUCE in exam writing, so concrete everyday nouns come out C1/C2.
CEFR_CAP_BANDS = 1
#: The review reason the cap adds (`app.models.lexicon.REVIEW_REASONS`).
CEFR_FAR_REASON = "cald_cefr_far"
VERIFY_VERSION = 1
VERIFY_VERDICTS = ("same", "different", "unsure")

VERIFY_PROMPT = """You are checking matches between two English dictionaries
for a learner's dictionary. Each item gives an English word, its part of
speech and two definitions of it: ours (with our Uzbek translation and, where
we have one, a sentence from a reading passage in which learners met the word
in OUR sense) and Cambridge's (with Cambridge's guideword in capitals where it
has one). They are shown as Sense 1 and Sense 2, in either order.

For each item decide whether the two are the SAME MEANING of the word -- a
learner who knows one would read the word correctly where the other is meant:
- "same": the same meaning; different wording, or one being a little broader
  or more general, is fine;
- "different": not the same meaning -- another meaning of the word, or one
  sense is a NARROWER use that changes the meaning (a specific situation, a
  business, technical or figurative use of a plain meaning), or the grammar
  differs in a way that changes it (causing something vs. it happening to
  something);
- "unsure": you cannot tell.
reason: at most 20 words, in English.

{items}

Reply with JSON only:
{{"verdicts": {{"k1": {{"verdict": "same", "reason": "..."}}, ...}}}}
Answer every item."""


def band_gap(ours: str | None, cald: str | None) -> int | None:
    """CALD's level minus ours, in bands; None when either is missing."""
    if ours not in CEFR_LEVELS or cald not in CEFR_LEVELS:
        return None
    return CEFR_LEVELS.index(cald) - CEFR_LEVELS.index(ours)


def needs_verify(ours: str | None, cald: str | None) -> bool:
    gap = band_gap(ours, cald)
    return gap is not None and abs(gap) >= VERIFY_BANDS


def verify_entry(item: dict, ref: str, index: CaldIndex) -> dict:
    block, sense = index.senses[ref]
    return {"id": item["sense_id"], "lemma": item["lemma"], "pos": item["pos"], "ref": ref,
            "ours": item["definition_en"], "uz": item["meaning_uz"],
            "alt": item["meaning_uz_alt"], "example": item.get("example") or "",
            "cald": {"def": sense["def"], "gw": block["gw"]}}


def verify_key(entry: dict, judge: str) -> str:
    return (f"{entry['id']}|{entry['ref']}|{judge}|"
            f"{_hash(VERIFY_VERSION, entry['ours'], entry['uz'], entry['alt'], entry['example'], entry['cald'])}")


def render_verify_item(key: str, entry: dict) -> str:
    """Run 1 shows ours as Sense 1; run 2 (``swap``) shows Cambridge's first
    -- the same position swap the comparison judge uses."""
    uz = entry["uz"] + (f" / {entry['alt']}" if entry["alt"] and entry["alt"] != entry["uz"] else "")
    ours = [f"(ours) \"{entry['ours']}\""]
    if uz:
        ours.append(f"      Our Uzbek: \"{uz}\"")
    if entry["example"]:
        ours.append(f"      Passage: \"{entry['example']}\"")
    cald = [f"(Cambridge) {_sense_line(entry['cald'])}"]
    first, second = (cald, ours) if entry.get("swap") else (ours, cald)
    lines = [f"{key}: {entry['lemma']} ({entry['pos'] or '?'})",
             f"  Sense 1 {first[0]}", *first[1:], f"  Sense 2 {second[0]}", *second[1:]]
    return "\n".join(lines)


def parse_verify_item(value: object, entry: dict) -> dict | None:
    """One run's verdict, or None when it names none of
    :data:`VERIFY_VERDICTS` -- no verdict, never a guessed one."""
    if isinstance(value, str):
        value = {"verdict": value}
    if not isinstance(value, dict):
        return None
    verdict = str(value.get("verdict") or "").strip().lower()
    if verdict not in VERIFY_VERDICTS:
        return None
    return {"verdict": verdict, "reason": " ".join(str(value.get("reason") or "").split())[:300]}


def combine_verify(runs: list[dict | None]) -> dict:
    """Two runs -> keep the mapping or not (agreed): ``different`` in EITHER
    run drops it; ``unsure`` in both drops it; otherwise (both answered) it
    stays. Fewer than two answers and no ``different``: ``keep`` None -- not
    decided, asked again by the next run, and not applied meanwhile."""
    answered = [r for r in runs if r]
    verdicts = [r["verdict"] for r in answered]
    if "different" in verdicts:
        return {"keep": False, "why": "different", "runs": len(answered), "verdicts": verdicts}
    if len(answered) < 2:
        return {"keep": None, "why": "incomplete", "runs": len(answered), "verdicts": verdicts}
    if verdicts == ["unsure", "unsure"]:
        return {"keep": False, "why": "unsure", "runs": 2, "verdicts": verdicts}
    return {"keep": True, "why": "same", "runs": 2, "verdicts": verdicts}


def verify_todo(items: list[dict], index: CaldIndex, log: DecisionLog,
                judge: str = JUDGE_MODEL) -> list[dict]:
    """The verify question of every mapped sense whose CALD level is
    :data:`VERIFY_BANDS`+ from ours and that the log holds no decision for."""
    todo = []
    for item in items:
        mapping = effective_mapping(log, item, index, keyed=True)
        if mapping["decision"] != "mapped":
            continue
        if not needs_verify(item["cefr"], index.senses[mapping["ref"]][1]["level"]):
            continue
        entry = verify_entry(item, mapping["ref"], index)
        record = log.get("verify", verify_key(entry, judge))
        if record is None or record.get("keep") is None:
            todo.append(entry)
    return todo


VERIFY_BATCH = 25


async def run_verify(items: list[dict], index: CaldIndex, log: DecisionLog, gemini,
                     judge: str = JUDGE_MODEL, *, budget: Budget | None = None,
                     concurrency: int = 4, progress=None) -> Counter:
    """:data:`VERIFY_PROMPT` twice per far-levelled mapping (positions
    swapped), combined (:func:`combine_verify`) and logged batch by batch."""
    todo = verify_todo(items, index, log, judge)
    counts: Counter = Counter(to_ask=len(todo))
    ticker = _Progress(f"verify {judge}", len(todo), progress)
    semaphore = asyncio.Semaphore(max(1, concurrency // 2))
    check = budget.check if budget is not None else None

    async def judge_batch(batch: list[dict]) -> None:
        async with semaphore:
            runs = await asyncio.gather(*(ask_keyed(
                gemini, judge, VERIFY_PROMPT, [dict(e, swap=swap) for e in batch],
                render_verify_item, parse_verify_item, step=f"cald-verify:{judge}",
                reply_key="verdicts", batch=VERIFY_BATCH, per_item_tokens=120, concurrency=1,
                before_request=check) for swap in (False, True)))
        for entry in batch:
            per_run = [r.get(entry["id"]) for r in runs]
            combined = combine_verify(per_run)
            log.put("verify", verify_key(entry, judge), {
                "sense_id": entry["id"], "lemma": entry["lemma"], "ref": entry["ref"],
                "judge_model": judge, "per_run": per_run, **combined})
            counts[combined["why"]] += 1
        ticker.add(len(batch))

    await asyncio.gather(*(judge_batch(b) for b in _chunks(todo, VERIFY_BATCH)))
    return counts


def verified_mapping(log: DecisionLog, item: dict, index: CaldIndex,
                     judge: str = JUDGE_MODEL) -> dict:
    """:func:`effective_mapping` (keyed) plus the re-verification: a mapped
    sense whose CALD level is :data:`VERIFY_BANDS`+ from ours stays mapped
    only if :func:`combine_verify` kept it; dropped it is ``none`` (the reason
    says why), undecided it is ``unverified`` (not applied, asked again).
    ``verify`` holds the record."""
    mapping = effective_mapping(log, item, index, keyed=True)
    mapping["verify"] = None
    if mapping["decision"] != "mapped":
        return mapping
    if not needs_verify(item["cefr"], index.senses[mapping["ref"]][1]["level"]):
        return mapping
    record = log.get("verify", verify_key(verify_entry(item, mapping["ref"], index), judge))
    mapping["verify"] = record
    if record is None or record.get("keep") is None:
        mapping["decision"] = "unverified"
    elif not record["keep"]:
        mapping.update(decision="none",
                       reason=f"[re-verify: {record['why']}] {mapping['reason']}")
    return mapping


# --- The plan: what apply would write, as a pure function of the log -------------------


@dataclass
class Plan:
    """One sense's outcome. ``decision``: ``mapped`` (the definition becomes
    CALD's), ``none``/``unanswered`` (the map or the re-verification said so
    / no usable answer yet), ``unverified`` (a far-levelled mapping the
    re-verification has not decided), ``unmatched`` (CALD has no candidate
    for the lexeme). For a
    mapped sense ``uz`` is ``new`` (the v2 pair is written) or ``old`` (the
    old pair stays), ``uz_why`` saying why: ``no-old`` (there was no Uzbek
    to keep), ``judge-new`` / ``judge-old`` (the comparison under the loose
    keep rule), ``identical`` (the translators gave back the old text),
    ``no-verdict`` (both judge runs failed: the old pair stays),
    ``untranslated`` (neither translator answered: the old pair stays)."""

    item: dict
    decision: str
    ref: str | None = None
    pointer_ref: str | None = None
    confidence: str = ""
    definition: str = ""
    #: The level APPLIED from CALD: CALD's own within
    #: :data:`CEFR_CAP_BANDS` of ours (or where we have none), else None --
    #: ours stays and ``cefr_far`` flags it.
    level: str | None = None
    #: CALD's level for the sense, applied or not (`LexemeSense.cald_cefr`).
    cald_level: str | None = None
    cefr_far: bool = False
    verify: dict | None = None
    reason: str = ""
    xref_text: bool = False
    uz: str = "old"
    uz_why: str = ""
    new_uz: str = ""
    new_alt: str = ""
    main_flag: str = ""
    alt_flag: str = ""
    compare: dict | None = None

    @property
    def sense_id(self) -> str:
        return self.item["sense_id"]

    @property
    def judge_verdict(self) -> str | None:
        """What `lexicon_enrich.review_reasons` is told about this sense's
        Uzbek: a pair the comparison passed is ``same`` (judge reasons go);
        an old pair every run called wrong, beside a new one also wrong, is
        ``different`` (the review queue is where it belongs); anything else
        keeps the reasons the sense had (None)."""
        if self.uz == "new" and self.uz_why == "judge-new":
            return "same"
        if self.compare and "both_wrong" in (self.compare.get("flags") or []):
            return "different"
        return None


def plan_items(items: list[dict], index: CaldIndex, log: DecisionLog,
               judge: str = JUDGE_MODEL) -> list[Plan]:
    """Every item's :class:`Plan` under the agreed rules -- a pure function of
    the items, the index and the log (no model, no database)."""
    plans = []
    for item in items:
        if not [r for r in item["refs"] if r in index.senses]:
            plans.append(Plan(item=item, decision="unmatched"))
            continue
        mapping = verified_mapping(log, item, index, judge)
        plan = Plan(item=item, decision=mapping["decision"], confidence=mapping["confidence"],
                    pointer_ref=mapping["pointer_ref"], verify=mapping["verify"],
                    reason=mapping["reason"])
        plans.append(plan)
        if mapping["decision"] != "mapped":
            continue
        block, sense = index.senses[mapping["ref"]]
        plan.ref, plan.definition, plan.cald_level = (
            mapping["ref"], strip_label_lost_prefix(sense["def"]), sense["level"])
        # The cap: CALD's level only near ours (or where we have none).
        gap = band_gap(item["cefr"], sense["level"])
        if sense["level"] and (gap is None or abs(gap) <= CEFR_CAP_BANDS):
            plan.level = sense["level"]
        elif sense["level"]:
            plan.cefr_far = True
        plan.xref_text = bool(sense.get("xref"))
        entry = v2_entry(item, plan.ref, index)
        new_uz, new_alt, main, alt = new_pair(entry, log)
        plan.new_uz, plan.new_alt = new_uz, new_alt
        plan.main_flag, plan.alt_flag = main.get("flag", ""), alt.get("flag", "")
        entry.update(new_uz=new_uz, new_alt=new_alt)
        if not new_uz:
            plan.uz, plan.uz_why = "old", "untranslated"
        elif not item["meaning_uz"]:
            plan.uz, plan.uz_why = "new", "no-old"
        elif same_pair(entry):
            plan.uz, plan.uz_why = "old", "identical"
        else:
            record = log.get("compare", compare_key(entry, judge))
            plan.compare = record
            if not record or not record.get("runs"):
                plan.uz, plan.uz_why = "old", "no-verdict"
            elif record["loose_keep"] == "old":
                plan.uz, plan.uz_why = "old", "judge-old"
            else:
                plan.uz, plan.uz_why = "new", "judge-new"
    return plans


def _shift(before: str | None, after: str | None) -> str:
    if before not in CEFR_LEVELS or after not in CEFR_LEVELS:
        return f"{before or '-'}->{after or '-'}" if before != after else "same"
    delta = CEFR_LEVELS.index(after) - CEFR_LEVELS.index(before)
    return f"{delta:+d}" if delta else "0"


def summarise(plans: list[Plan], material_levels: dict[str, list[str]]) -> dict:
    """The numbers the dry run prints (and a test can assert on).
    ``material_levels``: sense id -> the CURRENT `cefr_level` of every
    material row pointing at it, ``__pre__`` + sense id -> their
    ``cefr_level_pre_cald`` (what a re-levelled row was)."""
    out: dict = {"decision": Counter(), "confidence": Counter(), "cefr_shift": Counter(),
                 "cefr_source": Counter(), "uz": Counter(), "main_flag": Counter(),
                 "material_rows": Counter(), "material_shift": Counter(), "pointers": Counter(),
                 "verify": Counter(), "review_flags": Counter(), "collisions": {},
                 "other": Counter()}
    by_ref: dict[str, list[Plan]] = defaultdict(list)
    for plan in plans:
        out["decision"][plan.decision] += 1
        if plan.item["approved"] and (plan.decision == "mapped" or plan.item.get("applied")):
            # A human decided on it: apply and restore skip it (`is_locked`),
            # so it would change nothing -- left out of the numbers below.
            out["other"]["locked by review (apply and restore skip it)"] += 1
            continue
        if plan.verify is not None or plan.decision == "unverified":
            why = (plan.verify or {}).get("why") or "not asked yet"
            kept = {"same": "kept (same)", "different": "dropped (different in a run)",
                    "unsure": "dropped (unsure in both)"}.get(why, f"undecided ({why})")
            out["verify"][kept] += 1
        if plan.decision != "mapped":
            if plan.pointer_ref and "not resolved" in plan.reason:
                out["pointers"]["unresolved"] += 1
            elif plan.pointer_ref:
                out["pointers"][f"followed, then {plan.decision}"] += 1
            continue
        item = plan.item
        out["confidence"][plan.confidence] += 1
        by_ref[plan.ref].append(plan)
        if plan.pointer_ref:
            out["pointers"]["followed"] += 1
        after = plan.level or item["cefr"]
        out["cefr_source"]["cald" if plan.level else
                           f"ours (CALD {CEFR_CAP_BANDS + 1}+ bands away)" if plan.cefr_far else
                           "ours (no CALD level)"] += 1
        if plan.cefr_far:
            out["review_flags"][CEFR_FAR_REASON] += 1
        out["cefr_shift"][_shift(item["cefr"], after)] += 1
        out["uz"][f"{plan.uz}:{plan.uz_why}"] += 1
        out["main_flag"][plan.main_flag or "-"] += 1
        if plan.compare and "both_wrong" in (plan.compare.get("flags") or []):
            out["other"]["both_wrong (old kept, sent to review)"] += 1
            out["review_flags"]["judge_different (both_wrong)"] += 1
        if item["applied"]:
            out["other"]["already applied"] += 1
            if item["current"]["definition_en"] != plan.definition:
                out["other"]["already applied, would change"] += 1
        if plan.xref_text:
            out["other"]["definition had cross-reference markup (cleaned)"] += 1
        if plan.level:
            rows = material_levels.get(plan.sense_id, [])
            pre = material_levels.get("__pre__" + plan.sense_id, [])
            for i, level in enumerate(rows):
                before = pre[i] if i < len(pre) and pre[i] is not None else level
                out["material_rows"]["re-levelled" if before != plan.level else "already that level"] += 1
                out["material_shift"][_shift(before or None, plan.level)] += 1
        else:
            kept = len(material_levels.get(plan.sense_id, []))
            back = sum(1 for pre in material_levels.get("__pre__" + plan.sense_id, [])
                       if pre is not None)
            if kept:
                out["material_rows"]["kept (sense keeps ours)"] += kept
            if back:
                out["material_rows"]["put back (re-levelled by an earlier apply)"] += back
    for plan in plans:
        if plan.item["approved"]:
            continue
        if plan.decision == "none" and plan.item.get("applied"):
            out["other"]["applied, now none: apply restores it"] += 1
        elif plan.decision not in ("mapped", "none") and plan.item.get("applied"):
            out["other"]["applied, now undecided (left as it is)"] += 1
    for ref, group in by_ref.items():
        if len(group) > 1:
            lemmas = {p.item["lemma"] for p in group}
            kind = "same lemma" if len(lemmas) == 1 else "different lemmas"
            out["collisions"].setdefault(kind, []).append(
                {"ref": ref, "senses": [p.sense_id for p in group], "lemmas": sorted(lemmas)})
    out["collision_counts"] = {k: {"cald_senses": len(v), "our_senses": sum(len(g["senses"]) for g in v)}
                               for k, v in out["collisions"].items()}
    return out


def print_summary(summary: dict) -> None:
    def show(name: str, counter) -> None:
        print(f"  {name}: {dict(sorted(counter.items(), key=lambda kv: (-kv[1], kv[0])))}")

    print("plan:")
    show("senses by decision", summary["decision"])
    show("mapped by confidence", summary["confidence"])
    show("re-verification (CALD level 2+ bands from ours)", summary["verify"])
    show("pointers", summary["pointers"])
    show("CEFR source", summary["cefr_source"])
    show("CEFR shift (ours -> applied, in bands)", summary["cefr_shift"])
    show("material rows", summary["material_rows"])
    show("material row CEFR shift", summary["material_shift"])
    show("Uzbek (written:why)", summary["uz"])
    show("v2 main translator flag", summary["main_flag"])
    show("review flags added", summary["review_flags"])
    print(f"  collisions (several of our senses on one CALD sense): {summary['collision_counts']}")
    show("other", summary["other"])


async def load_material_levels(sense_ids: list[str], conn=None) -> dict[str, list]:
    """For :func:`summarise`: sense id -> its material rows' `cefr_level`
    (and ``__pre__`` + id -> their pre-CALD level, where the column exists)."""
    if conn is None:
        async with readonly_connection() as own:
            return await load_material_levels(sense_ids, conn=own)
    from sqlalchemy import bindparam, text
    from sqlalchemy.dialects.postgresql import ARRAY, UUID

    has_pre = bool((await conn.execute(text(
        "select count(*) from information_schema.columns where table_schema = current_schema() "
        "and table_name = 'material_vocabulary' and column_name = 'cefr_level_pre_cald'"))
    ).scalar_one())
    pre = ", cefr_level_pre_cald" if has_pre else ", null"
    stmt = text(f"select sense_id, cefr_level{pre} from material_vocabulary "
                "where sense_id = any(:ids) order by sense_id, id").bindparams(
        bindparam("ids", type_=ARRAY(UUID(as_uuid=True))))
    out: dict[str, list] = defaultdict(list)
    for sense_id, level, before in (await conn.execute(
            stmt, {"ids": [uuid.UUID(s) for s in sense_ids]})).all():
        out[str(sense_id)].append(level)
        out["__pre__" + str(sense_id)].append(before)
    return dict(out)


# --- apply / restore (the only writes) -------------------------------------------------

#: `LexemeSense.licence` of a CALD-defined sense -- see
#: `app.models.lexicon.DEFINITION_SOURCES`.
CALD_LICENCE = "cald"


def is_locked(row) -> bool:
    """A human decision on the sense: Studio's approve/fix stamped
    ``approved_at`` (or it holds a reviewer's rewrite, ``definition_source =
    'human'``). Apply and restore never write such a sense -- see
    :func:`apply_plans`."""
    return row.approved_at is not None or row.definition_source == "human"


def _uuid_chunks(ids, size: int = 1000) -> list[list[uuid.UUID]]:
    values = [uuid.UUID(str(i)) for i in ids]
    return [values[i:i + size] for i in range(0, len(values), size)]


async def _recompute_lexeme_cefr(session, lexeme_ids) -> None:
    """A sense's level changed: the lexeme's senses are re-ordered easiest
    first, `Lexeme.cefr` is the new rank 1's and the rank-1 `ngsl_conflict`
    flag follows (`lexicon.rerank_lexemes`, the one keeper of that order)."""
    from app.services.lexicon import rerank_lexemes

    await session.flush()
    await rerank_lexemes(session, list(lexeme_ids))


async def apply_plans(session, plans: list[Plan], *, now: datetime | None = None) -> Counter:
    """Write every ``mapped`` plan (the caller commits). Per sense: the
    before-values are copied into ``*_pre_cald`` the FIRST time only (with
    ``cald_applied_at``); then the CALD definition (``definition_source =
    'cald'``, ``cald_ref``, licence ``cald``, ``cald_cefr``), CALD's level
    where the cap allows (``cefr_source``; otherwise the pre-CALD level, and
    ``cald_cefr_far`` among the review reasons when CALD's was too far), the
    Uzbek the plan
    chose (otherwise the pre-CALD pair), review reasons recomputed from the
    pre-CALD ones, and the sense's material rows re-levelled to the APPLIED
    level (their old level kept once in ``cefr_level_pre_cald``; a sense
    keeping ours leaves them alone). An applied sense the plan now says
    ``none`` for is restored. Then `Lexeme.cefr` for the touched lexemes. Everything is computed from the pre-CALD values, so a
    second apply of the same plans writes the same thing: idempotent.

    A sense not applied yet whose row no longer says what its item was built
    from (the worker re-enriched it meanwhile) is skipped (``drifted``) --
    the plan answered a question about text the row no longer has.

    A sense a human has decided on is LOCKED (:func:`is_locked`: Studio's
    approve/fix set ``approved_at``, whether before the first apply or
    after it) and skipped whatever the plan says (``locked by review``): the
    reviewer's definition, Uzbek and level are not ours to overwrite, and a
    re-apply has no drift check to notice. It is read from the ROW, not the
    item -- the approval may have come after the plan was made. Its
    ``needs_review`` is never touched either: an approved sense is not
    re-opened. For the senses apply does write, ``needs_review`` follows
    the recomputed reasons, and the first apply keeps the old value in
    ``needs_review_pre_cald`` for :func:`restore_senses`."""
    from sqlmodel import select

    from app.models.lexicon import LexemeSense
    from app.models.vocabulary import MaterialVocabulary
    from app.services import lexicon_enrich as le

    now = now or datetime.now(timezone.utc)
    counts: Counter = Counter()
    mapped = [p for p in plans if p.decision == "mapped"]
    # An applied sense the plan now says ``none`` for (the re-verification
    # dropped it) goes back to what it was: apply converges on the plan.
    undo = [p.sense_id for p in plans if p.decision == "none" and p.item.get("applied")]
    if not mapped and not undo:
        return counts
    rows: dict[uuid.UUID, LexemeSense] = {}
    material: dict[uuid.UUID, list[MaterialVocabulary]] = defaultdict(list)
    for chunk in _uuid_chunks([p.sense_id for p in mapped]):
        for row in (await session.exec(select(LexemeSense).where(LexemeSense.id.in_(chunk)))).all():
            rows[row.id] = row
        for mv in (await session.exec(select(MaterialVocabulary).where(
                MaterialVocabulary.sense_id.in_(chunk)))).all():
            material[mv.sense_id].append(mv)
    touched_lexemes: set[uuid.UUID] = set()
    for plan in mapped:
        item = plan.item
        sense_id = uuid.UUID(plan.sense_id)
        row = rows.get(sense_id)
        if row is None:
            counts["gone"] += 1
            continue
        if is_locked(row):
            counts["locked by review"] += 1
            continue
        if row.cald_applied_at is None:
            if (row.definition_en != item["definition_en"] or row.meaning_uz != item["meaning_uz"]
                    or row.meaning_uz_alt != item["meaning_uz_alt"] or row.cefr != item["cefr"]):
                counts["drifted"] += 1
                continue
            row.definition_en_pre_cald = row.definition_en
            row.cefr_pre_cald = row.cefr
            row.meaning_uz_pre_cald = row.meaning_uz
            row.meaning_uz_alt_pre_cald = row.meaning_uz_alt
            row.licence_pre_cald = row.licence
            row.review_reasons_pre_cald = list(row.review_reasons)
            row.needs_review_pre_cald = row.needs_review
            row.cald_applied_at = now
            counts["newly applied"] += 1
        else:
            counts["re-applied"] += 1
        row.definition_en = plan.definition[:le.DEF_MAX]
        row.definition_source = "cald"
        row.cald_ref = plan.ref
        row.cald_cefr = plan.cald_level
        row.licence = CALD_LICENCE
        if plan.level:
            row.cefr, row.cefr_source = plan.level, "cald"
        else:
            row.cefr, row.cefr_source = row.cefr_pre_cald, "ours"
        if plan.uz == "new":
            row.meaning_uz = plan.new_uz[:le.UZ_MAX]
            row.meaning_uz_alt = plan.new_alt[:le.UZ_MAX]
        else:
            row.meaning_uz = row.meaning_uz_pre_cald or ""
            row.meaning_uz_alt = row.meaning_uz_alt_pre_cald or ""
        for mv in material.get(sense_id, []):
            if plan.level:
                if mv.cefr_level_pre_cald is None:
                    mv.cefr_level_pre_cald = mv.cefr_level
                if mv.cefr_level != plan.level:
                    counts["material rows re-levelled"] += 1
                mv.cefr_level = plan.level
            elif mv.cefr_level_pre_cald is not None:
                mv.cefr_level, mv.cefr_level_pre_cald = mv.cefr_level_pre_cald, None
                counts["material rows put back"] += 1
            session.add(mv)
        row.review_reasons = le.review_reasons(
            cefr=row.cefr, frequency_band=item["frequency_band"],
            material_levels=[mv.cefr_level for mv in material.get(sense_id, [])],
            carried=list(row.review_reasons_pre_cald or []), judge=plan.judge_verdict,
            rank=row.sense_rank)
        if plan.cefr_far and CEFR_FAR_REASON not in row.review_reasons:
            # Ours kept against a far CALD level: both are on the row
            # (`cefr`, `cald_cefr`) for the Studio review queue.
            row.review_reasons = [*row.review_reasons, CEFR_FAR_REASON]
        row.needs_review = bool(row.review_reasons)
        session.add(row)
        touched_lexemes.add(row.lexeme_id)
    await session.flush()
    if undo:
        restored, lexemes = await restore_senses(session, undo)
        counts["restored (now none)"] = restored["senses restored"]
        if restored["locked by review"]:
            counts["locked by review"] += restored["locked by review"]
        touched_lexemes |= lexemes
    await _recompute_lexeme_cefr(session, touched_lexemes)
    counts["lexemes"] = len(touched_lexemes)
    return counts


async def restore_senses(session, sense_ids: list | None = None
                         ) -> tuple[Counter, set[uuid.UUID]]:
    """Put back what the first CALD apply replaced -- every applied sense
    (``sense_ids`` None) or the listed ones -- and the material rows it
    re-levelled; then `Lexeme.cefr`. ``definition_source`` and the licence
    go back to what they were (an OEWN gloss is ``oewn``/``cc-by-4.0``,
    anything else ``model``/``proprietary`` -- the two always agreed before
    CALD). The ``*_pre_cald`` columns are cleared: a later apply copies
    afresh. A sense a human has decided on (:func:`is_locked`) is NOT
    restored -- counted as ``locked by review`` -- nor are its material rows:
    the reviewer's text and level stand. ``needs_review`` goes back to what
    it was before the first apply (``needs_review_pre_cald``). Returns the
    counts and the touched lexeme ids. The caller commits."""
    from sqlmodel import select

    from app.models.lexicon import LexemeSense
    from app.models.vocabulary import MaterialVocabulary
    from app.services import lexicon_enrich as le

    counts: Counter = Counter()
    query = select(LexemeSense).where(LexemeSense.cald_applied_at.is_not(None))
    rows = []
    if sense_ids is None:
        rows = list((await session.exec(query)).all())
    else:
        for chunk in _uuid_chunks(sense_ids):
            rows += list((await session.exec(query.where(LexemeSense.id.in_(chunk)))).all())
    touched: set[uuid.UUID] = set()
    locked: set[uuid.UUID] = set()
    restored_ids: list[uuid.UUID] = []
    for row in rows:
        if is_locked(row):
            locked.add(row.id)
            counts["locked by review"] += 1
            continue
        row.definition_en = row.definition_en_pre_cald or ""
        row.cefr = row.cefr_pre_cald
        row.meaning_uz = row.meaning_uz_pre_cald or ""
        row.meaning_uz_alt = row.meaning_uz_alt_pre_cald or ""
        row.licence = row.licence_pre_cald or (
            le.OEWN_LICENCE if row.source_id == "oewn" else le.MODEL_LICENCE)
        row.definition_source = "oewn" if row.licence == le.OEWN_LICENCE else "model"
        row.cefr_source = "ours"
        row.cald_ref = row.cald_cefr = None
        row.review_reasons = list(row.review_reasons_pre_cald or [])
        row.needs_review = (row.needs_review_pre_cald if row.needs_review_pre_cald is not None
                            else bool(row.review_reasons))
        row.needs_review_pre_cald = None
        row.definition_en_pre_cald = row.cefr_pre_cald = None
        row.meaning_uz_pre_cald = row.meaning_uz_alt_pre_cald = None
        row.licence_pre_cald = None
        row.review_reasons_pre_cald = None
        row.cald_applied_at = None
        session.add(row)
        touched.add(row.lexeme_id)
        restored_ids.append(row.id)
        counts["senses restored"] += 1
    mv_query = select(MaterialVocabulary).where(MaterialVocabulary.cefr_level_pre_cald.is_not(None))
    mvs = []
    if sense_ids is None:
        mvs = list((await session.exec(mv_query)).all())
    else:
        for chunk in _uuid_chunks(sense_ids):
            mvs += list((await session.exec(
                mv_query.where(MaterialVocabulary.sense_id.in_(chunk)))).all())
    for mv in mvs:
        if mv.sense_id in locked:
            continue
        mv.cefr_level, mv.cefr_level_pre_cald = mv.cefr_level_pre_cald, None
        session.add(mv)
        counts["material rows restored"] += 1
    await session.flush()
    # A restored sense has no `cald_ref` any more, so the block its recording
    # came from is no longer its own: drop the recordings (they may be a
    # heteronym's other pronunciation). `scripts/cald.py recordings` re-plans
    # them from the lemma. The files stay: they are shared and content-addressed.
    if restored_ids:
        from sqlalchemy import delete

        from app.models.word_recording import WordRecording

        for chunk in _uuid_chunks(restored_ids):
            await session.execute(delete(WordRecording).where(
                WordRecording.lexeme_sense_id.in_(chunk)))
        counts["recordings dropped"] = len(restored_ids)
    await _recompute_lexeme_cefr(session, touched)
    counts["lexemes"] = len(touched)
    return counts, touched


async def recompute_letter_hints(session, lexeme_ids) -> None:
    """`needs_letter_hint` reads `definition_en`, which apply/restore just
    changed: the incremental recompute for a few lexemes, the full backfill
    when most of the catalogue moved (it also catches the OTHER side of a
    newly identical pair). Commits (`lexicon_hints` does)."""
    from app.services import lexicon_hints

    ids = [uuid.UUID(str(i)) for i in lexeme_ids]
    if len(ids) > 200:
        await lexicon_hints.recompute_all(session)
    elif ids:
        await lexicon_hints.recompute_for_lexemes(session, ids)


# --- The worker's hook: lexemes enriched after the full run ----------------------------
#
# What keeps a new sense from being the one left on its old definition, and
# what keeps that from costing more than it is worth. Three rules, each from
# a review finding:
#
# * A hard failure stops the PASS at once (:class:`HookHalt`): HTTP 402/401/
#   403, or a 429 that outlasted the client's own retries
#   (`lexicon_enrich.Gemini.hard_status`). Every request is preceded by
#   :meth:`HookBudget.check`, so no queued request and no per-item re-ask is
#   made after it; nothing is applied (a half-translated sense would be
#   applied with its OLD Uzbek and, being applied, never revisited). The hook
#   then holds off for a cooldown that doubles from
#   `settings.cald_hook_cooldown_s` to `cald_hook_cooldown_max_s`, logged
#   once on entering it and once on leaving it -- not once per request.
# * A pass has a wall-clock timeout (`cald_hook_timeout_s`), a spend cap
#   (`cald_hook_pass_budget_usd`) and so does a day (`cald_hook_daily_budget_usd`,
#   from `usage.jsonl`'s ``worker`` records).
# * Memory: the index and the decision log are loaded for ONE call and
#   dropped right after it (:func:`_release_memory`). Peak while a call runs
#   is ~0.45 GB of resident memory for the index (its raw JSON and the
#   `pron` table are not kept: `CaldIndex` holds only what the matcher
#   reads) plus the log; after it the allocator keeps a fraction (~0.15 GB
#   measured) until it reuses it. Loading takes under a second, so a burst
#   of passes pays that each time; the sweep skips the load altogether when
#   nothing changed since its last empty scan.

_worker_said: set[str] = set()


def _say_once(key: str, level: int, message: str, *args) -> None:
    if key not in _worker_said:
        _worker_said.add(key)
        logger.log(level, message, *args)


class HookHalt(RuntimeError):
    """The pass must stop NOW: ``kind`` is ``http`` (``status`` the code that
    says asking again is pointless) -- see the section comment above."""

    def __init__(self, kind: str, status: int | None = None) -> None:
        super().__init__(f"{kind} {status}" if status else kind)
        self.kind, self.status = kind, status


@dataclass
class HookBudget(Budget):
    """:class:`Budget` whose check also refuses once the model client has
    reported a hard failure. Passed to every ``run_*`` step as ``budget`` (and
    its ``check`` to :func:`follow_pointers`), so the guard runs before every
    request, the per-item re-asks included."""

    gemini: object = None

    def check_hard(self) -> None:
        status = getattr(self.gemini, "hard_status", None)
        if status is not None:
            raise HookHalt("http", status)

    def check(self) -> None:
        self.check_hard()
        super().check()


@dataclass
class HookState:
    failures: int = 0
    #: ``_clock()`` value until which the hook holds off
    until: float = 0.0
    last_sweep: float | None = None
    last_rec_sweep: float | None = None
    #: the sweep's last empty scan: nothing to do while this still holds
    sweep_clean: tuple | None = None
    sweep_tried: Counter = field(default_factory=Counter)
    daily_stop_day: str = ""


_hook = HookState()
#: Patched by tests; everything time-based in the hook reads it.
_clock = time.monotonic


def reset_hook_state() -> None:
    """Forget cooldown, sweep bookkeeping and the once-only log lines
    (tests; a process restart does the same)."""
    from app.services import word_recordings

    word_recordings.reset_sweep_state()
    global _hook
    _hook = HookState()
    _worker_said.clear()


def hook_cooldown_left() -> float:
    """Seconds the hook still holds off after a failure (0: free to run)."""
    return max(0.0, _hook.until - _clock())


def _hold_off(why: str) -> float:
    """Start (or lengthen) the cooldown; ONE warning per state change."""
    _hook.failures += 1
    delay = min(settings.cald_hook_cooldown_s * 2 ** (_hook.failures - 1),
                settings.cald_hook_cooldown_max_s)
    _hook.until = _clock() + delay
    logger.warning("CALD hook paused for %.0f s (%s; failure %d in a row)", delay, why,
                   _hook.failures)
    return delay


def _recovered() -> None:
    if _hook.failures:
        logger.info("CALD hook resumed after %d failure(s) in a row", _hook.failures)
        _hook.failures = 0
        _hook.until = 0.0


def worker_spend_today(out_dir: Path = PRIVATE_DIR) -> float:
    """What the worker's passes cost since 00:00 UTC (``worker*`` records of
    :data:`USAGE_FILE`; the file is chronological, so reading stops at the
    first older day)."""
    path = out_dir / USAGE_FILE
    if not path.exists():
        return 0.0
    today = datetime.now(timezone.utc).date().isoformat()
    total = 0.0
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        record = json.loads(line)
        if str(record.get("at", ""))[:10] < today:
            break
        if str(record.get("cmd", "")).startswith("worker"):
            total += float(record.get("total_cost_usd") or 0.0)
    return total


def worker_index(out_dir: Path = PRIVATE_DIR) -> CaldIndex | None:
    """The CALD index for the worker, or None -- and ONE log line -- when
    this machine has none (a server without the private source: new senses
    keep the definition enrichment gave them). Loaded afresh each call and
    NOT cached: the caller drops it when its call ends (see the section
    comment above)."""
    if not (out_dir / INDEX_FILE).exists():
        _say_once(f"missing:{out_dir}", logging.INFO,
                  "CALD index not present (%s); new senses keep their enrichment definitions",
                  out_dir / INDEX_FILE)
        return None
    try:
        data = load_index_data(out_dir)
    except SystemExit as exc:  # load_index_data's own "rebuild it" message
        _say_once(f"version:{out_dir}", logging.WARNING, "CALD index unusable: %s", exc)
        return None
    index = CaldIndex(data)
    del data
    return index


async def _load_worker_data(out_dir: Path) -> tuple[CaldIndex | None, DecisionLog | None]:
    # Seconds of JSON parsing: off the event loop, so the worker's other
    # loops (transcription, renders) are not stalled behind it.
    index = await asyncio.to_thread(worker_index, out_dir)
    if index is None:
        return None, None
    return index, await asyncio.to_thread(DecisionLog, out_dir / DECISIONS_FILE)


def _release_memory() -> None:
    """Called once the index and log are unreferenced: collect now rather
    than whenever the next threshold trips."""
    gc.collect()


async def _map_and_apply(index: CaldIndex, log: DecisionLog, items: list[dict], *,
                         session_factory, gemini, out_dir: Path, judge: str,
                         budget_usd: float | None, cmd: str) -> Counter:
    """The full run's map -> pointers -> re-verify -> translate v2 -> compare
    -> apply for ``items``, under :class:`HookBudget`. A sense whose Uzbek no
    translator answered is NOT applied (``deferred (untranslated)``): applied,
    it would keep the old Uzbek for good, because the hook never revisits an
    applied sense -- left alone, the sweep asks again."""
    from app.core.database import async_session_factory
    from app.services import lexicon_enrich as le

    own = gemini is None
    gemini = gemini or le.Gemini(le.UsageLog())
    usage = getattr(gemini, "usage", None) or le.UsageLog()
    budget = HookBudget(limit=budget_usd or 0.0, before=0.0, usage=usage, gemini=gemini)
    counts: Counter = Counter()
    try:
        await run_map(items, index, log, gemini, budget=budget)
        await follow_pointers({"items": items}, log, index, gemini, le.MODEL_MAIN, keyed=True,
                              before_request=budget.check)
        await run_verify(items, index, log, gemini, judge, budget=budget)
        entries = v2_entries(items, index, log, judge)
        await run_translate(entries, log, gemini, budget=budget)
        await run_compare(compare_entries(entries, log), log, gemini, judge, budget=budget)
        budget.check_hard()  # a last request that failed: apply nothing
    finally:
        counts["requests"] = sum(u.requests for u in usage.by_model.values())
        if own:
            await gemini.aclose()
            record_usage(out_dir, cmd, gemini.usage)
    plans = plan_items(items, index, log, judge)
    deferred = {id(p) for p in plans if p.decision == "mapped" and p.uz_why == "untranslated"}
    counts["deferred (untranslated)"] = len(deferred)
    session_factory = session_factory or async_session_factory
    async with session_factory() as session:
        applied = await apply_plans(session, [p for p in plans if id(p) not in deferred])
        await session.commit()
    counts.update(applied)
    if applied.get("newly applied") or applied.get("re-applied"):
        async with session_factory() as session:
            await recompute_letter_hints(session, {uuid.UUID(i["lexeme_id"]) for i in items})
    counts.update({f"plan:{k}": v for k, v in Counter(p.decision for p in plans).items()})
    # The senses just finished may now have a CALD block to be spoken by:
    # attach their recordings while the index is in hand. An enhancement of
    # the pass, never a reason for it to fail (`attach_for_lexemes` does not
    # raise; without `settings.cald_source_dir` it logs once and does nothing).
    from app.services import word_recordings

    counts.update(await word_recordings.attach_for_lexemes(
        index, {uuid.UUID(i["lexeme_id"]) for i in items}, session_factory=session_factory))
    return counts


async def map_new_lexemes(lexeme_ids: list, *, session_factory=None, gemini=None,
                          out_dir: Path = PRIVATE_DIR, judge: str = JUDGE_MODEL,
                          budget_usd: float | None = None, cmd: str = "worker") -> Counter:
    """The full run's pipeline for the not-yet-applied, not-approved senses
    of ``lexeme_ids`` only: what keeps a lexeme `link_row` creates after the
    full run (and `lexicon_enrich` then finishes) from being the one sense
    left on its old definition. Every answer goes to the same decision log,
    so nothing already asked is asked again. A machine without the private
    CALD index does nothing (:func:`worker_index`). ``gemini`` None: a client
    of its own, whose usage is appended to :data:`USAGE_FILE` as ``cmd``.
    Raises :class:`HookHalt` / :class:`BudgetExceeded` when a pass must
    stop; :func:`run_hook` is the caller that turns those into a cooldown."""
    if not lexeme_ids:
        return Counter()
    index, log = await _load_worker_data(out_dir)
    if index is None:
        return Counter()
    try:
        items = [i for i in await load_items(index, lexeme_ids=lexeme_ids, log=log)
                 if not i["applied"] and not i["approved"] and i["refs"]]
        if not items:
            return Counter()
        return await _map_and_apply(index, log, items, session_factory=session_factory,
                                    gemini=gemini, out_dir=out_dir, judge=judge,
                                    budget_usd=budget_usd, cmd=cmd)
    finally:
        index = log = None
        _release_memory()


def _unfinished(item: dict, index: CaldIndex, log: DecisionLog, judge: str) -> bool:
    """Whether the pipeline still owes this unapplied sense something: no
    usable map answer (never asked -- a sense `word_lists_build` wrote after
    the lexeme's enrichment -- or recorded as unanswered), or a mapping that
    has not reached the row yet (translation or verification pending)."""
    if map_todo([item], index, log):
        return True
    return verified_mapping(log, item, index, judge)["decision"] in ("mapped", "unverified")


async def _sweep_candidates(session_factory) -> list[uuid.UUID]:
    """Lexemes that could still owe a sense a CALD definition: finished by
    enrichment (a provisional definition is not worth mapping), with an
    unapplied, unapproved sense of ours."""
    from sqlmodel import select

    from app.core.database import async_session_factory
    from app.models.lexicon import Lexeme, LexemeSense

    async with (session_factory or async_session_factory)() as session:
        return list((await session.exec(
            select(LexemeSense.lexeme_id).join(Lexeme, Lexeme.id == LexemeSense.lexeme_id)
            .where(LexemeSense.cald_applied_at.is_(None), LexemeSense.approved_at.is_(None),
                   LexemeSense.definition_source.in_(("oewn", "model")),
                   Lexeme.is_proper_noun.is_(False), Lexeme.is_function_word.is_(False),
                   Lexeme.enriched_at.is_not(None))
            .distinct().order_by(LexemeSense.lexeme_id))).all())


async def sweep_unmapped(*, session_factory=None, gemini=None, out_dir: Path = PRIVATE_DIR,
                         judge: str = JUDGE_MODEL, limit: int = 25, max_tries: int = 3,
                         budget_usd: float | None = None) -> Counter:
    """The retry sweep: the pipeline for up to ``limit`` lexemes that CALD
    matches and whose senses the hook never finished -- questions recorded as
    unanswered (a failed pass, a 402 that has since been paid), and senses
    nothing ever asked about (written by `word_lists_build.write_new_sense`
    into a lexeme whose ``enriched_at`` was already set, so the enrichment
    hook never saw them). Never-tried lexemes first; one tried ``max_tries``
    times in this process is left until a restart (a sense the model keeps
    refusing must not be asked about every half hour). An empty scan is
    remembered (:attr:`HookState.sweep_clean`): the next sweep loads nothing
    until the lexemes, or the decision log, change."""
    candidates = await _sweep_candidates(session_factory)
    if not candidates:
        return Counter()
    log_path = out_dir / DECISIONS_FILE
    stamp = (hashlib.sha1(",".join(map(str, candidates)).encode()).hexdigest(),
             log_path.stat().st_mtime_ns if log_path.exists() else None)
    if _hook.sweep_clean == stamp:
        return Counter()
    index, log = await _load_worker_data(out_dir)
    if index is None:
        return Counter()
    try:
        owed: list[uuid.UUID] = []
        for start in range(0, len(candidates), 400):
            chunk = candidates[start:start + 400]
            found = {uuid.UUID(i["lexeme_id"]) for i in await load_items(
                index, lexeme_ids=chunk, log=log)
                if not i["applied"] and not i["approved"] and i["refs"]
                and _unfinished(i, index, log, judge)}
            owed += [lexeme_id for lexeme_id in chunk if lexeme_id in found]
            await asyncio.sleep(0)  # the matching is CPU: let other loops run
        owed = [i for i in owed if _hook.sweep_tried[i] < max_tries]
        if not owed:
            _hook.sweep_clean = stamp
            return Counter()
        owed.sort(key=lambda i: (_hook.sweep_tried[i], str(i)))
        chosen = owed[:limit]
        for lexeme_id in chosen:
            _hook.sweep_tried[lexeme_id] += 1
        _hook.sweep_clean = None
        items = [i for i in await load_items(index, lexeme_ids=chosen, log=log)
                 if not i["applied"] and not i["approved"] and i["refs"]]
        counts = Counter(swept=len(chosen), owed=len(owed))
        if items:
            counts.update(await _map_and_apply(
                index, log, items, session_factory=session_factory, gemini=gemini,
                out_dir=out_dir, judge=judge, budget_usd=budget_usd, cmd="worker-sweep"))
        return counts
    finally:
        index = log = None
        _release_memory()


async def _guarded(job: str, run, *, out_dir: Path) -> Counter:
    """Policy around one hook job (``run(budget_usd)``): the switch, the
    cooldown, the caps, the wall-clock timeout, and what a failure does to
    the cooldown. Never raises."""
    if not settings.cald_map_new_lexemes:
        return Counter()
    if hook_cooldown_left() > 0:
        return Counter()
    pass_cap, day_cap = settings.cald_hook_pass_budget_usd, settings.cald_hook_daily_budget_usd
    limit = pass_cap if pass_cap > 0 else None
    daily_left = None
    if day_cap > 0:
        daily_left = day_cap - await asyncio.to_thread(worker_spend_today, out_dir)
        if daily_left <= 0:
            today = datetime.now(timezone.utc).date().isoformat()
            if _hook.daily_stop_day != today:
                _hook.daily_stop_day = today
                logger.warning("CALD hook idle: today's $%.2f cap is spent", day_cap)
            return Counter()
        limit = daily_left if limit is None else min(limit, daily_left)
    timeout = settings.cald_hook_timeout_s if settings.cald_hook_timeout_s > 0 else None
    try:
        counts = await asyncio.wait_for(run(limit), timeout=timeout)
    except HookHalt as halt:
        _hold_off(f"{job}: HTTP {halt.status}")
        return Counter()
    except BudgetExceeded as exc:
        which = "daily" if daily_left is not None and limit == daily_left else "per-pass"
        logger.warning("CALD hook %s stopped at its %s cap: %s", job, which, exc)
        return Counter()
    except (asyncio.TimeoutError, TimeoutError):
        _hold_off(f"{job}: no result in {timeout:.0f} s")
        return Counter()
    except Exception as exc:  # noqa: BLE001 - logged; held off like any failure
        logger.exception("CALD hook %s failed", job)
        _hold_off(f"{job}: {type(exc).__name__}")
        return Counter()
    if counts.get("requests"):
        _recovered()
    return counts


async def run_hook(lexeme_ids: list, *, out_dir: Path = PRIVATE_DIR, **kwargs) -> Counter:
    """What the worker calls after an enrichment pass: :func:`map_new_lexemes`
    under the policy of :func:`_guarded` (switch, cooldown, caps, timeout)."""
    return await _guarded("hook", lambda limit: map_new_lexemes(
        lexeme_ids, out_dir=out_dir, budget_usd=limit, **kwargs), out_dir=out_dir)


async def run_sweep(*, out_dir: Path = PRIVATE_DIR, **kwargs) -> Counter:
    """What the worker calls every loop: :func:`sweep_unmapped`, at most once
    per `settings.cald_sweep_interval_s` (0 turns it off), under the same
    policy as :func:`run_hook`; and, on its own interval and WITHOUT the
    model's cooldown or switch (it asks nobody anything), the recordings
    sweep (:func:`app.services.word_recordings.sweep`)."""
    counts = await _run_recordings_sweep(out_dir)
    counts.update(await _run_definitions_sweep(out_dir=out_dir, **kwargs))
    return counts


async def _run_recordings_sweep(out_dir: Path) -> Counter:
    interval = settings.cald_sweep_interval_s
    if interval <= 0:
        return Counter()
    now = _clock()
    if _hook.last_rec_sweep is not None and now - _hook.last_rec_sweep < interval:
        return Counter()
    _hook.last_rec_sweep = now
    from app.services import word_recordings

    return await word_recordings.sweep(out_dir)


async def _run_definitions_sweep(*, out_dir: Path = PRIVATE_DIR, **kwargs) -> Counter:
    interval = settings.cald_sweep_interval_s
    if interval <= 0 or not settings.cald_map_new_lexemes or hook_cooldown_left() > 0:
        return Counter()
    now = _clock()
    if _hook.last_sweep is not None and now - _hook.last_sweep < interval:
        return Counter()
    _hook.last_sweep = now
    return await _guarded("sweep", lambda limit: sweep_unmapped(
        out_dir=out_dir, limit=settings.cald_sweep_batch,
        max_tries=settings.cald_sweep_max_tries, budget_usd=limit, **kwargs), out_dir=out_dir)
