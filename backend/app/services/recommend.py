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

**A course in progress outranks everything below it.** A learner can work
from the catalogue or from a collection, and until this existed the two talked
over each other: somebody four papers into a six-paper course opened the page
and was handed three unrelated ones. Two reasons that is the wrong way round,
and both are stronger than any heuristic here.

They already chose the course. A recommendation that competes with a choice
the reader made is the page arguing with them rather than helping.

And its order is a person's judgement about what to do when, made by somebody
who knows the exam. Band-fit over a first-try average is a guess by
comparison, and a guess does not get to overrule a judgement.

The same reasoning runs the other way at the bottom: when the recommendation
IS a loose one, it skips materials sitting mid-sequence in a course they have
started. Offering lesson five to somebody on lesson three denies the one thing
a collection claims.

Nothing here is a model. It is four rules over numbers the platform already
has, and the reason each one exists is written next to it — which is the point
at which a recommender becomes reviewable instead of magic.
"""

import uuid

from app.core.database import AsyncSession
from app.services import (
    collections as collections_service,
    drills as drills_service,
    learner_stats,
    listening as listening_service,
)

#: How many materials somebody has to have finished before this says anything
#: at all.
#:
#: Below it there is no block: the search field, the filters, and then the
#: list. A recommendation off one paper is a guess in a confident voice, and
#: the reader has no way to tell those apart — so the honest move is silence
#: until there is something to go on, and then the block simply appears.
#:
#: Three rather than one, which is where the sidebar's own cards start. The
#: page fills in two steps rather than one because of it, and that is the
#: trade: an average over three papers is worth reading, an average over one
#: is a single morning.
MIN_MATERIALS = 3

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

#: What to serve somebody who is level everywhere: hard first. Nothing else
#: here ever opens with `hard` — this is the one reader for whom it is the
#: right answer rather than a discouragement.
_STEADY_RANKS = {"hard": 0, "medium": 1, "easy": 2, "new": 3}

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


def _steady(by_part: list[dict]) -> bool:
    """Whether they are level across the whole paper.

    The exact inverse of :func:`_weak_part`, using the same two constants, so
    the two can never both be true and the block can never tell somebody they
    have a weak part and that they haven't. Every part scored, none of them
    below the ceiling, and the whole spread inside the gap that would have
    made one of them "clearly behind".

    It exists because "your weakest area" is a sentence with nothing behind it
    for somebody who is good everywhere, and saying it anyway is the block
    being confident instead of useful. What that reader wants next is not
    their worst part — it is a harder paper.
    """
    scored = [
        row["accuracy_pct"] for row in by_part if row["accuracy_pct"] is not None
    ]
    if len(scored) < len(learner_stats.PARTS):
        return False
    return min(scored) >= WEAK_CEILING and max(scored) - min(scored) < DECISIVE_GAP


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
    """What the block above the list says, and why.

    ``reason`` is the whole contract. Each value is a genuinely different
    claim, and the client has to be able to tell them apart:

    * ``none`` — fewer than :data:`MIN_MATERIALS` finished. There is no block
      at all: silence beats a guess in a confident voice, and the block simply
      appearing once there is something to go on is a better first impression
      than one that was always there saying nothing.
    * ``finished_course`` — the attempt they just submitted completed a
      course. It says so, with what they averaged, and it is gone the moment
      they sit anything else.
    * ``course`` — part-way through a collection: the next lesson in it, in
      its order. This outranks the suggestions below because they chose the
      course and because its order is a person's judgement, not this module's.
    * ``task_type`` — working through one kind of question, recently and more
      than once (:data:`app.services.drills.CARRY_ON_FROM`,
      :data:`~app.services.drills.CARRY_ON_WITHIN`). A report of what they
      were doing rather than a guess about what would suit them, which is why
      it sits above the three below. Against ``course`` it is decided by
      which was touched last, not by rank — see the note there.
    * ``weak_part`` — one part is clearly behind the others.
    * ``steady`` — none of them is, and all four are good. Harder material,
      because "your weakest area" is a sentence with nothing behind it for
      somebody who is good everywhere.
    * ``level`` — nothing clear either way. Pitched at their average.

    An empty ``items`` is a real answer for every reason but the last two: a
    learner who has sat everything gets the reason and no rows, and the page
    has to be able to draw that.
    """
    profile = await learner_stats.first_attempt_profile(session, user_id)
    if not profile["sat_anything"] or profile["materials_done"] < MIN_MATERIALS:
        return _nothing()

    # Just finished one — said at the moment it is true and not after.
    finished = await collections_service.just_finished_for(session, user_id)
    if finished is not None:
        collection = finished["collection"]
        ids = finished["material_ids"]
        return {
            **_nothing(),
            "reason": "finished_course",
            "collection": {"id": collection.id, "title": collection.title},
            "accuracy_pct": await learner_stats.first_try_average_for(
                session, user_id, ids
            ),
            "done": len(ids),
            "remaining": 0,
            "of": len(ids),
            "in_progress_count": await collections_service.in_progress_count(
                session, user_id
            ),
        }

    # Carrying on beats being recommended to, so these are asked next.
    #
    # Two things can be carried on with — a course, and a kind of question —
    # and which one is offered is decided by WHEN, not by a fixed ladder. The
    # rule that a course outranks everything else was written against the
    # three suggestions below: those are guesses about what would suit
    # somebody, and a course is a judgement they made. It was never a rule
    # about two facts, and between two facts the honest one is the later —
    # which is exactly the argument `collections.in_progress_for` already
    # makes for choosing between two courses ("the question a page asks when
    # somebody comes back is where they left off").
    #
    # It also has to work this way to mean anything. Every material in a
    # seeded library belongs to a book of sixteen to thirty-two, so one
    # material sat leaves a course in progress for weeks; ranked below that,
    # a kind of question could be worked every day and never be offered.
    carrying_on = await collections_service.in_progress_for(session, user_id)
    drilling = await drills_service.in_progress_for(session, user_id)
    if (
        carrying_on is not None
        and drilling is not None
        and drilling["last_at"] > carrying_on["last_at"]
    ):
        carrying_on = None
    if carrying_on is not None:
        collection = carrying_on["collection"]
        # One lesson, not three. Two rows under a Continue button leave the
        # reader working out which one the button opens and which number each
        # of them is; one row cannot disagree with the button above it. The
        # rest of the course is a click away on its own page.
        materials = await listening_service.materials_in_order(
            session, carrying_on["remaining"][:1]
        )
        return {
            **_nothing(),
            "reason": "course",
            "collection": {"id": collection.id, "title": collection.title},
            "position": carrying_on["position"],
            "done": carrying_on["done"],
            # What the block prints beside the lesson number. "2 left" rather
            # than "4 of 6 done": both are true, and only one of them invites
            # the reader to subtract and find an off-by-one that isn't there.
            # Somebody who skipped a lesson is legitimately on lesson 4 with
            # four done, and the bar already shows how far along they are.
            "remaining": len(carrying_on["remaining"]),
            "of": carrying_on["total"],
            "in_progress_count": await collections_service.in_progress_count(
                session, user_id
            ),
            "items": await listening_service._catalogue_rows(
                session, user_id, materials
            ),
        }

    # The other carrying-on, reached when there is no course to carry on with
    # or when this was worked more recently. Above the three below it for the
    # reason the course is: this is a report of what they were doing, and
    # those are guesses about what would suit them.
    if drilling is not None:
        return {
            **_nothing(),
            "reason": "task_type",
            # The TYPE, not a name: what we call a kind of question belongs
            # with the rest of the interface's words, and the client already
            # holds the table that turns one into a card's title.
            "task_type": drilling["type"],
            "next_group_id": drilling["next_group_id"],
            "done": drilling["done"],
            "of": drilling["total"],
            "remaining": drilling["total"] - drilling["done"],
            "in_progress_count": await collections_service.in_progress_count(
                session, user_id
            ),
        }

    # Nothing that is waiting its turn inside a course they have started.
    skip = await collections_service.sequenced_material_ids(session, user_id)
    average = profile["average_pct"]
    by_part = profile["by_part"]

    weak = _weak_part(by_part)
    if weak is not None:
        return {
            **_nothing(),
            "reason": "weak_part",
            "part": weak["part"],
            "accuracy_pct": weak["accuracy_pct"],
            "items": await listening_service.recommended(
                session,
                user_id,
                part=weak["part"],
                ranks=_ranks_for(average),
                size=size,
                skip=skip,
            ),
        }

    if _steady(by_part):
        return {
            **_nothing(),
            "reason": "steady",
            "accuracy_pct": average,
            "items": await listening_service.recommended(
                session,
                user_id,
                part=None,
                ranks=_STEADY_RANKS,
                size=size,
                skip=skip,
                prefer_full=True,
            ),
        }

    return {
        **_nothing(),
        "reason": "level",
        "accuracy_pct": average,
        "items": await listening_service.recommended(
            session,
            user_id,
            part=None,
            ranks=_ranks_for(average),
            size=size,
            skip=skip,
        ),
    }


def _nothing() -> dict:
    """The shape every answer has, with nothing said.

    One definition, so a branch that forgets a field sends a null rather than
    a missing key — and so "no block" is a value the client switches on rather
    than an empty response it has to guess about.
    """
    return {
        "reason": "none",
        "part": None,
        "accuracy_pct": None,
        "collection": None,
        "position": None,
        "done": None,
        "remaining": None,
        "of": None,
        "task_type": None,
        "next_group_id": None,
        "in_progress_count": 0,
        "items": [],
    }
