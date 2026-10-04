"""Did the learner say the word? The matcher behind `speak` (decisions 16-19).

The browser's ``SpeechRecognition`` returns ENGLISH TEXT, not phonemes: an
Uzbek speaker who says ``think`` as /tink/ gets ``tink`` or ``sink`` back, and
one who says ``stop`` as /istop/ gets ``istop``. So the rule is applied to
SPELLING -- the substitutions a Uzbek mouth makes are written down as letters
and the target is allowed to be spelled that way (decision 17). A mispronounced
word the recogniser still guessed correctly (``think``) matches trivially; this
module is for the ones it wrote down the way they were said.

## What is accepted

A target (the lemma) matches an alternative when, after both are normalised
(:func:`normalise`: lowercase, punctuation dropped, hyphens read as spaces,
whitespace collapsed), the alternative equals the target **spelled in any of
these ways**, together:

* ``th`` -> ``t``, ``s``, ``d`` or ``z`` (any of the four, wherever the target
  has a ``th``: the spelling does not say whether it was the voiced or the
  voiceless one, and Uzbek has neither);
* ``w`` -> ``v``;
* ``a`` <-> ``e`` (a target ``a`` may be heard as ``e`` and a target ``e`` as
  ``a``);
* a vowel -- ANY vowel (decision 17) -- put in front of an INITIAL consonant
  cluster (``stop`` -> ``istop`` / ``estop`` / ``ostop``). Because a real
  recogniser returns WORDS, the same vowel split off as its own one-letter
  token is accepted too (``a stop``, ``i stop``, ``e stop``). A cluster is two
  or more consonant SOUNDS at the start of the word,
  ``th``/``sh``/``ch``/``ph``/``gh``/``wh`` counting as one (``this`` has no
  cluster; ``school`` has ``sch``). A vowel before a word with no cluster
  (``isit`` for ``sit``) is not a rule, and neither is any longer prefix.

A phrase is compared WHOLE -- ``give rise to`` is matched as one string, so a
recogniser that heard only ``rise`` is a miss, never a partial credit.

## What is not

No inflection tolerance (``thinks`` is not ``think``), no edit distance, no
phonetic similarity, no other letters: ``c`` -> ``k`` (``cat`` / ``ket``),
``ch`` -> ``k`` with a changed vowel (``school`` / ``iskool``), ``l`` -> ``r``
(``play`` / ``pray``), a vowel before a word with no initial cluster
(``isit``) are all misses.
Everything fuzzier than a written-down rule is a guess about what the
recogniser meant, and a guess that accepts ``pray`` for ``play`` teaches the
wrong word. A miss is cheap here -- three attempts, nothing written to the
schedule (decision 18) -- and a false accept is not.

Accepting is deliberately a little generous where the REAL English word the
recogniser returns is a different word: ``sink`` for ``think``, ``estate``
for ``state`` and ``across`` for ``cross`` are accepted, because they are exactly what a learner who said
the right word would be handed back. The rule cannot tell the two apart and
the recogniser cannot either.

## Why a pattern and not a list of variants

A target with several ``th``/``w``/``a``/``e`` has thousands of spellings
(``give rise to`` alone: dozens). The target is turned into ONE regular
expression with an alternation at each rule's letter instead, which is linear
in the target's length, cannot blow up, and is checked with a single
``fullmatch`` against each alternative. The rules above are the pattern's
only content.
"""

import re
from collections.abc import Iterable
from functools import lru_cache

_VOWELS = frozenset("aeiou")
#: Digraphs that are ONE consonant sound, so ``this`` and ``shop`` do not count
#: as having an initial cluster (nobody puts a vowel in front of ``sh``).
_DIGRAPHS = ("th", "sh", "ch", "ph", "gh", "wh")
#: The prefix vowel of decision 17 is ANY vowel, written either glued to the
#: word (``istop``) or as its own one-letter token (``i stop``) -- what a
#: recogniser that returns words does. Only ever before an initial CLUSTER.
_PREFIX = "(?:[aeiou] ?)?"
#: What a target ``th`` may be written as.
_TH_SPELLINGS = ("th", "t", "s", "d", "z")


def normalise(text: str) -> str:
    """Lowercase, drop punctuation, hyphens and underscores read as spaces,
    whitespace collapsed. Applied to the target and to every alternative, so
    both sides are compared in the same shape."""
    lowered = (text or "").casefold().replace("-", " ").replace("_", " ")
    kept = "".join(ch for ch in lowered if ch.isalnum() or ch.isspace())
    return " ".join(kept.split())


def _has_initial_cluster(word: str) -> bool:
    """Two or more consonant sounds before the first vowel. ``y`` counts as a
    vowel after the first letter (``try``, ``style``) and as a consonant first
    (``yes``)."""
    index = 0
    sounds = 0
    while index < len(word):
        if word[index : index + 2] in _DIGRAPHS:
            sounds += 1
            index += 2
            continue
        ch = word[index]
        if ch in _VOWELS or (ch == "y" and index > 0) or not ch.isalpha():
            break
        sounds += 1
        index += 1
    return sounds >= 2


@lru_cache(maxsize=1024)
def _pattern(target: str) -> re.Pattern[str] | None:
    """The target (already normalised) as the one expression every accepted
    spelling matches. ``None`` for an empty target, which matches nothing."""
    if not target:
        return None
    parts: list[str] = []
    if _has_initial_cluster(target):
        parts.append(_PREFIX)
    index = 0
    while index < len(target):
        if target[index : index + 2] == "th":
            parts.append("(?:" + "|".join(_TH_SPELLINGS) + ")")
            index += 2
            continue
        ch = target[index]
        if ch == "w":
            parts.append("[wv]")
        elif ch in "ae":
            parts.append("[ae]")
        else:
            parts.append(re.escape(ch))
        index += 1
    return re.compile("".join(parts))


def matches(spoken: str, target: str) -> bool:
    """Whether ``spoken`` (one recogniser alternative) is the ``target`` word
    or phrase, under the rules in the module docstring."""
    pattern = _pattern(normalise(target))
    if pattern is None:
        return False
    heard = normalise(spoken)
    return bool(heard) and pattern.fullmatch(heard) is not None


def match(alternatives: Iterable[str], target: str) -> str | None:
    """The FIRST of the recogniser's alternatives (in the order it ranked
    them) that matches, exactly as it was sent -- or ``None``. Returned as
    sent so the client can post it back as ``given`` and the server can
    re-run :func:`matches` on it."""
    for alternative in alternatives:
        if matches(alternative, target):
            return alternative
    return None
