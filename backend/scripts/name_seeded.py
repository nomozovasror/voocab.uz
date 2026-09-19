"""Split a seeded material's title into the name it has and the book it is in.

    cd backend && uv run --no-sync python -m scripts.name_seeded
    cd backend && uv run --no-sync python -m scripts.name_seeded --write

A one-off, and idempotent: a material that already has a ``reference`` is
left alone, so running it twice is running it once.

Every seeded title carries two different things run together::

    Book review: The World of Sugar by Ulbe Bosma — C21 T1 P3
    C21 T1 · Part 3

The first half is what the book calls the passage, which is what a learner
reads and recognises on a card. The second is which test it came from, which
is a fact about where it is from. They are now two columns — see the
``b3e91a7c40d2`` migration for why all three readers of this string wanted
them apart.

## Listening had no first half, and it does have one

A reading passage prints its title at the top of the page. A listening part
does not: the book prints "Part 3" and plays a recording. So every listening
material was called "C21 T1 · Part 3" and nothing else, which is a code where
its reading neighbour has a name.

But the name is there, printed, in the first task on the sheet — "Oyster Bay
Sailing Club Courses" over the table, "SELF-DRIVE TOURS IN THE USA" over the
notes. It is a heading in the layout grammar (``# ...`` in a group's
template), which means it is already stored and already exactly what the book
printed. 156 of 266 listening materials have one.

The other 110 do not, and are almost all Part 3 — multiple choice and
matching, which print questions and no heading at all. Those keep the code as
their name. That is the honest answer rather than a gap: the book did not
name them, and a name invented from the transcript would be this app telling
a learner the book said something it did not. The same argument
``Passage.paragraphs[].label`` is nullable for.
"""

import argparse
import asyncio
import re

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.material import Material
from app.models.part import Part
from app.models.question_group import QuestionGroup

#: A seeded title, as the two importers wrote it. Reading puts the passage's
#: own name first and the code after an em dash; listening is the code alone,
#: with "· Part 3" where reading has "P3".
#:
#: Anchored at both ends. A title that merely CONTAINS something code-shaped
#: is an author's, and an author's material is not this script's business.
SEEDED = re.compile(
    r"^(?:(?P<name>.+?) — )?"
    r"(?P<book>C\d{1,2}|TR2?|GD|#\d+) T(?P<test>\d+) "
    r"(?:· Part |P)(?P<part>\d+)$"
)


def heading(template: str) -> str | None:
    """The first heading printed over a task, or nothing.

    First rather than longest or last: a sheet's own title is printed above
    the sheet's first task, and a later one belongs to a later task on the
    same sheet ("Questions 7-10: General information").
    """
    for line in (template or "").splitlines():
        if line.startswith("#") and line[1:].strip():
            return line[1:].strip()
    return None


async def named(session, material: Material) -> str | None:
    """What the book calls this material, if it calls it anything."""
    parts = (await session.scalars(
        select(Part).where(Part.material_id == material.id)
        .order_by(Part.order_index))).all()
    for part in parts:
        # A reading passage carries its title as data already; there is no
        # need to go looking in the questions for it.
        if part.passage and (title := (part.passage.get("title") or "").strip()):
            return title
        groups = (await session.scalars(
            select(QuestionGroup).where(QuestionGroup.part_id == part.id)
            .order_by(QuestionGroup.order_index))).all()
        for group in groups:
            if found := heading((group.config or {}).get("template", "")):
                return found
    return None


async def run(write: bool) -> None:
    async with async_session_factory() as session:
        materials = (await session.scalars(
            select(Material).order_by(Material.title))).all()

        split = renamed = kept = skipped = 0
        show: list[tuple[str, str, str]] = []
        for material in materials:
            if material.reference:
                skipped += 1
                continue
            found = SEEDED.match(material.title or "")
            if not found:
                skipped += 1
                continue

            reference = (f"{found['book']} T{found['test']}"
                         f" P{found['part']}")
            title = (found["name"] or "").strip() or await named(
                session, material)
            # No name anywhere: the code is the name. Never blank -- the
            # column is not null, and a card with no title is a card nobody
            # can tell from the one under it.
            title = title or reference

            split += 1
            if title == material.title:
                kept += 1
            else:
                renamed += 1
            if len(show) < 15:
                show.append((material.title, title, reference))

            if write:
                material.title = title
                material.reference = reference
                session.add(material)

        if write:
            await session.commit()

    for before, title, reference in show:
        print(f"  {before}\n    -> {title!r}  [{reference}]")
    print(f"\n{split} seeded, {renamed} renamed, {kept} already named,"
          f" {skipped} left alone (authored, or already done)")
    if not write:
        print("Nothing written. Pass --write to do it.")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help="actually change the titles; without it, a report")
    args = ap.parse_args()
    asyncio.run(run(args.write))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
