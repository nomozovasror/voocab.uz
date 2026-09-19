"""Make the seeded corpus public, one material at a time, through the real rule.

    cd backend && uv run --no-sync python -m scripts.publish_seeded --dry-run
    cd backend && uv run --no-sync python -m scripts.publish_seeded
    cd backend && uv run --no-sync python -m scripts.publish_seeded --unpublish

Publishing is the one change the API refuses rather than accepts and undoes,
because the whole point is that nobody else sees a material until it holds up.
A script that set ``visibility = 'public'`` in a loop would walk straight past
that, so this asks ``publish_blockers()`` about every material and publishes
only the ones it has nothing to say about -- the same function the endpoint
calls, not a copy of its reasoning.

Anything it refuses is printed with the reason, and stays private.

The collections go with them, through ``can_publish`` for the same reason: a
public collection whose materials are private is a shelf of locked doors.
"""

import argparse
import asyncio
import logging
import re
import uuid

from sqlalchemy import select

from app.core.database import async_session_factory
from app.models.collection import Collection, CollectionItem
from app.models.material import Material
from app.services import collections as collections_service
from app.services import publishing as publishing_service

#: Every seeded material's title ENDS with the code its
#: importer generates -- "C11 T4 · Part 2" for a listening
#: section, "… — C11 T4 P2" for a reading passage, whose own
#: passage title comes first. Anchored at the end for exactly
#: that reason.
SEEDED = re.compile(r"(?:^| — )(C\d{1,2}|TR2?|GD|#\d+) T\d+ (?:· Part |P)\d+$")

logger = logging.getLogger("publish")


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="say what would happen and change nothing")
    ap.add_argument("--unpublish", action="store_true",
                    help="put them all back to private")
    ap.add_argument("--owner", default="d2b9f563-9669-4fb3-b6dc-51536c8baac1")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    owner = uuid.UUID(args.owner)

    async with async_session_factory() as session:
        materials = [m for m in (await session.scalars(select(Material).where(
            Material.author_id == owner).order_by(Material.title))).all()
            if SEEDED.search(m.title or "")]

        if args.unpublish:
            for material in materials:
                material.visibility = "private"
                session.add(material)
            for collection in (await session.scalars(select(Collection).where(
                    Collection.author_id == owner))).all():
                if (collection.cover_seed or "").startswith("book-"):
                    collection.visibility = "private"
                    session.add(collection)
            if not args.dry_run:
                await session.commit()
            logger.info("%d material(s) back to private", len(materials))
            return 0

        published, refused = 0, []
        for material in materials:
            blockers = await publishing_service.publish_blockers(session, material)
            if blockers:
                refused.append((material.title, " ".join(blockers)))
                continue
            if material.visibility != "public":
                material.visibility = "public"
                session.add(material)
            published += 1
        if not args.dry_run:
            await session.commit()

        logger.info("%d of %d material(s) %s public",
                    published, len(materials),
                    "would be" if args.dry_run else "are now")
        for title, why in refused:
            logger.info("  REFUSED %s — %s", title, why)

        # The shelf, once what is on it can be opened.
        for collection in (await session.scalars(select(Collection).where(
                Collection.author_id == owner).order_by(Collection.title))).all():
            if not (collection.cover_seed or "").startswith("book-"):
                continue
            why = await collections_service.can_publish(session, collection)
            if why:
                logger.info("  collection stays private: %s — %s",
                            collection.title, why)
                continue
            if collection.visibility != "public":
                collection.visibility = "public"
                session.add(collection)
        if not args.dry_run:
            await session.commit()
        public = sum(1 for c in (await session.scalars(select(Collection).where(
            Collection.author_id == owner))).all()
            if c.visibility == "public" and (c.cover_seed or "").startswith("book-"))
        logger.info("%d book collection(s) public", public)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
