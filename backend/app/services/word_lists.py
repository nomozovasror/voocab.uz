"""Word lists: what a learner sees of them, and what they feed the session.

See ``backend/app/services/CLAUDE.md``, "Word lists", for the rules this
module keeps (subscribing is not adding; the sense is the list's; owning a
sense is owning it whatever its origin).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import exists, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import select

from app.core.database import AsyncSession
from app.models.lexicon import Lexeme, LexemeSense
from app.models.vocabulary import SavedWord
from app.models.word_list import UserWordList, WordList, WordListEntry

CEFR_LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")
SAMPLE_COUNT = 12

#: Namespace for the id a list word will have once it exists. Deterministic,
#: so the options built for an item before the word exists grade correctly
#: after it does (``distractors.option_id`` hashes the word id).
_LIST_WORD_NAMESPACE = uuid.UUID("5d1a3f0e-7b64-4c2a-9a38-0c6f2b8e41d7")


def list_word_id(user_id: uuid.UUID, sense_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(_LIST_WORD_NAMESPACE, f"{user_id}:{sense_id}")


def _owned_clause(user_id: uuid.UUID):
    """The learner owns this entry's sense, by any route."""
    return exists(
        select(SavedWord.id).where(
            SavedWord.user_id == user_id,
            SavedWord.lexeme_sense_id == WordListEntry.sense_id,
        )
    )


def _not_vocabulary_clause():
    """A proper noun or function word is never offered (or counted)."""
    return ~exists(
        select(Lexeme.id)
        .join(LexemeSense, LexemeSense.lexeme_id == Lexeme.id)
        .where(
            LexemeSense.id == WordListEntry.sense_id,
            (Lexeme.is_proper_noun.is_(True)) | (Lexeme.is_function_word.is_(True)),
        )
    )


# --- Reading lists --------------------------------------------------------------


async def _get_list(session: AsyncSession, key: str) -> WordList:
    found = (
        await session.exec(select(WordList).where(WordList.key == key))
    ).first()
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such word list")
    return found


async def _counts(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[uuid.UUID, tuple[int, int]]:
    """``{list_id: (word_count, owned)}`` -- entries with a sense, and the
    ones whose sense the learner has as a saved word."""
    rows = await session.exec(
        select(
            WordListEntry.list_id,
            func.count(),
            func.count().filter(_owned_clause(user_id)),
        )
        .where(WordListEntry.sense_id.is_not(None), _not_vocabulary_clause())
        .group_by(WordListEntry.list_id)
    )
    return {list_id: (total, owned) for list_id, total, owned in rows.all()}


async def _memberships(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[uuid.UUID, UserWordList]:
    rows = await session.exec(
        select(UserWordList).where(UserWordList.user_id == user_id)
    )
    return {row.list_id: row for row in rows.all()}


def _head(
    word_list: WordList,
    counts: dict[uuid.UUID, tuple[int, int]],
    memberships: dict[uuid.UUID, UserWordList],
) -> dict:
    total, owned = counts.get(word_list.id, (0, 0))
    membership = memberships.get(word_list.id)
    return {
        "key": word_list.key,
        "title": word_list.title,
        "description": word_list.description,
        "word_count": total,
        "owned": owned,
        "active": bool(membership and membership.active),
        "started": membership is not None,
    }


async def list_all(session: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    lists = (
        await session.exec(select(WordList).order_by(WordList.sort_order, WordList.key))
    ).all()
    counts = await _counts(session, user_id)
    memberships = await _memberships(session, user_id)
    return [_head(word_list, counts, memberships) for word_list in lists]


def _spread(ranked_ids: list[uuid.UUID], count: int) -> list[uuid.UUID]:
    """``count`` ids evenly spread over an already rank-ordered list, each
    taken from the middle of its stretch."""
    total = len(ranked_ids)
    if total <= count:
        return ranked_ids
    return [ranked_ids[int((i + 0.5) * total / count)] for i in range(count)]


async def detail(
    session: AsyncSession, user_id: uuid.UUID, key: str, *, pending_saved: int
) -> dict:
    word_list = await _get_list(session, key)
    counts = await _counts(session, user_id)
    memberships = await _memberships(session, user_id)
    head = _head(word_list, counts, memberships)

    cefr_rows = await session.exec(
        select(LexemeSense.cefr, func.count())
        .select_from(WordListEntry)
        .join(LexemeSense, LexemeSense.id == WordListEntry.sense_id)
        .where(WordListEntry.list_id == word_list.id, _not_vocabulary_clause())
        .group_by(LexemeSense.cefr)
    )
    cefr = {level: 0 for level in CEFR_LEVELS}
    cefr["unrated"] = 0
    for level, number in cefr_rows.all():
        cefr[level if level in CEFR_LEVELS else "unrated"] += number

    ranked = (
        await session.exec(
            select(WordListEntry.id)
            .where(
                WordListEntry.list_id == word_list.id,
                WordListEntry.sense_id.is_not(None),
                _not_vocabulary_clause(),
            )
            .order_by(WordListEntry.rank)
        )
    ).all()
    picked = _spread(list(ranked), SAMPLE_COUNT)
    samples: list[dict] = []
    if picked:
        rows = await session.exec(
            select(WordListEntry, LexemeSense, Lexeme)
            .join(LexemeSense, LexemeSense.id == WordListEntry.sense_id)
            .join(Lexeme, Lexeme.id == LexemeSense.lexeme_id)
            .where(WordListEntry.id.in_(picked))
            .order_by(WordListEntry.rank)
        )
        for entry, sense, lexeme in rows.all():
            samples.append(
                {
                    "lemma": lexeme.lemma,
                    "pos": lexeme.pos,
                    "cefr": sense.cefr if sense.cefr in CEFR_LEVELS else None,
                    "definition_en": sense.definition_en,
                    "meaning_uz": sense.meaning_uz,
                }
            )

    return {
        **head,
        "cefr": cefr,
        "samples": samples,
        "attribution": word_list.attribution,
        "source_title": word_list.source_title,
        "licence_name": word_list.licence_name,
        "licence_url": word_list.licence_url,
        "pending_saved": pending_saved,
    }


# --- Starting and stopping ------------------------------------------------------


async def start(session: AsyncSession, user_id: uuid.UUID, key: str) -> None:
    """Subscribe. Writes ONE ``user_word_lists`` row and nothing else --
    no saved word exists for any entry until the learner answers it."""
    word_list = await _get_list(session, key)
    # One atomic upsert: two concurrent Starts must not race a get-then-insert
    # into a primary-key IntegrityError.
    await session.execute(
        pg_insert(UserWordList)
        .values(
            user_id=user_id, list_id=word_list.id,
            added_at=datetime.now(timezone.utc), active=True,
        )
        .on_conflict_do_update(
            index_elements=[UserWordList.user_id, UserWordList.list_id],
            set_={"active": True},
        )
    )
    await session.commit()


async def stop(session: AsyncSession, user_id: uuid.UUID, key: str) -> None:
    """Unsubscribe. Owned words stay; unpresented entries stop coming."""
    word_list = await _get_list(session, key)
    membership = await session.get(UserWordList, (user_id, word_list.id))
    if membership is not None and membership.active:
        membership.active = False
        session.add(membership)
        await session.commit()


# --- Feeding the session --------------------------------------------------------


@dataclass
class ListCandidate:
    entry: WordListEntry
    sense: LexemeSense
    lexeme: Lexeme


async def next_candidates(
    session: AsyncSession, user_id: uuid.UUID, limit: int
) -> list[ListCandidate]:
    """Up to ``limit`` entries to offer as new words: round-robin over the
    learner's ACTIVE lists, each in rank order, skipping any sense already
    owned or already taken by another list in this batch. A list that runs dry
    gives its turns to the others.

    Which list goes first rotates with the number of words the learner has
    taken from lists so far (durable, deterministic): with one new slot a day
    the lists take turns instead of the earliest-started one always winning."""
    if limit <= 0:
        return []
    active = (
        await session.exec(
            select(UserWordList.list_id)
            .where(UserWordList.user_id == user_id, UserWordList.active.is_(True))
            .order_by(UserWordList.added_at, UserWordList.list_id)
        )
    ).all()
    if not active:
        return []
    taken_from_lists = (
        await session.exec(
            select(func.count()).select_from(SavedWord).where(
                SavedWord.user_id == user_id, SavedWord.origin_list_id.is_not(None)
            )
        )
    ).one()
    turn = taken_from_lists % len(active)
    active = list(active[turn:]) + list(active[:turn])

    # Each list may have to cover every slot, plus however many of its
    # leading entries another list takes first.
    per_list = limit * len(active)
    queues: list[list[ListCandidate]] = []
    for list_id in active:
        rows = await session.exec(
            select(WordListEntry, LexemeSense, Lexeme)
            .join(LexemeSense, LexemeSense.id == WordListEntry.sense_id)
            .join(Lexeme, Lexeme.id == LexemeSense.lexeme_id)
            .where(
                WordListEntry.list_id == list_id,
                ~_owned_clause(user_id),
                Lexeme.is_proper_noun.is_(False),
                Lexeme.is_function_word.is_(False),
            )
            .order_by(WordListEntry.rank)
            .limit(per_list)
        )
        queues.append(
            [ListCandidate(e, s, x) for e, s, x in rows.all()]
        )

    taken: set[uuid.UUID] = set()
    picked: list[ListCandidate] = []
    cursors = [0] * len(queues)
    while len(picked) < limit:
        progressed = False
        for index, queue in enumerate(queues):
            if len(picked) >= limit:
                break
            while cursors[index] < len(queue):
                candidate = queue[cursors[index]]
                cursors[index] += 1
                if candidate.sense.id in taken:
                    continue
                taken.add(candidate.sense.id)
                picked.append(candidate)
                progressed = True
                break
        if not progressed:
            break
    return picked


async def entry_for_answer(
    session: AsyncSession, user_id: uuid.UUID, entry_id: uuid.UUID
) -> ListCandidate:
    """The server-side gate for answering a list item. 404 unknown entry;
    403 when its list is not an ACTIVE one of this learner's; 409 when the
    learner already owns the sense (the client should continue with that
    word's own id)."""
    row = (
        await session.exec(
            select(WordListEntry, LexemeSense, Lexeme)
            .join(LexemeSense, LexemeSense.id == WordListEntry.sense_id)
            .join(Lexeme, Lexeme.id == LexemeSense.lexeme_id)
            .where(WordListEntry.id == entry_id)
        )
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such list entry")
    entry, sense, lexeme = row
    membership = await session.get(UserWordList, (user_id, entry.list_id))
    if membership is None or not membership.active:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "That word's list is not active for you"
        )
    if lexeme.is_proper_noun or lexeme.is_function_word:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such list entry")
    owned = (
        await session.exec(
            select(SavedWord.id).where(
                SavedWord.user_id == user_id, SavedWord.lexeme_sense_id == sense.id
            )
        )
    ).first()
    if owned is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have this word on your list"
        )
    return ListCandidate(entry, sense, lexeme)


def transient_word(user_id: uuid.UUID, candidate: ListCandidate) -> SavedWord:
    """The word an entry WILL become, built but never added to a session.
    Its id is the one the real row is created with."""
    return SavedWord(
        id=list_word_id(user_id, candidate.sense.id),
        user_id=user_id,
        lemma=candidate.lexeme.lemma,
        pos=candidate.lexeme.pos,
        lexeme_sense_id=candidate.sense.id,
        origin_list_id=candidate.entry.list_id,
    )
