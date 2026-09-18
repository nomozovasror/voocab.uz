"""One paper's learner-facing API, built once and mounted per skill.

Listening and reading are the same exam machinery asked about different
material: a catalogue of public papers, a recommendation with a reason, the
learner's own statistics, and the drills cut out of a paper's question groups.
Everything that differs between them is data — which ``Material.type`` to
filter on, how many parts make a whole paper — and nothing is behaviour.

So this is a FACTORY rather than two routers. ``/api/listening/practice`` and
``/api/reading/practice`` are the same function under two prefixes, which
makes parity structural: a filter added here reaches both papers, and there is
no second copy to forget. The alternative was an ``api/reading.py`` beside
``api/listening.py``, six hundred lines each, identical on the day it was
written and drifting from the first fix applied to one of them.

What is NOT here is everything addressed by a material id rather than by a
skill — ``/materials/{id}/take``, ``/materials/{id}/attempts``,
``/attempts/{id}`` — and that is deliberate. A client holding an id does not
know which router minted it, and should not have to: those endpoints stay
shared in ``app/api/listening.py`` and dispatch on the material's own type.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser
from app.api.materials import _load_owned_or_public, _resolve_audio
from app.core.database import AsyncSession, get_session
from app.models.material import Material
from app.models.part import Part
from app.models.question_group import QuestionGroup
from app.schemas.studio import ListeningList
from app.schemas.listening import (
    AttemptResultOut,
    AttemptSubmit,
    DrillListOut,
    DrillTakeOut,
    DrillTypesOut,
    LastAttemptOut,
    ListeningStatsOut,
    NextUpOut,
    PracticeCatalogueOut,
    PracticeMaterialOut,
)
from app.services import drills as drills_service
from app.services import grading as grading_service
from app.services import learner_stats as learner_stats_service
from app.services import studio as studio_service
from app.services import listening as listening_service
from app.services import recommend as recommend_service

logger = logging.getLogger("app.api.papers")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _load_drillable_group(
    session: SessionDep, group_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[QuestionGroup, Part, Material]:
    """A group the caller may drill, with the part and material behind it.

    Same visibility rule as ``/take`` — anyone who may take the material may
    drill a group of it — plus the group actually being drillable. A group
    whose questions are not all marked has no clip that contains all its
    answers, and a drill that cannot be answered is a 404, not a partial.
    """
    group = await session.get(QuestionGroup, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question group not found")
    part = await session.get(Part, group.part_id)
    if part is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question group not found")
    material = await _load_owned_or_public(session, part.material_id, user_id)
    if await listening_service.group_clip(session, group) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This group cannot be drilled")
    return group, part, material


def paper_router(skill: str) -> APIRouter:
    """The learner-facing endpoints for one paper, under its own prefix.

    ``skill`` is closed over rather than taken as a path parameter. A path
    parameter would accept ``/api/anything/practice`` and answer it with an
    empty catalogue, and would put the job of validating it on every handler;
    a prefix registered for exactly the skills that exist answers 404 for
    everything else, which is what that address is.
    """
    api = APIRouter(prefix="/api", tags=[skill])
    parts = listening_service.full_test_parts(skill)
    # A part chip for each part this paper has, and "full" for all of them.
    scope_pattern = rf"^(all|full|[1-{parts}])$"

    @api.get(f"/{skill}/practice", response_model=PracticeCatalogueOut)
    async def practice_catalogue(
        user: CurrentUser,
        session: SessionDep,
        q: Annotated[str, Query(max_length=200)] = "",
        scope: Annotated[str, Query(pattern=scope_pattern)] = "all",
        types: Annotated[list[str] | None, Query()] = None,
        bands: Annotated[list[str] | None, Query()] = None,
        done: bool = False,
        sort: Annotated[
            str, Query(pattern=r"^(newest|easiest|hardest|shortest)$")
        ] = "newest",
        limit: Annotated[int, Query(ge=1, le=listening_service.CATALOGUE_MAX_PAGE)] = (
            listening_service.CATALOGUE_PAGE
        ),
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> PracticeCatalogueOut:
        """One page of what a learner can sit, and what they have done with it.

        Public materials only; an author reaches their own drafts through the
        Studio. The history in each row is the caller's — an attempt is a record
        of somebody's mistakes, and a catalogue is not where other people's go.

        Every control above the list is a parameter here rather than something
        the browser does afterwards, and that is the whole change: filtering a
        page is filtering thirty rows out of a thousand. ``done`` defaults to
        false — materials the caller has finished are put away unless asked for.

        The enum-shaped parameters are validated by pattern rather than by an
        Enum type on purpose: an unknown ``sort`` is a client bug and deserves a
        422, while ``types`` and ``bands`` are open lists (question types grow
        without a migration — see :class:`QuestionGroupType`) and an unrecognised
        member simply matches nothing.
        """
        page = await listening_service.practice_catalogue(
            session,
            user.id,
            skill=skill,
            query=q.strip(),
            scope=scope,
            types=types,
            bands=bands,
            done=done,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        return PracticeCatalogueOut(
            items=[PracticeMaterialOut(**row) for row in page["items"]],
            total=page["total"],
            done_hidden=page["done_hidden"],
            types=page["types"],
            bands=page["bands"],
        )


    @api.get(f"/{skill}/next", response_model=NextUpOut)
    async def next_up(user: CurrentUser, session: SessionDep) -> NextUpOut:
        """What to practise next, and why.

        Its own request rather than a field on the catalogue, and the reason is
        the same one that keeps the statistics panel separate: the catalogue is
        "what is there", this is "what should I do", and a learner changing a
        filter has not asked the second question again. Bundled together, every
        chip click would recompute a recommendation nobody is looking at.

        Nothing is cached and nothing is stored. It is three rules over numbers
        the platform already has (:mod:`app.services.recommend`), so it is always
        current and there is no stale-suggestion state to reason about.
        """
        return NextUpOut(
            **await recommend_service.next_up(session, user.id, skill=skill),
        )


    @api.get(f"/{skill}/studio", response_model=ListeningList)
    async def studio_list(
        user: CurrentUser, session: SessionDep
    ) -> ListeningList:
        """The author's own table of this paper: every material they have
        written, published or not, with what is in it and how it has gone.

        Under the skill rather than under /studio, because it is one paper's
        list and the studio has one per paper. What stays at /studio is what
        is about the AUTHOR rather than about a paper — the dashboard's
        counters, which span all of them.
        """
        data = await studio_service.get_listening_list(
            session, user.id, skill=skill
        )
        return ListeningList(**data)

    @api.get(f"/{skill}/stats", response_model=ListeningStatsOut)
    async def listening_statistics(
        user: CurrentUser, session: SessionDep
    ) -> ListeningStatsOut:
        """What the caller is good and bad at, from their own answers.

        The caller's own and nobody else's — the same rule the catalogue's history
        column follows, for the same reason. There is no user id in the path, and
        there is deliberately no way to ask for somebody else's: a record of what
        a person keeps getting wrong is theirs.

        Empty is a real answer here rather than a 404. A learner who has never sat
        anything gets zeroes and empty distributions, and the page turns that into
        "start with Part 1" instead of a wall of 0%.
        """
        return ListeningStatsOut(
            **await learner_stats_service.listening_stats(
                session, user.id, skill=skill
            )
        )


    @api.get(f"/{skill}/drills/types", response_model=DrillTypesOut)
    async def drill_types(
        user: CurrentUser,
        session: SessionDep,
        part: Annotated[int | None, Query(ge=1, le=parts)] = None,
    ) -> DrillTypesOut:
        """The Drills tab's cards: every question type, and what there is of it.

        Counted over the whole public library, never over a page — the catalogue's
        rule, for the catalogue's reason. Eleven rows, so it is not paged.
        """
        return DrillTypesOut(
            items=await drills_service.type_summary(
                session, user.id, skill=skill, part=part
            )
        )


    @api.get(f"/{skill}/drills", response_model=DrillListOut)
    async def list_drills(
        user: CurrentUser,
        session: SessionDep,
        type: Annotated[list[str], Query(max_length=64)],
        q: Annotated[str | None, Query(max_length=200)] = None,
        part: Annotated[int | None, Query(ge=1, le=parts)] = None,
        done: Annotated[bool, Query()] = False,
        limit: Annotated[int, Query(ge=1, le=100)] = drills_service.DRILL_PAGE,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> DrillListOut:
        """One page of drills of a given type.

        ``type`` repeats, because a card on the tab can cover more than one kind:
        map and diagram labelling are the same task on two kinds of picture. Open
        strings for the same reason the catalogue's are — the question types grow
        without a migration, and one we do not recognise simply matches nothing.
        """
        return DrillListOut(
            **await drills_service.list_drills(
                session,
                user.id,
                skill=skill,
                group_types=type,
                query=q,
                part=part,
                done=done,
                limit=limit,
                offset=offset,
            )
        )


    @api.get(f"/{skill}/drills/{{group_id}}", response_model=DrillTakeOut)
    async def take_drill(
        group_id: uuid.UUID, user: CurrentUser, session: SessionDep
    ) -> DrillTakeOut:
        """One drill's render payload.

        The same guarantee ``/take`` carries, by the same two independent means:
        built from ``get_drill_tree`` (which never reads
        ``Question.correct_answers``) and validated against a schema whose nested
        question type has no such field at all.
        """
        group, part, material = await _load_drillable_group(session, group_id, user.id)
        audio = await _resolve_audio(session, material)
        clip = await listening_service.group_clip(
            session, group, duration_ms=audio["duration_ms"]
        )
        parts = await listening_service.get_drill_tree(session, group)
        done = await grading_service.last_submitted_attempt(
            session, user.id, material.id, group_id=group.id
        )
        return DrillTakeOut(
            id=group.id,
            title=material.title,
            audio_url=audio["audio_url"],
            duration_ms=audio["duration_ms"],
            parts=parts,
            clip_start_ms=clip["start_ms"],
            clip_end_ms=clip["end_ms"],
            drill=await drills_service.drill_row(
                session, user.id, group, material, part
            ),
            last_attempt=(
                LastAttemptOut(
                    attempt_id=done.id,
                    score=int(done.score or 0),
                    total_questions=done.total_questions or 0,
                    submitted_at=done.submitted_at,
                )
                if done is not None and done.submitted_at is not None
                else None
            ),
        )


    @api.post(f"/{skill}/drills/{{group_id}}/attempts", response_model=AttemptResultOut)
    async def submit_drill(
        group_id: uuid.UUID,
        data: AttemptSubmit,
        user: CurrentUser,
        session: SessionDep,
    ) -> AttemptResultOut:
        """Submit + grade one drill.

        No ``refresh_if_unrated`` here, and that is deliberate rather than an
        omission: a drill does not feed the material difficulty tally
        (``difficulty._tally`` excludes it), so refreshing the band after one
        would be a write that recomputes the same number. This line gets copied,
        so it says why it is missing.
        """
        group, part, material = await _load_drillable_group(session, group_id, user.id)
        attempt = await grading_service.submit_drill(
            session,
            user_id=user.id,
            group=group,
            material_id=material.id,
            data=data,
        )
        return AttemptResultOut.model_validate(
            await grading_service.attempt_result(session, attempt)
        )

    return api
