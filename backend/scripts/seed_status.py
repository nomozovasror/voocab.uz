"""How complete the seeded materials are, measured against the real rules.

    cd backend && uv run --no-sync python -m scripts.seed_status
    cd backend && uv run --no-sync python -m scripts.seed_status --blocked

Completeness is not a thing the seed pipeline can decide for itself. It knows
whether each of its stages exited zero, and a stage can exit zero having
produced something the app will not publish -- a labelling group with no
picture, an answer with no span in the recording. So this asks the server's own
``publish_blockers()``, the same function that refuses a material going public,
and reports what it says.

The replay figure is separate and not a blocker: an answer with no
``replay_start_ms`` still works, the learner just cannot jump to where it was
said. It is counted because it is the number that moved every time a margin
marker was recovered, and it is the honest measure of how much of the reading
actually landed.
"""

import argparse
import asyncio
import collections
import re

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.material import Material
from app.models.part import Part
from app.models.question import Question
from app.models.question_group import QuestionGroup
from app.services.publishing import publish_blockers

#: Every seeded material is titled from its book, test and section.
SEEDED = re.compile(r"^Cambridge IELTS \d+ ", re.I)


async def report(show_blocked: bool) -> None:
    async with async_session_factory() as session:
        materials = [m for m in (await session.scalars(
            select(Material).order_by(Material.title))).all()
            if SEEDED.match(m.title or "")]

        # One query for every seeded question, not one per material: the join
        # from a question up to its material runs group -> part -> material,
        # and walking that 143 times is 143 round trips for a count.
        wanted = {m.id for m in materials}
        spans = collections.Counter()
        rows = await session.exec(
            select(Part.material_id, Question.replay_start_ms)
            .join(QuestionGroup, QuestionGroup.id == Question.group_id)
            .join(Part, Part.id == QuestionGroup.part_id))
        for material_id, replay in rows:
            if material_id in wanted:
                spans["total"] += 1
                spans["with"] += replay is not None

        complete, reasons, blocked = 0, collections.Counter(), []
        for material in materials:
            why = await publish_blockers(session, material)
            if why:
                blocked.append((material.title, why))
                for reason in why:
                    reasons[re.sub(r"\b\d+\b", "N", reason)] += 1
            else:
                complete += 1

    pct = 100 * spans["with"] / spans["total"] if spans["total"] else 0
    print(f"{len(materials)} materials | {spans['with']}/{spans['total']} replay ({pct:.0f}%)")
    print(f"{complete}/{len(materials)} content-complete")
    for reason, count in reasons.most_common():
        print(f"  {count:3}x {reason}")
    if show_blocked:
        print()
        for title, why in blocked:
            print(f"{title}\n    " + "\n    ".join(why))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--blocked", action="store_true",
                    help="name every material that is not complete, and why")
    args = ap.parse_args()
    asyncio.run(report(args.blocked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
