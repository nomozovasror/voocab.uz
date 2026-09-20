"""The seam behind which a word gets its meaning, and the Groq side of it.

Almost nothing comes through here. A passage's vocabulary is extracted once
at seed time, by `seed/read_vocabulary.py`, and 95% of what a reader taps is
already a row in ``material_vocabulary`` with its sense, its Uzbek and its
example sentence. This is for the other 5%: the word the frequency filter did
not think was hard, which this particular reader does.

Same shape as :mod:`app.services.asr` for the same reason. A provider is an
implementation of a Protocol, the callers never learn which one answered, and
swapping one for another is writing a class rather than editing the code that
uses it.

## Why the answer is still contextual

The paragraph goes with the word, and what comes back is one sense: the one
that is true here.

## There is no plain-dictionary fallback, and that is a decision

The obvious backstop is a free dictionary API -- instant, no model, no key.
The brief asks for one on the grounds that an incomplete answer beats an
empty one. It is deliberately not built, for three reasons that all point
the same way:

* **No Uzbek.** A one-line English gloss of a C1 word is regularly harder
  than the word, which is the whole reason this feature exists rather than
  a link to Cambridge Dictionary.
* **No context.** A dictionary answers with every sense a word has, and a
  reader at band 5 picking the wrong one is precisely the failure the
  design is built to avoid. ``bank`` has six entries and one of them is the
  side of the river the passage is describing.
* **It would almost never run.** 95% of taps are answered from rows already
  on disk; the remaining 5% reach this module, and the fallback would only
  fire during the minutes a provider is down. A path that rare is a path
  nobody exercises, and an unexercised path that shows the one thing the
  rest of the design calls worse than nothing is not a safety net.

What a reader gets instead is the plain truth: this word is not in the
passage's list. Say so, and the page is still working.

## What happens when it is down

The extracted rows are on disk and depend on nobody's API, so an outage
costs the occasional unusual word rather than the vocabulary help on every
passage in the catalogue. That property is the reason the expensive
extraction happens at seed time, and it is worth more than a fallback that
would be wrong.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger("app.services.dictionary")

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "qwen/qwen3.8-27b"

#: The same three the seed stage is allowed to answer, and for the same
#: reason: a word below B1 would not have been asked about, and no two
#: sources agree on what C2 means.
LEVELS = ("B1", "B2", "C1")
PARTS = ("n", "v", "adj", "adv", "prep", "conj", "phr")

#: How long a gloss may be. The panel shows it in a narrow column, and a
#: meaning that wraps to four lines is one nobody reads mid-paper.
MEANING = 120

#: Some models wrap a reply in a reasoning block or a code fence whatever the
#: prompt says. Neither is worth a second request.
THINK = re.compile(r"<think>.*?</think>", re.S)
FENCE = re.compile(r"^```(?:json)?|```$", re.M)

PROMPT = """A learner reading an IELTS passage has looked up one word. They
are an Uzbek speaker at IELTS band 5 to 6.

The word: {word}

The paragraph it stands in:

{context}

Give the meaning the word has IN THIS PARAGRAPH -- one sense, not a
dictionary entry. If the paragraph uses a common word in an unusual sense,
that unusual sense is the one to give.

Reply with JSON only:

{{"lemma": "dictionary form of the word",
  "pos": "one of {parts}",
  "meaning_en": "one short line, under {meaning} characters, in simpler
English than the word itself",
  "meaning_uz": "the same sense in natural Uzbek, latin script",
  "cefr": "one of {levels}"}}

If the word is a name, a number or not an English word at all, reply
{{"lemma": ""}} and nothing else.
"""


@dataclass(frozen=True)
class Gloss:
    """One word, in one passage's sense. The shape a row of
    ``material_vocabulary`` is built from, minus everything about WHERE --
    the offsets are the caller's to supply, because only the caller knows
    which occurrence was tapped."""

    lemma: str
    pos: str
    meaning_en: str
    meaning_uz: str
    cefr_level: str


class DictionaryProvider(Protocol):
    """One interface every source of a meaning implements.

    ``None`` rather than an exception for "no meaning": a word nobody can
    gloss is an ordinary outcome here (a name, a typo, a word in another
    language) and not a fault. Faults are raised, and the caller decides
    whether one is worth failing a request over -- it is not.
    """

    async def look_up(self, word: str, context: str) -> Gloss | None: ...


def parse(reply: str) -> Gloss | None:
    """A model's reply as a :class:`Gloss`, or nothing where it is unusable.

    Refused rather than repaired, the same rule the seed stage applies. A
    missing Uzbek translation is the gloss's reason for existing and a level
    outside the scale is a guess at what the model meant; either way, showing
    the reader "no meaning found" is more honest than showing them a half
    one they cannot tell is half.
    """
    text = FENCE.sub("", THINK.sub("", reply).strip()).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        said = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None

    def line(key: str, limit: int = MEANING) -> str:
        value = " ".join(str(said.get(key) or "").split())
        return value if len(value) <= limit else ""

    lemma = line("lemma", 80).lower()
    meaning_en, meaning_uz = line("meaning_en"), line("meaning_uz")
    level = str(said.get("cefr") or "").strip().upper()
    part = str(said.get("pos") or "").strip().lower().rstrip(".")
    if not (lemma and meaning_en and meaning_uz) or level not in LEVELS:
        return None
    return Gloss(
        lemma=lemma,
        pos=part if part in PARTS else "",
        meaning_en=meaning_en,
        meaning_uz=meaning_uz,
        cefr_level=level,
    )


class GroqDictionary:
    """The only active :class:`DictionaryProvider`: a chat model, asked about
    one word in one paragraph.

    Deliberately not retried. This runs inside a request a reader is waiting
    on, and the reader's alternative to waiting twice is reading the sentence
    again -- which is the skill the paper is testing anyway. A failure here
    costs one word.
    """

    def __init__(self, api_key: str | None = None, timeout: float | None = None) -> None:
        self._api_key = settings.groq_api_key if api_key is None else api_key
        self._timeout = 20.0 if timeout is None else timeout

    async def look_up(self, word: str, context: str) -> Gloss | None:
        if not self._api_key:
            return None
        prompt = PROMPT.format(
            word=word, context=context, parts=", ".join(PARTS),
            levels=", ".join(LEVELS), meaning=MEANING,
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                GROQ_CHAT_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": GROQ_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    # One sense, five short fields. A ceiling this low is
                    # also the cheapest guard against a model that decides
                    # to write an essay about the etymology.
                    "max_tokens": 400,
                    "temperature": 0.0,
                },
            )
        response.raise_for_status()
        body = response.json()
        return parse(body["choices"][0]["message"]["content"] or "")


def provider() -> DictionaryProvider:
    """The dictionary this deployment uses.

    A function rather than a module-level instance so a test can replace it
    and so a deployment with no Groq key still imports."""
    return GroqDictionary()
