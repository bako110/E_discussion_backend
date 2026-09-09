"""Groupes & chaines — creation, adhesion, messages, membres.

Messages EN CLAIR (pas d'E2E de groupe). Diffusion temps reel : chaque event
est pousse a tous les membres via `manager.send_to_user`.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.db.models.group import (
    Group,
    GroupKind,
    GroupMember,
    GroupMessage,
    GroupRole,
)
from app.db.models.user import User
from app.schemas.group import (
    GroupCreate,
    GroupMemberOut,
    GroupMessageCreate,
    GroupMessageOut,
    GroupOut,
    GroupPreview,
    GroupUpdate,
)
from app.services import user_service
from app.services.ws_manager import manager

_POST_ROLES = {GroupRole.owner, GroupRole.admin, GroupRole.member}
_ADMIN_ROLES = {GroupRole.owner, GroupRole.admin}


# ── helpers ────────────────────────────────────────────────────────────────
async def _membership(
    db: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> GroupMember | None:
    return await db.scalar(
        select(GroupMember).where(
            GroupMember.group_id == group_id, GroupMember.user_id == user_id
        )
    )


async def _require_member(
    db: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[Group, GroupMember]:
    group = await db.get(Group, group_id)
    if group is None:
        raise NotFoundError("group.not_found", code="group_not_found")
    mem = await _membership(db, group_id, user_id)
    if mem is None:
        raise ForbiddenError("group.not_member", code="not_member")
    return group, mem


async def _member_ids(db: AsyncSession, group_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await db.execute(
        select(GroupMember.user_id).where(GroupMember.group_id == group_id)
    )
    return [r[0] for r in rows.all()]


async def _broadcast(db: AsyncSession, group_id: uuid.UUID, payload: dict) -> None:
    for uid in await _member_ids(db, group_id):
        await manager.send_to_user(str(uid), payload)


def _can_post(group: Group, role: GroupRole) -> bool:
    if group.kind == GroupKind.channel:
        return role in _ADMIN_ROLES
    return role in _POST_ROLES


async def _serialize_group(
    db: AsyncSession, group: Group, *, me_id: uuid.UUID
) -> GroupOut:
    member_count = await db.scalar(
        select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group.id)
    )
    mem = await _membership(db, group.id, me_id)

    last_msg = await db.scalar(
        select(GroupMessage)
        .where(GroupMessage.group_id == group.id, GroupMessage.deleted_at.is_(None))
        .order_by(GroupMessage.created_at.desc())
        .limit(1)
    )
    unread = 0
    if mem is not None:
        since = mem.last_read_at
        q = select(func.count()).select_from(GroupMessage).where(
            GroupMessage.group_id == group.id,
            GroupMessage.sender_id != me_id,
            GroupMessage.deleted_at.is_(None),
        )
        if since is not None:
            q = q.where(GroupMessage.created_at > since)
        unread = int(await db.scalar(q) or 0)

    out = GroupOut.model_validate(group)
    out.member_count = int(member_count or 0)
    out.unread_count = unread
    out.my_role = mem.role if mem else None
    out.can_post = _can_post(group, mem.role) if mem else False
    if last_msg is not None:
        out.last_message_preview = (
            last_msg.body[:120] if last_msg.type == "text" else f"[{last_msg.type}]"
        )
    return out


async def _serialize_message(
    db: AsyncSession, m: GroupMessage, *, with_sender: bool = True
) -> GroupMessageOut:
    out = GroupMessageOut.model_validate(m)
    if with_sender:
        sender = await db.get(User, m.sender_id)
        if sender is not None:
            out.sender = await user_service.serialize_public(sender)
    return out


# ── creation / edition ─────────────────────────────────────────────────────
async def create_group(db: AsyncSession, me: User, data: GroupCreate) -> GroupOut:
    group = Group(
        kind=data.kind,
        name=data.name.strip(),
        description=data.description,
        avatar_url=data.avatar_url,
        owner_id=me.id,
        is_public=data.is_public,
    )
    db.add(group)
    await db.flush()

    db.add(GroupMember(group_id=group.id, user_id=me.id, role=GroupRole.owner))

    default_role = (
        GroupRole.subscriber if data.kind == GroupKind.channel else GroupRole.member
    )
    seen = {me.id}
    for uid in data.member_ids:
        if uid in seen:
            continue
        seen.add(uid)
        if await db.get(User, uid) is None:
            continue
        db.add(GroupMember(group_id=group.id, user_id=uid, role=default_role))
    await db.flush()

    for uid in seen - {me.id}:
        await manager.send_to_user(
            str(uid),
            {"type": "group.added", "group_id": str(group.id), "kind": group.kind.value},
        )
    return await _serialize_group(db, group, me_id=me.id)


async def update_group(
    db: AsyncSession, me: User, group_id: uuid.UUID, data: GroupUpdate
) -> GroupOut:
    group, mem = await _require_member(db, group_id, me.id)
    if mem.role not in _ADMIN_ROLES:
        raise ForbiddenError("group.not_admin", code="not_admin")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await db.flush()
    await _broadcast(db, group_id, {"type": "group.updated", "group_id": str(group_id)})
    return await _serialize_group(db, group, me_id=me.id)


# ── lecture ────────────────────────────────────────────────────────────────
async def my_groups(db: AsyncSession, me: User, kind: GroupKind | None = None) -> list[GroupOut]:
    q = (
        select(Group)
        .join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.user_id == me.id)
    )
    if kind is not None:
        q = q.where(Group.kind == kind)
    rows = (await db.execute(q)).scalars().all()
    rows = sorted(rows, key=lambda g: g.last_message_at or g.created_at, reverse=True)
    return [await _serialize_group(db, g, me_id=me.id) for g in rows]


async def get_group(db: AsyncSession, me: User, group_id: uuid.UUID) -> GroupOut:
    group, _ = await _require_member(db, group_id, me.id)
    return await _serialize_group(db, group, me_id=me.id)


async def preview_by_code(db: AsyncSession, me: User, invite_code: str) -> GroupPreview:
    group = await db.scalar(select(Group).where(Group.invite_code == invite_code))
    if group is None:
        raise NotFoundError("group.not_found", code="group_not_found")
    member_count = await db.scalar(
        select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group.id)
    )
    is_member = await _membership(db, group.id, me.id) is not None
    return GroupPreview(
        id=group.id,
        kind=group.kind,
        name=group.name,
        description=group.description,
        avatar_url=group.avatar_url,
        member_count=int(member_count or 0),
        is_member=is_member,
    )


async def members(db: AsyncSession, me: User, group_id: uuid.UUID) -> list[GroupMemberOut]:
    await _require_member(db, group_id, me.id)
    rows = (
        await db.execute(
            select(GroupMember, User)
            .join(User, User.id == GroupMember.user_id)
            .where(GroupMember.group_id == group_id)
            .order_by(GroupMember.created_at)
        )
    ).all()
    return [
        GroupMemberOut(
            user=await user_service.serialize_public(u),
            role=gm.role,
            joined_at=gm.created_at,
            muted=gm.muted,
        )
        for gm, u in rows
    ]


# ── adhesion ───────────────────────────────────────────────────────────────
async def join_by_code(db: AsyncSession, me: User, invite_code: str) -> GroupOut:
    group = await db.scalar(select(Group).where(Group.invite_code == invite_code))
    if group is None:
        raise NotFoundError("group.not_found", code="group_not_found")

    existing = await _membership(db, group.id, me.id)
    if existing is None:
        role = (
            GroupRole.subscriber if group.kind == GroupKind.channel else GroupRole.member
        )
        db.add(GroupMember(group_id=group.id, user_id=me.id, role=role))
        await db.flush()
        # message systeme + notif membres
        sys = GroupMessage(
            group_id=group.id,
            sender_id=me.id,
            type="system",
            body=f"{me.display_name or me.username or 'Quelqu un'} a rejoint",
        )
        db.add(sys)
        await db.flush()
        await _broadcast(
            db,
            group.id,
            {"type": "group.member", "group_id": str(group.id), "user_id": str(me.id), "action": "join"},
        )
    return await _serialize_group(db, group, me_id=me.id)


async def leave(db: AsyncSession, me: User, group_id: uuid.UUID) -> None:
    group, mem = await _require_member(db, group_id, me.id)
    if mem.role == GroupRole.owner:
        # owner qui part : transfere a l'admin/membre le plus ancien, sinon supprime
        nxt = await db.scalar(
            select(GroupMember)
            .where(GroupMember.group_id == group_id, GroupMember.user_id != me.id)
            .order_by(GroupMember.created_at)
            .limit(1)
        )
        if nxt is None:
            await db.delete(group)
            await db.flush()
            return
        nxt.role = GroupRole.owner
    await db.delete(mem)
    await db.flush()
    await _broadcast(
        db,
        group_id,
        {"type": "group.member", "group_id": str(group_id), "user_id": str(me.id), "action": "leave"},
    )


async def set_muted(db: AsyncSession, me: User, group_id: uuid.UUID, muted: bool) -> None:
    _, mem = await _require_member(db, group_id, me.id)
    mem.muted = muted
    await db.flush()


# ── messages ───────────────────────────────────────────────────────────────
async def send_message(
    db: AsyncSession, me: User, group_id: uuid.UUID, data: GroupMessageCreate
) -> GroupMessageOut:
    group, mem = await _require_member(db, group_id, me.id)
    if not _can_post(group, mem.role):
        raise ForbiddenError("group.cannot_post", code="cannot_post")
    if data.type == "text" and not data.body.strip() and not data.attachment_url:
        raise AppError("errors.validation", status_code=422, code="empty_message")

    if data.client_id:
        dup = await db.scalar(
            select(GroupMessage).where(
                GroupMessage.group_id == group_id,
                GroupMessage.client_id == data.client_id,
            )
        )
        if dup is not None:
            return await _serialize_message(db, dup)

    msg = GroupMessage(
        group_id=group_id,
        sender_id=me.id,
        type=data.type,
        body=data.body,
        attachment_url=data.attachment_url,
        attachment_meta=data.attachment_meta,
        client_id=data.client_id,
    )
    db.add(msg)
    group.last_message_at = datetime.now(UTC)
    await db.flush()

    out = await _serialize_message(db, msg)
    payload = out.model_dump(mode="json")
    for uid in await _member_ids(db, group_id):
        if uid == me.id:
            continue
        await manager.send_to_user(
            str(uid), {"type": "group.message", "group_id": str(group_id), "message": payload}
        )
    return out


async def history(
    db: AsyncSession, me: User, group_id: uuid.UUID, *, before: datetime | None, limit: int
) -> list[GroupMessageOut]:
    await _require_member(db, group_id, me.id)
    q = (
        select(GroupMessage)
        .where(GroupMessage.group_id == group_id, GroupMessage.deleted_at.is_(None))
        .order_by(GroupMessage.created_at.desc())
        .limit(limit)
    )
    if before is not None:
        q = q.where(GroupMessage.created_at < before)
    rows = (await db.execute(q)).scalars().all()
    rows = list(reversed(rows))
    return [await _serialize_message(db, m) for m in rows]


async def mark_read(db: AsyncSession, me: User, group_id: uuid.UUID) -> None:
    _, mem = await _require_member(db, group_id, me.id)
    mem.last_read_at = datetime.now(UTC)
    await db.flush()
