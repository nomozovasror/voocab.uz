"""Studio dashboard API: aggregate stats for the caller's own authored
content. Auth required; every number is scoped to ``author_id == caller``
(no cross-author leakage) -- see app/services/studio.py for the queries.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser
from app.core.database import AsyncSession, get_session
from app.schemas.studio import ListeningList, StudioStats
from app.services import studio as studio_service

router = APIRouter(prefix="/api", tags=["studio"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/studio/stats", response_model=StudioStats)
async def get_studio_stats(user: CurrentUser, session: SessionDep) -> StudioStats:
    stats = await studio_service.get_stats(session, user.id)
    return StudioStats(**stats)


@router.get("/studio/listening", response_model=ListeningList)
async def get_studio_listening(
    user: CurrentUser, session: SessionDep
) -> ListeningList:
    data = await studio_service.get_listening_list(session, user.id)
    return ListeningList(**data)
