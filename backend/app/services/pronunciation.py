"""Heteronyms: words the ear tells apart and the spelling does not.

`record` the noun is /ˈrekɔːd/ and `record` the verb is /rɪˈkɔːd/; `lead` the
metal is /lɛd/. A text-to-speech voice reading the bare word guesses, and a
wrong guess raises no error -- it teaches the learner a wrong pronunciation
with a confident British voice (brief §2). So for every word that has more
than one pronunciation, the pronunciation is a DECISION made once per sense,
stored on the sense, and handed to the voice as phonemes instead of text:
``[record](/ɹɪkˈɔːd/)``.

## One decision per accent

The two accents are two phoneme alphabets and two tables (decision 25): the
British choice is ``LexemeSense.pronunciation`` and the American one
``LexemeSense.pronunciation_us``, each a string in ITS accent's alphabet
(``ɹˈɛkɔːd`` is British; ``ɹˈɛkəɹd`` American, with ``O`` /oʊ/ where British
has ``Q`` /əʊ/, ``æ``, ``ɾ``, ``ɹ`` after a vowel ...). A phoneme string
handed to the wrong voice is mispronounced silently, so every function here
takes the ``accent`` and the stored column is chosen by the caller
(:func:`app.services.word_audio.decided_pronunciation`).

## Where the candidates come from

* ``app/data/tts/misaki_gb_pos_entries.json`` -- the 788 part-of-speech-keyed
  entries of misaki's British gold lexicon (``gb_gold.json``, the voice's own
  front end, Apache-2.0), vendored so the API image needs no misaki. One
  entry is ``{"DEFAULT": ..., "VERB": ..., ...}``.
* ``app/data/tts/misaki_us_pos_entries.json`` -- the same for the American
  gold lexicon (``us_gold.json``, 790 entries).
* ``app/data/tts/heteronym_extras.json`` -- a small hand-written table. It
  adds words that differ WITHIN one part of speech, which a POS-keyed table
  cannot hold (``lead`` the metal, ``row`` the quarrel, ``does`` the deer ...),
  and it annotates the misaki variants that already exist with a plain-English
  note, because the model that picks between candidates (``scripts/
  decide_heteronyms.py``) is choosing between strings like ``klˈQs`` and
  ``klˈQz`` and a gloss is what lets it choose by meaning.

Both use **misaki's phoneme alphabet, not IPA**: the diphthongs are single
capital letters (``A`` = /eɪ/, ``I`` = /aɪ/, ``W`` = /aʊ/, ``Y`` = /ɔɪ/, and
``Q`` = /əʊ/ in British but ``O`` = /oʊ/ in American), ``ɹ`` is the r, ``ː`` a
long vowel (British only), ``ˈ`` primary stress. :func:`to_ipa` renders them
for people and for the model.

An extras item is ``{"ps": <British>, "us": <American>, "note": ...}``. A
missing ``us`` means the same string serves both (valid only if it is in both
alphabets); ``"us": null`` leaves the item out of the American candidates; no
``ps`` makes it American-only (``slough``'s /sluː/). The notes are shared: a
gloss is about the meaning, which does not change with the accent.

## What counts as a heteronym

A lemma with at least TWO candidates that differ once stress marks are
ignored. misaki's table also holds entries whose variants differ only in
stress (``be``: ``biː`` / ``bˈiː`` -- a function word read stressed or not);
those are not heteronyms and a clip of them is as good as any other. The
decision is per LEMMA and exact: a phrase is never a heteronym, even if one
of its words is.

## No decision yet

A heteronym sense the decisions log has not reached still gets a
pronunciation, because the alternative is no audio for a common word:
misaki's entry for the sense's own part of speech, else its ``DEFAULT``
(:func:`fallback_pronunciation`). That is misaki's own behaviour, i.e. what
the voice would have done on its own, and it is LOGGED (once per word and part
of speech per process) so a reader of the worker's log can see which senses
are running on the fallback.
"""

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.services.accents import DEFAULT_ACCENT, Accent

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "tts"
MISAKI_PATH = DATA_DIR / "misaki_gb_pos_entries.json"
MISAKI_US_PATH = DATA_DIR / "misaki_us_pos_entries.json"
MISAKI_PATHS: dict[str, Path] = {"british": MISAKI_PATH, "american": MISAKI_US_PATH}
EXTRAS_PATH = DATA_DIR / "heteronym_extras.json"

#: Our ``Lexeme.pos`` -> misaki's (Penn-derived) tag for the same part of
#: speech. Anything else (``prep``, ``conj``, ``phr``, "") has no tag, so only
#: ``DEFAULT`` ever applies to it.
MISAKI_TAG_BY_POS: dict[str, str] = {
    "n": "NOUN",
    "v": "VERB",
    "adj": "ADJ",
    "adv": "ADV",
}

_STRESS = "ˈˌ"

#: misaki's alphabets (both), for display only.
_IPA = {
    "A": "eɪ",
    "I": "aɪ",
    "Q": "əʊ",
    "W": "aʊ",
    "Y": "ɔɪ",
    "O": "oʊ",
    "ᵊ": "ə",
    "ʤ": "dʒ",
    "ʧ": "tʃ",
    "ᵻ": "ɪ",
}


@dataclass
class Candidate:
    """One way to say a lemma: misaki phonemes, where it came from, and (where
    the extras table annotated it) what it means."""

    ps: str
    #: misaki tags that carry it (``DEFAULT``, ``VERB`` ...); empty for an
    #: extras-only candidate.
    tags: list[str] = field(default_factory=list)
    note: str = ""


def to_ipa(ps: str) -> str:
    """misaki phonemes as (approximate) IPA, for people and for the prompt."""
    return "".join(_IPA.get(ch, ch) for ch in ps)


def strip_stress(ps: str) -> str:
    return "".join(ch for ch in ps if ch not in _STRESS)


@lru_cache(maxsize=None)
def _misaki(accent: Accent = DEFAULT_ACCENT) -> dict[str, dict[str, str | None]]:
    raw = json.loads(MISAKI_PATHS[accent].read_text(encoding="utf-8"))
    # Lowercase keys only: the upper-case ones are abbreviations (`AA`, `ABS`)
    # whose variants differ in stress at most.
    return {k: v for k, v in raw.items() if k == k.lower()}


@lru_cache(maxsize=None)
def _extras(accent: Accent = DEFAULT_ACCENT) -> dict[str, list[dict[str, str]]]:
    """The extras table as ``{lemma: [{"ps", "note"}]}`` in ``accent``'s
    alphabet (the module docstring has the item format)."""
    raw = json.loads(EXTRAS_PATH.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, str]]] = {}
    for lemma, items in raw.items():
        chosen = []
        for item in items:
            if accent == "american":
                ps = item["us"] if "us" in item else item.get("ps")
            else:
                ps = item.get("ps")
            if ps:
                chosen.append({"ps": ps, "note": item.get("note", "")})
        if chosen:
            out[lemma] = chosen
    return out


@lru_cache(maxsize=None)
def candidates(lemma: str, accent: Accent = DEFAULT_ACCENT) -> tuple[Candidate, ...]:
    """Every distinct pronunciation of ``lemma`` (lower-cased), misaki's
    ``DEFAULT`` first, then its other tags in alphabetical order, then extras
    that misaki does not have. Two variants differing only in stress are one
    candidate (the first seen wins). Empty for a lemma in neither table."""
    word = lemma.lower().strip()
    found: list[Candidate] = []
    by_bare: dict[str, Candidate] = {}

    def add(ps: str, tag: str | None, note: str = "") -> None:
        bare = strip_stress(ps)
        existing = by_bare.get(bare)
        if existing is None:
            existing = Candidate(ps=ps)
            by_bare[bare] = existing
            found.append(existing)
        if tag and tag not in existing.tags:
            existing.tags.append(tag)
        if note and not existing.note:
            existing.note = note

    entry = _misaki(accent).get(word)
    if entry is not None:
        for tag in sorted(entry, key=lambda t: (t != "DEFAULT", t)):
            if entry[tag]:
                add(entry[tag], tag)
    for extra in _extras(accent).get(word, []):
        add(extra["ps"], None, extra["note"])
    return tuple(found)


def is_heteronym(lemma: str, accent: Accent = DEFAULT_ACCENT) -> bool:
    """Whether ``lemma`` has two or more pronunciations in ``accent`` (see the
    module docstring for what counts). Exact on the lemma: ``"close down"`` is
    not."""
    return len(candidates(lemma, accent)) >= 2


@lru_cache(maxsize=None)
def heteronym_lemmas(accent: Accent = DEFAULT_ACCENT) -> frozenset[str]:
    """Every heteronym lemma we know in ``accent``, lower-cased."""
    words = set(_misaki(accent)) | set(_extras(accent))
    return frozenset(w for w in words if is_heteronym(w, accent))


_logged_fallbacks: set[tuple[str, str, str]] = set()


def fallback_pronunciation(
    lemma: str, pos: str, accent: Accent = DEFAULT_ACCENT
) -> str | None:
    """misaki's own answer for ``lemma`` as a ``pos``: its entry for that part
    of speech if it has one, else ``DEFAULT``, else the first candidate (an
    extras-only word). ``None`` for a lemma that is not a heteronym."""
    word = lemma.lower().strip()
    if not is_heteronym(word, accent):
        return None
    entry = _misaki(accent).get(word)
    if entry is not None:
        tag = MISAKI_TAG_BY_POS.get(pos)
        if tag and entry.get(tag):
            return entry[tag]
        if entry.get("DEFAULT"):
            return entry["DEFAULT"]
    return candidates(word, accent)[0].ps


def sense_pronunciation(
    lemma: str, pos: str, decided: str | None, accent: Accent = DEFAULT_ACCENT
) -> str | None:
    """The phonemes the voice must be given for one sense, or ``None`` when it
    should read plain text (the lemma is not a heteronym).

    ``decided`` is the sense's column FOR ``accent`` (``pronunciation`` or
    ``pronunciation_us``). A heteronym sense without one
    falls back to :func:`fallback_pronunciation` and says so in the log."""
    if not is_heteronym(lemma, accent):
        return None
    if decided:
        return decided
    key = (lemma.lower(), pos, accent)
    if key not in _logged_fallbacks:
        _logged_fallbacks.add(key)
        logger.warning(
            "heteronym %r (%s, %s) has no decided pronunciation; using misaki's own",
            lemma, pos or "no pos", accent,
        )
    return fallback_pronunciation(lemma, pos, accent)
