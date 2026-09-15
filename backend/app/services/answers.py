"""How an answer is written down for comparison.

One rule, in its own module, for a reason that is structural rather than
tidy: **grading** owns what makes an answer right, and **mistakes** owns what
kind of wrong a wrong one was — and both of them have to compare the same two
strings the same way, or the second contradicts the first. Left in grading, it
made ``mistakes`` import ``grading``, which put the two lowest modules in the
package in a cycle with everything built on top of them.

Deliberately dumb, and §3.5 says so: no fuzzy matching, no number/word
conversion, no stemming. Everything cleverer than this lives in
:mod:`app.services.mistakes`, where it is used to EXPLAIN a wrong answer and
never to decide one.
"""

import re

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_answer(text: str) -> str:
    """§3.5: trim the ends, collapse internal whitespace runs to one space,
    lowercase. Applied identically to the given answer and to every accepted
    answer before they are compared.

    Never written back. ``QuestionAttempt.given_answer`` keeps what the
    candidate actually typed, which is the only reason a misspelling can be
    told from a different word afterwards.
    """
    return _WHITESPACE_RE.sub(" ", text.strip()).lower()
