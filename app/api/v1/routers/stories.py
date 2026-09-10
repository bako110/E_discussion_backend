"""Router stories — publication, feed, vues, reactions, reponses."""
from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import Message
from app.schemas.conversation import MessageOut
from app.schemas.story import (
    StoryAudienceIn,
    StoryAudienceOut,
    StoryCreate,
    StoryFeedItem,
    StoryOut,
    StoryReactionIn,
    StoryReplyIn,
    StoryUpdate,
    StoryViewerOut,
)
from app.services import story_service

router = APIRouter()


@router.get("/feed", response_model=list[StoryFeedItem])
async def get_feed(current_user: CurrentUser, db: DbSession):
    """Stories des contacts, groupees par auteur."""
    return await story_service.feed(db, current_user)


@router.get("/audience", response_model=StoryAudienceOut)
async def get_audience(current_user: CurrentUser, db: DbSession):
    """Confidentialité des statuts (mode + contacts listés)."""
    return await story_service.get_audience(db, current_user)


@router.put("/audience", response_model=StoryAudienceOut)
async def set_audience(body: StoryAudienceIn, current_user: CurrentUser, db: DbSession):
    return await story_service.set_audience(
        db, current_user, body.mode, body.contact_ids
    )


@router.get("/mine", response_model=list[StoryOut])
async def get_mine(current_user: CurrentUser, db: DbSession):
    return await story_service.my_stories(db, current_user)


@router.post("", response_model=StoryOut, status_code=201)
async def publish(body: StoryCreate, current_user: CurrentUser, db: DbSession):
    return await story_service.create_story(db, current_user, body)


@router.patch("/{story_id}", response_model=StoryOut)
async def edit(
    story_id: uuid.UUID, body: StoryUpdate, current_user: CurrentUser, db: DbSession
):
    return await story_service.update_story(db, current_user, story_id, body)


@router.delete("/{story_id}", response_model=Message)
async def remove(story_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await story_service.delete_story(db, current_user, story_id)
    return Message(message="deleted")


@router.post("/{story_id}/view", response_model=Message)
async def view(story_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await story_service.mark_viewed(db, current_user, story_id)
    return Message(message="ok")


@router.get("/{story_id}/viewers", response_model=list[StoryViewerOut])
async def get_viewers(story_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    """Liste des personnes ayant vu ma story (auteur uniquement)."""
    return await story_service.viewers(db, current_user, story_id)


@router.post("/{story_id}/react", response_model=Message)
async def react(
    story_id: uuid.UUID, body: StoryReactionIn, current_user: CurrentUser, db: DbSession
):
    await story_service.react(db, current_user, story_id, body.emoji)
    return Message(message="ok")


@router.delete("/{story_id}/react", response_model=Message)
async def unreact(story_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await story_service.react(db, current_user, story_id, None)
    return Message(message="ok")


@router.post("/{story_id}/reply", response_model=MessageOut, status_code=201)
async def reply(
    story_id: uuid.UUID, body: StoryReplyIn, current_user: CurrentUser, db: DbSession
):
    """Repond a une story : cree un message dans la conversation avec
    l'auteur et le lui pousse en temps reel."""
    from app.services import message_service

    msg = await story_service.reply(db, current_user, story_id, body)
    return await message_service._serialize(db, msg, viewer_id=current_user.id)  # noqa: SLF001
