"""What to practise next — the page choosing, when the reader would rather
not.

A catalogue of a thousand papers is not browsable, and a search field only
helps somebody who already knows what they are looking for. This is the answer
to "I have twenty minutes, what should I do": three materials, and a sentence
saying why those three.

**The sentence is the hard part, not the query.** A recommendation that cannot
say why it was made is a shuffle with a confident label on it, so every branch
here produces a reason the interface can print in full, and a branch that
cannot justify itself falls through to one that can.

Which is why "your weakest part" is guarded rather than assumed. The sidebar
used to make that claim off the part with the lowest accuracy and it did not
survive being looked at: 62% against 66% over a few dozen answers is noise,
and sending somebody to spend their evening on the difference is worse than
saying nothing. So a part is only named when the gap is big enough to mean
something (:data:`DECISIVE_GAP`) and the number is low enough to be worth
acting on (:data:`WEAK_CEILING`). Otherwise the recommendation is about their
LEVEL, which is a claim the same data does support.

Nothing here is a model. It is three rules over numbers the platform already
has, and the reason each one exists is written next to it — which is the point
at which a recommender becomes reviewable instead of magic.
"""

import uuid

from app.core.database import AsyncSession
from app.services import learner_stats, listening as listening_service

#: How many to put in front of somebody. Three is a choice; one is an
#: instruction and a learner who does not fancy it has nowhere to go, and six
#: is the catalogue again in miniature.
SIZE = 3

#: How many points below the next-weakest part a part must be before it is
#: named as the weak one.
#:
#: Ten, and the number is doing real work rather than being round. Over the
#: few dozen answers a part carries early on, a gap smaller than this is
#: within the noise of which particular questions somebody happened to get:
#: name it anyway and the page sends people to Part 2 one week and Part 3 the
#: next, on evidence that never changed.
DECISIVE_GAP = 10

#: Above this, nothing is weak enough to be worth naming. Somebody whose worst
#: part is 78% does not have a weak part; they have four good ones, and
#: telling them otherwise is inventing a problem to solve.
WEAK_CEILING = 75

#: The band order to serve, by how the learner is doing. The keys are the
#: upper bound of a first-try average.
#:
#: The shape of each row matters more than the exact thresholds: the band that
#: suits them first, the next one out second, and `new` always last — an
#: unrated material might be anything, and "might be anything" is not a
#: recommendation. Nobody is ever sent to `hard` first, including the people
#: doing well: the top of this scale is somebody at 85%, and the difference
#: between them and somebody at 65% is which of medium and hard comes second,
#: not whether their evening starts with a paper most people fail.
_LADDER: list[tuple[int, dict[str, int]]] = [
    (60, {"easy": 0, "medium": 1, "hard": 2, "new": 3}),
    (80, {"medium": 0, "easy": 1, "hard": 2, "new": 3}),
    (101, {"medium": 0, "hard": 1, "easy": 2, "new": 3}),
]

#: Where somebody with no history at all is sent. Part 1 is the gentlest
#: section of the paper and the one whose task types the rest are built on,
#: and easiest-first inside it.
_START_RANKS = {"easy": 0, "medium": 1, "hard": 2, "new": 3}
START_PART = 1


def _ranks_for(average: int | None) -> dict[str, int]:
    """The band order for a learner at ``average``.

    ``None`` — nothing scored yet — gets the gentlest rung rather than the
    middle one. Being handed something too easy costs a few minutes; being
    handed something too hard on your first evening costs the habit.
    """
    if average is None:
        return _START_RANKS
    for ceiling, ranks in _LADDER:
        if average < ceiling:
            return ranks
    return _LADDER[-1][1]


def _weak_part(by_part: list[dict]) -> dict | None:
    """The part worth naming, or ``None`` where naming one would be a guess.

    Three conditions, and each one is a way of being wrong that this has
    already been caught being:

    * The part must be SCORED — below :data:`app.services.learner_stats.MIN_ANSWERS`
      there is no percentage, and a part somebody has barely touched is not a
      part they are bad at.
    * It must be below :data:`WEAK_CEILING`, or there is no weakness here.
    * It must be clear of the next-weakest by :data:`DECISIVE_GAP`, or the
      ranking is noise. A learner with exactly one scored part has nothing to
      be clear of, and that is enough on its own: one measured part and three
      unmeasured ones is not a close-run thing.
    """
    scored = sorted(
        (row for row in by_part if row["accuracy_pct"] is not None),
        key=lambda row: row["accuracy_pct"],
    )
    if not scored:
        return None
    weakest = scored[0]
    if weakest["accuracy_pct"] >= WEAK_CEILING:
        return None
    if len(scored) > 1:
        gap = scored[1]["accuracy_pct"] - weakest["accuracy_pct"]
        if gap < DECISIVE_GAP:
            return None
    return weakest


async def next_up(
    session: AsyncSession, user_id: uuid.UUID, *, size: int = SIZE
) -> dict:
    """Three materials and the reason for them.

    ``reason`` is what the interface prints, and the three values are three
    different sentences rather than three ways of saying the same one:

    * ``start`` — no finished attempts. Part 1, easiest first.
    * ``weak_part`` — one part is clearly behind the others. Materials with
      that part in them, at their level.
    * ``level`` — nothing is clearly behind. Anything they have not sat, at
      their level. This is the ordinary case and it is not a failure of the
      other two: most people practising are not lopsided, they are just
      practising.

    An empty ``items`` is a real answer and the page has to survive it: a
    learner who has sat everything in the library gets a reason and no rows.
    """
    profile = await learner_stats.first_attempt_profile(session, user_id)
    if not profile["sat_anything"]:
        return {
            "reason": "start",
            "part": START_PART,
            "accuracy_pct": None,
            "items": await listening_service.recommended(
                session, user_id, part=START_PART, ranks=_START_RANKS, size=size
            ),
        }

    average = profile["average_pct"]
    ranks = _ranks_for(average)
    weak = _weak_part(profile["by_part"])
    if weak is not None:
        return {
            "reason": "weak_part",
            "part": weak["part"],
            "accuracy_pct": weak["accuracy_pct"],
            "items": await listening_service.recommended(
                session, user_id, part=weak["part"], ranks=ranks, size=size
            ),
        }

    return {
        "reason": "level",
        "part": None,
        "accuracy_pct": average,
        "items": await listening_service.recommended(
            session, user_id, part=None, ranks=ranks, size=size
        ),
    }
