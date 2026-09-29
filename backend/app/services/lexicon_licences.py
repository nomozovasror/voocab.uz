"""The public "Data sources and licences" page (`brief-lexicon.md` §9):
GENERATED from what `source_id`/`licence`/`frequency_source` actually sit in
the database, never a hand-written list of rows.

The two facts that do NOT come from the database are an entry's author,
title and licence link -- nobody stores those per-row, and they wouldn't
change if we did, so `REGISTRY` below is the one hand-written thing here.
Everything else (which keys are worth showing at all, and how many lexemes
or senses actually use each) is a live count, so a key present in the
registry but absent from this deploy's data (impossible today, but true the
day a list is dropped) never appears, and the obligation this project
actually has -- NGSL and NAWL are already in use -- cannot silently go
unlisted because someone forgot to add a row by hand.
"""

from dataclasses import dataclass

from sqlalchemy import func
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.lexicon import Lexeme, LexemeSense


@dataclass(frozen=True)
class _Entry:
    title: str
    authors: str
    licence_name: str
    licence_url: str
    source_url: str
    #: Shown on the card beneath the licence badge, empty for every entry but
    #: Princeton WordNet's -- see that entry's own comment for why it alone
    #: needs one.
    usage_note: str = ""


_CC_BY_SA_4 = "https://creativecommons.org/licenses/by-sa/4.0/"
_CC_BY_4 = "https://creativecommons.org/licenses/by/4.0/"
_NGSL_FAMILY_AUTHORS = "Browne, C., Culligan, B. & Phillips, J."
_NGSL_FAMILY_URL = "https://www.newgeneralservicelist.com"

#: Keyed by `Lexeme.frequency_source` (the NGSL family) or `LexemeSense
#: .source_id` (`oewn`) -- the two columns `brief-lexicon.md` §9 names as
#: what the page is generated from. `off-list` and `model` are deliberately
#: absent: neither is a redistributed third-party source that owes an
#: attribution (see `app.models.lexicon.SENSE_SOURCES`'s own docstring for
#: why `model` carries no upstream licence at all).
REGISTRY: dict[str, _Entry] = {
    "ngsl": _Entry(
        "New General Service List", _NGSL_FAMILY_AUTHORS,
        "CC BY-SA 4.0", _CC_BY_SA_4, _NGSL_FAMILY_URL,
    ),
    "nawl": _Entry(
        "New Academic Word List", _NGSL_FAMILY_AUTHORS,
        "CC BY-SA 4.0", _CC_BY_SA_4, _NGSL_FAMILY_URL,
    ),
    "bsl": _Entry(
        "Business Service List", _NGSL_FAMILY_AUTHORS,
        "CC BY-SA 4.0", _CC_BY_SA_4, _NGSL_FAMILY_URL,
    ),
    "tsl": _Entry(
        "TOEIC Service List", _NGSL_FAMILY_AUTHORS,
        "CC BY-SA 4.0", _CC_BY_SA_4, _NGSL_FAMILY_URL,
    ),
    "moel": _Entry(
        "Medical Oral English List", _NGSL_FAMILY_AUTHORS,
        "CC BY-SA 4.0", _CC_BY_SA_4, _NGSL_FAMILY_URL,
    ),
    "oewn": _Entry(
        "Open English WordNet", "Open English WordNet Team",
        "CC BY 4.0", _CC_BY_4,
        "https://github.com/globalwordnet/english-wordnet",
    ),
    # Keyed by `LexemeSense.oewn_rank IS NOT NULL` (`sources` below), not by
    # `frequency_source` or `source_id` like every other row -- Princeton's
    # SemCor tag counts are not a source of DEFINITIONS (those are OEWN's,
    # above, under OEWN's own CC BY licence) or of a frequency BAND (that's
    # the NGSL family). They are used for exactly one thing: choosing which
    # of a lemma's OEWN senses is "the commonest" (`sense_rank`), and a
    # list-only lexeme's part of speech when OEWN's own counts have to decide
    # between two (`lexicon_enrich.top_sense_any_pos`). This entry appears on
    # the page only because `oewn_rank` is actually non-null on senses in
    # this deployment's database -- see `sources()`.
    #
    # The WordNet 3.1 licence permits use and redistribution with the
    # copyright notice, but explicitly forbids using Princeton University's
    # name in advertising or publicity relating to distribution of the
    # software without prior written permission -- worth stating here,
    # rather than only on the licence's own page, since this registry is the
    # one place in the codebase that decides how Princeton is credited.
    "wordnet-semcor": _Entry(
        "Princeton WordNet 3.1 — SemCor sense frequencies", "Princeton University",
        "WordNet 3.1 licence", "https://wordnet.princeton.edu/license-and-commercial-use",
        "https://wordnetcode.princeton.edu/wn3.1.dict.tar.gz",
        usage_note="Sense ordering only, not stored as definitions.",
    ),
}


async def sources(session: AsyncSession) -> list[dict]:
    """One row per registry key actually present, each with a live count --
    never a row for a key the database has nothing under, and never a
    fabricated zero. `frequency_source` counts `Lexeme` rows (what those
    lists actually classify); `source_id` counts `LexemeSense` rows (what
    OEWN's definitions actually cover)."""
    rows: list[dict] = []

    freq_stmt = (
        select(Lexeme.frequency_source, func.count(Lexeme.id))
        .where(
            Lexeme.frequency_source.is_not(None),
            Lexeme.frequency_source != "off-list",
        )
        .group_by(Lexeme.frequency_source)
    )
    for key, count in (await session.exec(freq_stmt)).all():
        entry = REGISTRY.get(key)
        if entry is None or count == 0:
            continue
        rows.append({"key": key, "count": count, **entry.__dict__})

    sense_stmt = (
        select(LexemeSense.source_id, func.count(LexemeSense.id))
        .where(LexemeSense.source_id != "model")
        .group_by(LexemeSense.source_id)
    )
    for key, count in (await session.exec(sense_stmt)).all():
        entry = REGISTRY.get(key)
        if entry is None or count == 0:
            continue
        rows.append({"key": key, "count": count, **entry.__dict__})

    # `oewn_rank` counts how many senses were actually ORDERED using
    # Princeton's SemCor tag counts (`LexemeSense.oewn_rank`'s own
    # docstring) -- present only once `scripts/lexicon_cleanup.py
    # wordnet-provenance` (or ordinary enrichment) has written at least one,
    # which is what keeps this entry off the page on a deployment whose
    # senses predate that column.
    wordnet_count = (await session.exec(
        select(func.count(LexemeSense.id)).where(LexemeSense.oewn_rank.is_not(None))
    )).one()
    if wordnet_count:
        entry = REGISTRY["wordnet-semcor"]
        rows.append({"key": "wordnet-semcor", "count": wordnet_count, **entry.__dict__})

    # Registry order (NGSL family, then OEWN, then Princeton), not whatever
    # order SQL's GROUP BY happened to return.
    order = {key: i for i, key in enumerate(REGISTRY)}
    rows.sort(key=lambda r: order.get(r["key"], len(order)))
    return rows
