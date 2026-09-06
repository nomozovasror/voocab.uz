"""How a margin marker is written, in one place.

The book prints `Q1` down the side of the audioscript against the line where
that answer is spoken. Where one turn answers two questions -- which is common,
because a single sentence often fills two gaps -- it prints both, and it prints
them a dozen different ways:

    Q21/22    Q21 & 22    Q21/Q22    Q11 & 12    Q23, Q24

The first version of this matched `^Q\\d+$` and nothing else, so every one of
those was unparseable and BOTH its questions were recorded as having no marker.
84 such strings across 34 sections were hiding 169 question numbers, and every
one of them cost an answer its replay span. The model had read the page
correctly each time.

Which is the argument for this file existing at all: three programs read these
strings, and a marker syntax understood in three places is understood
differently in three places.
"""

import re

#: Any run of digits, with or without a Q in front. Deliberately loose: the
#: separator between two numbers is a slash here, an ampersand there and a
#: comma somewhere else, and none of those distinctions mean anything.
_NUMBER = re.compile(r"\d+")
#: The one non-numeric marker the book uses.
EXAMPLE = "example"


def numbers(marker: str | None) -> list[int]:
    """Every question number a marker string names, in order.

    ``"Q21/22"`` and ``"Q21 & 22"`` both give ``[21, 22]``; ``"Example"`` and
    an empty marker give ``[]``.
    """
    if not marker:
        return []
    return [int(n) for n in _NUMBER.findall(marker)]


def is_example(marker: str | None) -> bool:
    return bool(marker) and EXAMPLE in marker.strip().lower()
