"""The two accents a learner can hear, and which Kokoro voice speaks each.

ONE table, read by everything that has to know: the render queue (which voice
a render is made with, and so which key it has), the worker's synthesiser
(which pipeline to load), the settings schema (what is a valid choice) and the
pronunciation tables (which phoneme alphabet a heteronym is decided in).

The accent only chooses the TTS voice (vocabulary stage 3, decisions 22-23):
every word is Kokoro TTS, since the live clips were dropped (2026-10-07).
British is the default -- the brief's choice -- for a learner who has never
opened the setting.
"""

from dataclasses import dataclass
from typing import Literal

Accent = Literal["british", "american"]
DEFAULT_ACCENT: Accent = "british"


@dataclass(frozen=True)
class AccentVoice:
    accent: Accent
    #: Kokoro voice name (``voices/{voice}.pt``).
    voice: str
    #: Kokoro ``KPipeline(lang_code=...)``: ``b`` British, ``a`` American. The
    #: language code picks the G2P front end (misaki's gb or us lexicon), the
    #: voice picks the speaker; the two must agree.
    lang_code: str


ACCENTS: dict[Accent, AccentVoice] = {
    "british": AccentVoice("british", "bf_emma", "b"),
    "american": AccentVoice("american", "af_heart", "a"),
}

ACCENT_NAMES: tuple[Accent, ...] = tuple(ACCENTS)


def voice_for(accent: Accent | str) -> str:
    return ACCENTS[accent].voice  # type: ignore[index]


def lang_code_for_voice(voice: str) -> str:
    """The pipeline language a voice belongs to. A voice outside the table is a
    programming error (a render row carries one of ours), so it raises."""
    for entry in ACCENTS.values():
        if entry.voice == voice:
            return entry.lang_code
    raise ValueError(f"no accent uses the voice {voice!r}")
