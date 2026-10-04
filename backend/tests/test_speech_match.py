"""The `speak` matcher (`app.services.speech_match`): what is accepted for a
word under decision 17's substitutions, and -- as important -- what is not."""

import pytest

from app.services import speech_match as sm


@pytest.mark.parametrize(
    "target, heard",
    [
        # th -> t / s / d / z, in any of the four
        ("think", "tink"), ("think", "sink"), ("think", "dink"), ("think", "zink"),
        ("this", "dis"), ("this", "zis"), ("this", "tis"), ("this", "sis"),
        # w -> v
        ("window", "vindow"), ("work out", "vork out"),
        # a <-> e, both ways, only on the target's own letters
        ("cat", "cet"), ("bed", "bad"), ("water", "veter"),
        # a vowel before an initial consonant cluster
        ("stop", "istop"), ("stop", "estop"), ("school", "ischool"),
        ("state", "estate"),  # a real word, accepted on purpose (docstring)
        # normalisation: case, punctuation, hyphens, spacing
        ("think", "Think."), ("tip-of-the-tongue", "tip of the tongue"),
        ("give rise to", "  Give   rise to "),
        # exact is always fine
        ("play", "play"),
    ],
)
def test_accepted(target: str, heard: str) -> None:
    assert sm.matches(heard, target)


@pytest.mark.parametrize(
    "target, heard",
    [
        ("play", "pray"),            # l -> r is not a rule
        ("cat", "ket"),              # c -> k is not a rule
        ("school", "iskool"),        # needs ch -> k and oo: not a rule
        ("stop", "ostop"),           # only i / e go in front
        ("stop", "astop"),
        ("sit", "isit"),             # no initial cluster, no prefix
        ("this", "ithis"),           # th is ONE sound, not a cluster
        ("think", "thinks"),         # no inflection tolerance
        ("think", "thnk"),           # no edit distance
        ("think", "fink"),           # th -> f is not a rule
        ("window", "windows"),
        ("give rise to", "rise"),    # phrases are compared whole
        ("give rise to", "give rise"),
        ("window", "wvndow"),
        ("", "anything"),
        ("think", ""),
    ],
)
def test_rejected(target: str, heard: str) -> None:
    assert not sm.matches(heard, target)


def test_match_returns_the_first_matching_alternative_as_sent() -> None:
    assert sm.match(["tank", "Tink", "sink"], "think") == "Tink"
    assert sm.match(["pray", "plea"], "play") is None


def test_a_long_phrase_does_not_explode() -> None:
    target = "the weather with the thing that we want"
    assert sm.matches(target, target)
    assert not sm.matches(target + " x", target)
