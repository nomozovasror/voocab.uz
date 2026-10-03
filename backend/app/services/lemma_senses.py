"""Every sense we hold for a word -- what the lookup popover and the word
page list ("lookup shows every sense"). Rules live in
`app/services/CLAUDE.md`, "Every sense of the word"; this is the mechanism.

One batched query per request, whatever the number of entries: the lexemes
of every asked-about lemma and their senses come back in a single SELECT
(the lemma set is a subquery over the anchor lexeme ids), and ordering,
labels and marks are computed in Python from that one result.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlmodel import select

from app.core.database import AsyncSession
from app.models.lexicon import Lexeme, LexemeSense

#: Tie order between parts of speech, the same as `lexicon_enrich.POS_PRIORITY`
#: (not imported: that module loads the OEWN extract machinery).
_POS_ORDER = ("n", "v", "adj", "adv")

MOST_COMMON = "most common"
COMMON = "common"
LESS_COMMON = "less common"

#: A sense is `common` when its SemCor count is at least this share of the
#: word's top count. Compared as `count * DENOM >= top * NUM` -- integers only.
COMMON_SHARE = (1, 4)


@dataclass(frozen=True)
class SenseView:
    sense_id: uuid.UUID
    pos: str
    definition_en: str
    meaning_uz: str
    cefr: str | None
    label: str | None
    #: True for the sense the anchor named (the material row's sense in the
    #: lookup; the learner's saved sense on the word page).
    anchor: bool


def label_for(count: int | None, top: int | None) -> str | None:
    """`None` whenever there is no SemCor data to compare: the sense has no
    count (a model sense, or not yet backfilled) or the word has no tagged
    sense at all (top 0 -- every count is 0, nothing separates them)."""
    if count is None or not top:
        return None
    if count >= top:
        return MOST_COMMON
    if count * COMMON_SHARE[1] >= top * COMMON_SHARE[0]:
        return COMMON
    return LESS_COMMON


def _sense_key(s: LexemeSense) -> tuple[bool, int, int, int]:
    # Senses with SemCor data first, by COUNT desc (rank is file order, with
    # capitalised entries appended, so it can put a high-count sense below
    # count-0 ones); rank breaks ties; then ours (by sense_rank).
    return (s.oewn_count is None, -(s.oewn_count or 0), s.oewn_rank or 0, s.sense_rank)


def _pos_key(pos: str) -> tuple[int, str]:
    return (_POS_ORDER.index(pos) if pos in _POS_ORDER else len(_POS_ORDER), pos)


def arrange(
    rows: list[tuple[Lexeme, LexemeSense]],
    *,
    anchor_lexeme_id: uuid.UUID,
    anchor_sense_id: uuid.UUID | None,
) -> list[SenseView]:
    """Order and label one lemma's senses (``rows`` are only that lemma's).

    The anchor sense first overall; then the anchor lexeme's POS group, then
    the other groups (best-attested first); inside a group SemCor-counted
    senses by count (rank breaks ties), the rest by our `sense_rank`.
    """
    usable = [(lx, s) for lx, s in rows if s.definition_en.strip() or s.meaning_uz.strip()]
    top = max((s.oewn_count or 0 for _, s in usable if s.oewn_count is not None), default=0)

    groups: dict[uuid.UUID, list[tuple[Lexeme, LexemeSense]]] = {}
    for lx, s in usable:
        groups.setdefault(lx.id, []).append((lx, s))

    def group_key(item: tuple[uuid.UUID, list[tuple[Lexeme, LexemeSense]]]):
        lexeme_id, members = item
        best = max((s.oewn_count or 0 for _, s in members if s.oewn_count is not None), default=0)
        return (lexeme_id != anchor_lexeme_id, -best, _pos_key(members[0][0].pos), str(lexeme_id))

    ordered: list[SenseView] = []
    for _, members in sorted(groups.items(), key=group_key):
        for lx, s in sorted(members, key=lambda m: _sense_key(m[1])):
            ordered.append(SenseView(
                sense_id=s.id, pos=lx.pos, definition_en=s.definition_en,
                meaning_uz=s.meaning_uz, cefr=s.cefr,
                label=label_for(s.oewn_count, top),
                anchor=anchor_sense_id is not None and s.id == anchor_sense_id,
            ))
    # Stable: the anchor moves to the front, the rest keep their order.
    return sorted(ordered, key=lambda v: not v.anchor)


async def senses_for(
    session: AsyncSession,
    anchors: list[tuple[uuid.UUID | None, uuid.UUID | None]],
) -> list[list[SenseView]]:
    """For each ``(lexeme_id, anchor_sense_id)``: every sense of that
    lexeme's lemma across its parts of speech, arranged by :func:`arrange`.
    Result is parallel to ``anchors``. Proper-noun and function-word
    lexemes contribute nothing (the anchor's own included). ONE query."""
    lexeme_ids = {lexeme_id for lexeme_id, _ in anchors if lexeme_id is not None}
    if not lexeme_ids:
        return [[] for _ in anchors]
    lemmas = select(Lexeme.lemma).where(Lexeme.id.in_(lexeme_ids))
    result = await session.exec(
        select(Lexeme, LexemeSense)
        .join(LexemeSense, LexemeSense.lexeme_id == Lexeme.id)
        .where(
            Lexeme.lemma.in_(lemmas),
            Lexeme.is_proper_noun.is_(False),
            Lexeme.is_function_word.is_(False),
        )
    )
    by_lemma: dict[str, list[tuple[Lexeme, LexemeSense]]] = {}
    lemma_of: dict[uuid.UUID, str] = {}
    for lexeme, sense in result.all():
        by_lemma.setdefault(lexeme.lemma, []).append((lexeme, sense))
        lemma_of[lexeme.id] = lexeme.lemma

    out: list[list[SenseView]] = []
    for lexeme_id, sense_id in anchors:
        lemma = lemma_of.get(lexeme_id) if lexeme_id is not None else None
        if lemma is None:
            out.append([])
            continue
        out.append(arrange(by_lemma[lemma], anchor_lexeme_id=lexeme_id, anchor_sense_id=sense_id))
    return out
