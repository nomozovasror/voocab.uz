"""Heteronyms: words the ear tells apart and the spelling does not.

`record` the noun is /ˈrekɔːd/ and `record` the verb is /rɪˈkɔːd/; `lead` the
metal is /lɛd/. A text-to-speech voice reading the bare word guesses, and a
wrong guess raises no error -- it teaches the learner a wrong pronunciation
with a confident British voice (brief §2). So for every word that has more
than one pronunciation, the pronunciation is a DECISION made once per sense,
stored on the sense (``LexemeSense.pronunciation``), and handed to the voice
as phonemes instead of text: ``[record](/ɹɪkˈɔːd/)``.

## Where the candidates come from

* ``app/data/tts/misaki_gb_pos_entries.json`` -- the 788 part-of-speech-keyed
  entries of misaki's British gold lexicon (``gb_gold.json``, the voice's own
  front end, Apache-2.0), vendored so the API image needs no misaki. One
  entry is ``{"DEFAULT": ..., "VERB": ..., ...}``.
* ``app/data/tts/heteronym_extras.json`` -- a small hand-written table. It
  adds words that differ WITHIN one part of speech, which a POS-keyed table
  cannot hold (``lead`` the metal, ``row`` the quarrel, ``does`` the deer ...),
  and it annotates the misaki variants that already exist with a plain-English
  note, because the model that picks between candidates (``scripts/
  decide_heteronyms.py``) is choosing between strings like ``klˈQs`` and
  ``klˈQz`` and a gloss is what lets it choose by meaning.

Both use **misaki's phoneme alphabet, not IPA**: the diphthongs are single
capital letters (``A`` = /eɪ/, ``I`` = /aɪ/, ``Q`` = /əʊ/, ``W`` = /aʊ/,
``Y`` = /ɔɪ/), ``ɹ`` is the r, ``ː`` a long vowel, ``ˈ`` primary stress.
:func:`to_ipa` renders them for people and for the model.

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

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "tts"
MISAKI_PATH = DATA_DIR / "misaki_gb_pos_entries.json"
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

#: misaki's British alphabet, for display only.
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


@lru_cache(maxsize=1)
def _misaki() -> dict[str, dict[str, str | None]]:
    raw = json.loads(MISAKI_PATH.read_text(encoding="utf-8"))
    # Lowercase keys only: the upper-case ones are abbreviations (`AA`, `ABS`)
    # whose variants differ in stress at most.
    return {k: v for k, v in raw.items() if k == k.lower()}


@lru_cache(maxsize=1)
def _extras() -> dict[str, list[dict[str, str]]]:
    return json.loads(EXTRAS_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def candidates(lemma: str) -> tuple[Candidate, ...]:
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

    entry = _misaki().get(word)
    if entry is not None:
        for tag in sorted(entry, key=lambda t: (t != "DEFAULT", t)):
            if entry[tag]:
                add(entry[tag], tag)
    for extra in _extras().get(word, []):
        add(extra["ps"], None, extra.get("note", ""))
    return tuple(found)


def is_heteronym(lemma: str) -> bool:
    """Whether ``lemma`` has two or more pronunciations (see the module
    docstring for what counts). Exact on the lemma: ``"close down"`` is not."""
    return len(candidates(lemma)) >= 2


@lru_cache(maxsize=1)
def heteronym_lemmas() -> frozenset[str]:
    """Every heteronym lemma we know, lower-cased."""
    words = set(_misaki()) | set(_extras())
    return frozenset(w for w in words if is_heteronym(w))


_logged_fallbacks: set[tuple[str, str]] = set()


def fallback_pronunciation(lemma: str, pos: str) -> str | None:
    """misaki's own answer for ``lemma`` as a ``pos``: its entry for that part
    of speech if it has one, else ``DEFAULT``, else the first candidate (an
    extras-only word). ``None`` for a lemma that is not a heteronym."""
    word = lemma.lower().strip()
    if not is_heteronym(word):
        return None
    entry = _misaki().get(word)
    if entry is not None:
        tag = MISAKI_TAG_BY_POS.get(pos)
        if tag and entry.get(tag):
            return entry[tag]
        if entry.get("DEFAULT"):
            return entry["DEFAULT"]
    return candidates(word)[0].ps


def sense_pronunciation(lemma: str, pos: str, decided: str | None) -> str | None:
    """The phonemes the voice must be given for one sense, or ``None`` when it
    should read plain text (the lemma is not a heteronym).

    ``decided`` is ``LexemeSense.pronunciation``. A heteronym sense without one
    falls back to :func:`fallback_pronunciation` and says so in the log."""
    if not is_heteronym(lemma):
        return None
    if decided:
        return decided
    key = (lemma.lower(), pos)
    if key not in _logged_fallbacks:
        _logged_fallbacks.add(key)
        logger.warning(
            "heteronym %r (%s) has no decided pronunciation; using misaki's own",
            lemma, pos or "no pos",
        )
    return fallback_pronunciation(lemma, pos)
