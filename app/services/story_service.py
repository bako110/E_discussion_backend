"""Stories — publication, feed, vues, reactions, reponses (-> messages).

Regles de visibilite (v1) : une story est visible par les personnes avec qui
l'auteur a deja une conversation (dans les deux sens). Simple et suffisant
pour du 1-to-1 ; on pourra ajouter des listes d'audience ensuite.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.db.models.conversation import Conversation
from app.db.models.message import Message, MessageType
from app.db.models.story import Story, StoryAudienceEntry, StoryReaction, StoryView
from app.db.models.user import User
from app.schemas.story import (
    StoryCreate,
    StoryFeedItem,
    StoryOut,
    StoryReplyIn,
    StoryUpdate,
    StoryViewerOut,
)
from app.services import conversation_service, user_service
from app.services.ws_manager import manager

STORY_TTL_HOURS = 24


# ── helpers ────────────────────────────────────────────────────────────────
async def _contact_ids(db: AsyncSession, me_id: uuid.UUID) -> set[uuid.UUID]:
    rows = (
        await db.execute(
            select(Conversation.user_a_id, Conversation.user_b_id).where(
                or_(Conversation.user_a_id == me_id, Conversation.user_b_id == me_id)
            )
        )
    ).all()
    ids: set[uuid.UUID] = set()
    for a, b in rows:
        ids.add(b if a == me_id else a)
    return ids


async def _audience_list(db: AsyncSession, owner_id: uuid.UUID) -> set[uuid.UUID]:
    """Contacts listés pour la confidentialité des statuts de `owner`."""
    rows = (
        await db.execute(
            select(StoryAudienceEntry.target_id).where(
                StoryAudienceEntry.owner_id == owner_id
            )
        )
    ).scalars().all()
    return set(rows)


async def _story_audience_ids(db: AsyncSession, author: User) -> set[uuid.UUID]:
    """Ensemble des utilisateurs autorisés à voir les statuts de `author`,
    évalué MAINTENANT (façon WhatsApp).

    - `contacts`         -> tous les contacts,
    - `contacts_except`  -> contacts moins la liste,
    - `only`             -> intersection(contacts, liste).
    """
    contacts = await _contact_ids(db, author.id)
    mode = getattr(author, "story_audience_mode", "contacts") or "contacts"
    if mode == "contacts":
        return contacts
    listed = await _audience_list(db, author.id)
    if mode == "contacts_except":
        return contacts - listed
    if mode == "only":
        return contacts & listed
    return contacts


async def _can_view_stories(db: AsyncSession, author: User, viewer_id: uuid.UUID) -> bool:
    if author.id == viewer_id:
        return True
    return viewer_id in await _story_audience_ids(db, author)


async def _serialize(
    db: AsyncSession, s: Story, *, me_id: uuid.UUID
) -> StoryOut:
    views = await db.scalar(
        select(func.count()).select_from(StoryView).where(StoryView.story_id == s.id)
    )
    reactions = await db.scalar(
        select(func.count()).select_from(StoryReaction).where(StoryReaction.story_id == s.id)
    )
    seen = await db.scalar(
        select(func.count())
        .select_from(StoryView)
        .where(StoryView.story_id == s.id, StoryView.viewer_id == me_id)
    )
    my_reaction = await db.scalar(
        select(StoryReaction.emoji).where(
            StoryReaction.story_id == s.id, StoryReaction.user_id == me_id
        )
    )
    out = StoryOut.model_validate(s)
    out.view_count = int(views or 0)
    out.reaction_count = int(reactions or 0)
    out.seen_by_me = bool(seen)
    out.my_reaction = my_reaction
    out.is_mine = s.author_id == me_id
    return out


def _active_filter():
    now = datetime.now(UTC)
    return and_(Story.deleted_at.is_(None), Story.expires_at > now)


# ── publication ────────────────────────────────────────────────────────────
async def create_story(db: AsyncSession, me: User, data: StoryCreate) -> StoryOut:
    now = datetime.now(UTC)
    story = Story(
        author_id=me.id,
        media_type=data.media_type,
        media_url=data.media_url,
        caption=data.caption,
        background_color=data.background_color,
        font=data.font,
        duration_sec=data.duration_sec,
        thumbnail_url=data.thumbnail_url,
        audio_url=data.audio_url,
        audio_name=data.audio_name,
        audience=data.audience,
        expires_at=now + timedelta(hours=STORY_TTL_HOURS),
    )
    db.add(story)
    await db.flush()

    # notifier uniquement l'audience autorisee (event WS leger)
    for cid in await _story_audience_ids(db, me):
        await manager.send_to_user(
            str(cid),
            {"type": "story.new", "author_id": str(me.id), "story_id": str(story.id)},
        )
    return await _serialize(db, story, me_id=me.id)


async def update_story(
    db: AsyncSession, me: User, story_id: uuid.UUID, data: StoryUpdate
) -> StoryOut:
    story = await db.get(Story, story_id)
    if story is None or story.deleted_at is not None:
        raise NotFoundError("story.not_found", code="story_not_found")
    if story.author_id != me.id:
        raise ForbiddenError("story.not_owner", code="not_owner")

    patch = data.model_dump(exclude_unset=True)
    for field, value in patch.items():
        setattr(story, field, value)
    story.edited_at = datetime.now(UTC)
    await db.flush()

    for cid in await _story_audience_ids(db, me):
        await manager.send_to_user(
            str(cid),
            {"type": "story.updated", "author_id": str(me.id), "story_id": str(story.id)},
        )
    return await _serialize(db, story, me_id=me.id)


async def delete_story(db: AsyncSession, me: User, story_id: uuid.UUID) -> None:
    story = await db.get(Story, story_id)
    if story is None or story.deleted_at is not None:
        raise NotFoundError("story.not_found", code="story_not_found")
    if story.author_id != me.id:
        raise ForbiddenError("story.not_owner", code="not_owner")
    story.deleted_at = datetime.now(UTC)
    await db.flush()

    for cid in await _story_audience_ids(db, me):
        await manager.send_to_user(
            str(cid),
            {"type": "story.deleted", "author_id": str(me.id), "story_id": str(story.id)},
        )


# ── lecture ────────────────────────────────────────────────────────────────
async def my_stories(db: AsyncSession, me: User) -> list[StoryOut]:
    rows = (
        await db.execute(
            select(Story)
            .where(Story.author_id == me.id, _active_filter())
            .order_by(Story.created_at)
        )
    ).scalars().all()
    return [await _serialize(db, s, me_id=me.id) for s in rows]


async def feed(db: AsyncSession, me: User) -> list[StoryFeedItem]:
    """Stories des contacts, groupees par auteur, plus recentes d'abord."""
    contact_ids = await _contact_ids(db, me.id)
    if not contact_ids:
        return []

    rows = (
        await db.execute(
            select(Story)
            .where(Story.author_id.in_(contact_ids), _active_filter())
            .order_by(Story.author_id, Story.created_at)
        )
    ).scalars().all()
    if not rows:
        return []

    by_author: dict[uuid.UUID, list[Story]] = {}
    for s in rows:
        by_author.setdefault(s.author_id, []).append(s)

    authors = {
        u.id: u
        for u in (
            await db.execute(select(User).where(User.id.in_(by_author.keys())))
        ).scalars().all()
    }

    items: list[StoryFeedItem] = []
    for author_id, stories in by_author.items():
        author = authors.get(author_id)
        if author is None:
            continue
        # confidentialite des statuts de l'auteur (evaluee maintenant)
        if not await _can_view_stories(db, author, me.id):
            continue
        serialized = [await _serialize(db, s, me_id=me.id) for s in stories]
        items.append(
            StoryFeedItem(
                author=await user_service.serialize_public(author),
                stories=serialized,
                has_unseen=any(not s.seen_by_me for s in serialized),
                latest_at=max(s.created_at for s in stories),
            )
        )
    items.sort(key=lambda it: it.latest_at, reverse=True)
    return items


async def _get_visible(db: AsyncSession, me: User, story_id: uuid.UUID) -> Story:
    story = await db.get(Story, story_id)
    if story is None or story.deleted_at is not None or story.expires_at <= datetime.now(UTC):
        raise NotFoundError("story.not_found", code="story_not_found")
    if story.author_id != me.id:
        author = await db.get(User, story.author_id)
        if author is None or not await _can_view_stories(db, author, me.id):
            raise ForbiddenError("story.not_visible", code="not_visible")
    return story


# ── confidentialite des statuts ───────────────────────────────────────────
_VALID_MODES = {"contacts", "contacts_except", "only"}


async def get_audience(db: AsyncSession, me: User) -> dict:
    return {
        "mode": getattr(me, "story_audience_mode", "contacts") or "contacts",
        "contact_ids": [str(x) for x in await _audience_list(db, me.id)],
    }


async def set_audience(
    db: AsyncSession, me: User, mode: str, contact_ids: list[uuid.UUID]
) -> dict:
    if mode not in _VALID_MODES:
        raise ForbiddenError("story.bad_mode", code="bad_mode")
    me.story_audience_mode = mode

    # on ne garde dans la liste que de vrais contacts
    contacts = await _contact_ids(db, me.id)
    wanted = {c for c in contact_ids if c in contacts} if mode != "contacts" else set()

    current = await _audience_list(db, me.id)
    to_add = wanted - current
    to_del = current - wanted
    if to_del:
        await db.execute(
            StoryAudienceEntry.__table__.delete().where(
                StoryAudienceEntry.owner_id == me.id,
                StoryAudienceEntry.target_id.in_(to_del),
            )
        )
    for tid in to_add:
        db.add(StoryAudienceEntry(owner_id=me.id, target_id=tid))
    await db.flush()
    return {"mode": mode, "contact_ids": [str(x) for x in wanted]}


# ── vues ───────────────────────────────────────────────────────────────────
async def mark_viewed(db: AsyncSession, me: User, story_id: uuid.UUID) -> None:
    story = await _get_visible(db, me, story_id)
    if story.author_id == me.id:
        return  # l'auteur ne "voit" pas sa propre story
    exists = await db.scalar(
        select(StoryView.id).where(
            StoryView.story_id == story_id, StoryView.viewer_id == me.id
        )
    )
    if exists:
        return
    db.add(StoryView(story_id=story_id, viewer_id=me.id))
    await db.flush()
    await manager.send_to_user(
        str(story.author_id),
        {"type": "story.viewed", "story_id": str(story_id), "viewer_id": str(me.id)},
    )


async def viewers(db: AsyncSession, me: User, story_id: uuid.UUID) -> list[StoryViewerOut]:
    story = await db.get(Story, story_id)
    if story is None or story.author_id != me.id:
        raise ForbiddenError("story.not_owner", code="not_owner")

    rows = (
        await db.execute(
            select(StoryView, User)
            .join(User, User.id == StoryView.viewer_id)
            .where(StoryView.story_id == story_id)
            .order_by(StoryView.created_at.desc())
        )
    ).all()
    reactions = {
        uid: emoji
        for uid, emoji in (
            await db.execute(
                select(StoryReaction.user_id, StoryReaction.emoji).where(
                    StoryReaction.story_id == story_id
                )
            )
        ).all()
    }
    return [
        StoryViewerOut(
            user=await user_service.serialize_public(u),
            viewed_at=v.created_at,
            reaction=reactions.get(u.id),
        )
        for v, u in rows
    ]


# ── reactions ──────────────────────────────────────────────────────────────
async def react(
    db: AsyncSession, me: User, story_id: uuid.UUID, emoji: str | None
) -> None:
    story = await _get_visible(db, me, story_id)
    row = await db.scalar(
        select(StoryReaction).where(
            StoryReaction.story_id == story_id, StoryReaction.user_id == me.id
        )
    )
    if emoji is None:
        if row:
            await db.delete(row)
    elif row:
        row.emoji = emoji
    else:
        db.add(StoryReaction(story_id=story_id, user_id=me.id, emoji=emoji))
    await db.flush()

    if story.author_id != me.id:
        await manager.send_to_user(
            str(story.author_id),
            {
                "type": "story.reaction",
                "story_id": str(story_id),
                "user_id": str(me.id),
                "emoji": emoji,
            },
        )


# ── reponse -> message dans la conversation ────────────────────────────────
async def reply(
    db: AsyncSession, me: User, story_id: uuid.UUID, data: StoryReplyIn
) -> Message:
    story = await _get_visible(db, me, story_id)
    if story.author_id == me.id:
        raise ForbiddenError("story.reply_self", code="reply_self")

    conv = await conversation_service.get_or_create(db, me, story.author_id)

    # idempotence si le client rejoue (offline)
    if data.client_id:
        dup = await db.scalar(
            select(Message).where(
                Message.conversation_id == conv.id, Message.client_id == data.client_id
            )
        )
        if dup is not None:
            return dup

    msg = Message(
        conversation_id=conv.id,
        sender_id=me.id,
        type=MessageType.text,
        body=data.body,
        encrypted=False,
        client_id=data.client_id,
        story_id=story.id,
    )
    db.add(msg)
    conv.last_message_at = datetime.now(UTC)
    await db.flush()

    # event WS "message.new" pour que la reponse apparaisse dans la discussion
    from app.services import message_service  # local: evite un cycle

    payload = (
        await message_service._serialize(db, msg, viewer_id=story.author_id)  # noqa: SLF001
    ).model_dump(mode="json")
    payload["story_id"] = str(story.id)
    payload["story_caption"] = story.caption
    await manager.send_to_user(
        str(story.author_id), {"type": "message.new", "message": payload}
    )
    return msg
