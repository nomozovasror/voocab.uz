"""Word lists: browse them, start one, stop one.

Starting writes one `user_word_lists` row and nothing else -- see
`app.services.word_lists`. What the lists feed into the daily session is
`app.services.practice`'s business.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser
from app.core.database import AsyncSession, get_session
from app.schemas.vocabulary import (
    WordListDetailOut,
    WordListOut,
    WordListStartOut,
    WordListStopOut,
)
from app.services import practice as practice_service
from app.services import word_lists as word_lists_service

SessionDep = Annotated[AsyncSession, Depends(get_session)]

router = APIRouter(prefix="/api", tags=["vocabulary"])


@router.get("/vocabulary/lists", response_model=list[WordListOut])
async def list_word_lists(user: CurrentUser, session: SessionDep) -> list[dict]:
    return await word_lists_service.list_all(session, user.id)


@router.get("/vocabulary/lists/{key}", response_model=WordListDetailOut)
async def word_list_detail(key: str, user: CurrentUser, session: SessionDep) -> dict:
    pending = await practice_service.count_new_saved(session, user.id)
    return await word_lists_service.detail(session, user.id, key, pending_saved=pending)


@router.post("/vocabulary/lists/{key}/start", response_model=WordListStartOut)
async def start_word_list(
    key: str, user: CurrentUser, session: SessionDep
) -> WordListStartOut:
    await word_lists_service.start(session, user.id, key)
    return WordListStartOut(
        pending_saved=await practice_service.count_new_saved(session, user.id)
    )


@router.post("/vocabulary/lists/{key}/stop", response_model=WordListStopOut)
async def stop_word_list(
    key: str, user: CurrentUser, session: SessionDep
) -> WordListStopOut:
    await word_lists_service.stop(session, user.id, key)
    return WordListStopOut()
