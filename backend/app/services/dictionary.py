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

## Two providers, in a chain

The first rule of the lookup is that any word a learner selects is answered.
That cannot rest on one API, and this is not hypothetical: the seed run hit
Groq's spend limit at the 174th passage and every live lookup in the app
started returning nothing — ordinary words, to a reader with no way to know
why. One outage had quietly repealed the rule.

So :func:`providers` returns them in order and the first that answers wins.
Groq leads because it is what the extraction was measured on; Gemini stands
behind it on a separate account with a separate quota, which is the only
kind of backstop worth having — a second model on the same key fails at the
same moment.

## Why the answer is still contextual -- and why it is no longer only that

The paragraph goes with the word, and what comes back is the sense that is
true here. It now comes back beside the sense the word usually has, because
the contextual one alone taught the wrong thing: a passage about artificial
intelligence glossed ``learn`` as "a computer process of finding patterns in
data", and a learner who saves that has it wrong in every other sentence.

The same failure has a second half. The word tapped was ``learning``, inside
``machine learning`` -- so the honest answer was not a narrower meaning of
``learn`` but a meaning of something WIDER than the word. :class:`Gloss`
carries ``term`` for exactly that, and the caller stores the entry over the
term's span.

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

#: Google's OpenAI-compatible endpoint, so one client speaks to both.
GEMINI_CHAT_URL = (
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
)
GEMINI_MODEL = "gemini-3.1-flash-lite"

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

Give two meanings: what the word USUALLY means, and what it means IN THIS
PARAGRAPH. One sense each, not a dictionary entry. If the paragraph uses a
common word in an unusual sense, that unusual sense is the one to give as
the second.

If the word stands inside a fixed multi-word term -- "machine learning",
"climate change", "public sector" -- answer for the TERM: put the term as
it is written in the paragraph in "term", give the term's dictionary form
as the lemma, and give the term's meanings. The meaning of a term is not a
meaning of any word in it, and filing it under one of them teaches the
learner something wrong about that word everywhere else.

The lemma is the dictionary form of the word AS IT IS USED HERE. If the form
in the paragraph belongs to a different part of speech from the base word --
"learning" the noun beside "learn" the verb -- give the lemma of the form
that is actually here, never the base word carrying the other form's part of
speech.

Reply with JSON only:

{{"lemma": "dictionary form of the word, or of the term",
  "term": "the multi-word term exactly as written in the paragraph, or an
empty string when the word does not stand inside one",
  "pos": "one of {parts}, for the lemma you gave",
  "meaning_core_en": "what it usually means -- one short line, under
{meaning} characters, in simpler English than the word itself",
  "meaning_core_uz": "that usual sense in natural Uzbek, latin script",
  "meaning_en": "what it means in this paragraph, under {meaning}
characters -- the same as meaning_core_en where the paragraph uses it in the
ordinary way",
  "meaning_uz": "the same sense in natural Uzbek, latin script",
  "sense_differs": true only where this paragraph's sense is genuinely not
the usual one,
  "cefr": "one of {levels}"}}

If the word is a name, a number or not an English word at all, reply
{{"lemma": ""}} and nothing else.
"""


@dataclass(frozen=True)
class Gloss:
    """One word, in one passage's sense. The shape a row of
    ``material_vocabulary`` is built from, minus everything about WHERE --
    the offsets are the caller's to supply, because only the caller knows
    which occurrence was tapped.

    ``term`` is the exception and the reason it exists is the worst gloss
    this feature has produced. A reader tapped ``learning`` in a passage
    about artificial intelligence; what came back was "a computer process of
    finding patterns in data", filed under the lemma ``learn`` and marked a
    noun. Every part of that is a faithful reading of ``machine learning``
    and a false statement about the verb the learner then had on their list.

    So the model is allowed to answer about something WIDER than what was
    tapped, and says so by naming the term as the paragraph writes it. The
    caller locates that string and stores the entry over the term's span --
    which is also what makes the tap work next time, because an entry whose
    span covers three words answers a tap on any of them.

    Empty for the overwhelming majority of words, which stand on their own.
    """

    lemma: str
    pos: str
    meaning_en: str
    meaning_uz: str
    cefr_level: str
    #: What the word usually means, wherever it is met.
    #:
    #: Optional, and last with the other optional fields, because it is an
    #: improvement on the answer rather than the answer. :func:`parse` falls
    #: back to ``meaning_en`` where the model would not give one separately:
    #: the contextual sense is what the reader is waiting for, and refusing
    #: the whole gloss over the improvement would be the tail wagging the
    #: dog.
    meaning_core_en: str = ""
    meaning_core_uz: str = ""
    #: Whether the two are genuinely different senses rather than two
    #: wordings of one. False whenever the core meaning fell back, because
    #: there is then nothing to differ from.
    sense_differs: bool = False
    #: The multi-word term this word stands inside, exactly as the paragraph
    #: writes it, or empty. See the class docstring.
    term: str = ""


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
    core_en, core_uz = line("meaning_core_en"), line("meaning_core_uz")
    level = str(said.get("cefr") or "").strip().upper()
    part = str(said.get("pos") or "").strip().lower().rstrip(".")
    if not (lemma and meaning_en and meaning_uz) or level not in LEVELS:
        return None
    # Both halves of the usual meaning or neither: one English line with no
    # Uzbek beside it is a heading promising a meaning the reader cannot
    # read, which is the same half-entry this function refuses everywhere
    # else. Unlike the rest it falls back instead of refusing, because the
    # reader is waiting on the CONTEXTUAL sense and that one arrived.
    if not (core_en and core_uz):
        core_en = core_uz = ""
    differs = bool(said.get("sense_differs")) and bool(core_en)
    if differs and core_en.casefold() == meaning_en.casefold():
        differs = False
    return Gloss(
        lemma=lemma,
        pos=part if part in PARTS else "",
        meaning_core_en=core_en or meaning_en,
        meaning_core_uz=core_uz or meaning_uz,
        meaning_en=meaning_en,
        meaning_uz=meaning_uz,
        sense_differs=differs,
        cefr_level=level,
        term=" ".join(str(said.get("term") or "").split()),
    )


class ChatDictionary:
    """One chat model, asked about one word in one paragraph.

    Both providers speak OpenAI's chat format, so they differ by a URL, a
    key and a model name and share everything else. Two classes with one
    body between them would be two places to fix the next prompt.

    Deliberately not retried. This runs inside a request a reader is waiting
    on, and the reader's alternative to waiting twice is reading the
    sentence again -- which is the skill the paper is testing anyway. What
    stands behind a failure is the NEXT provider in the chain, not a second
    attempt at the one that just refused.
    """

    def __init__(
        self,
        name: str,
        url: str,
        model: str,
        api_key: str,
        timeout: float = 20.0,
    ) -> None:
        self.name = name
        self._url = url
        self._model = model
        self._api_key = api_key
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def look_up(self, word: str, context: str) -> Gloss | None:
        if not self._api_key:
            return None
        prompt = PROMPT.format(
            word=word, context=context, parts=", ".join(PARTS),
            levels=", ".join(LEVELS), meaning=MEANING,
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                self._url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [{"role": "user", "content": prompt}],
                    # Two senses in two languages, and a handful of short
                    # fields around them. Raised from 400 when the usual
                    # meaning was added: a ceiling that cuts the reply off
                    # mid-string does not parse, and the reader gets "we
                    # couldn't find a meaning" for a word the model knew
                    # perfectly well. Still low enough to be the cheapest
                    # guard against a model that decides to write an essay
                    # about the etymology.
                    "max_tokens": 800,
                    "temperature": 0.0,
                },
            )
        response.raise_for_status()
        body = response.json()
        return parse(body["choices"][0]["message"]["content"] or "")


def GroqDictionary() -> ChatDictionary:  # noqa: N802 - reads as a class
    # Not `settings.groq_timeout_s` — that is two minutes, sized for
    # uploading a recording, and a reader mid-paper will not wait twenty
    # seconds let alone a hundred and twenty.
    return ChatDictionary(
        "groq", GROQ_CHAT_URL, GROQ_MODEL, settings.groq_api_key
    )


def GeminiDictionary() -> ChatDictionary:  # noqa: N802 - reads as a class
    return ChatDictionary(
        "gemini", GEMINI_CHAT_URL, GEMINI_MODEL, settings.gemini_api_key
    )


def providers() -> list[DictionaryProvider]:
    """The dictionaries this deployment has, in the order to try them.

    Only the configured ones, so a deployment with a single key behaves
    exactly as it did before there were two.
    """
    return [
        made
        for made in (GroqDictionary(), GeminiDictionary())
        if made.configured
    ]


async def look_up(word: str, context: str) -> Gloss | None:
    """Ask each provider in turn until one answers.

    A provider that RAISES is out of action -- no key, no quota, no network
    -- and the next one is tried. A provider that returns ``None`` has
    answered: it read the paragraph and there is no meaning to give, which
    is the ordinary outcome for a name or a number, and asking a second
    model the same question about the same name would spend a request to be
    told the same thing.

    That distinction is the whole design. It is also why this loop cannot
    become "try everything until something non-empty comes back": the point
    of a chain is to survive an outage, not to shop around for an answer
    somebody wants to hear.
    """
    for source in providers():
        try:
            return await source.look_up(word, context)
        except Exception:  # noqa: BLE001 - the next provider is the answer
            logger.warning(
                "dictionary provider %s could not answer %r",
                getattr(source, "name", "?"), word, exc_info=True,
            )
    return None
