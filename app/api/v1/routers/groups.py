"""Router groupes & chaines — CRUD, adhesion (invite_code / QR), messages."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, PageParams
from app.db.models.group import GroupKind
from app.schemas.channel_live import (
    ChannelLiveJoinOut,
    ChannelLiveOut,
    ChannelLiveStartIn,
    ChannelLiveStartOut,
)
from app.schemas.common import Message
from app.schemas.group import (
    AddMembersIn,
    GroupCreate,
    GroupJoinRequestOut,
    GroupMemberOut,
    GroupMessageCreate,
    GroupMessageOut,
    GroupOut,
    GroupPreview,
    GroupSettingsIn,
    GroupSettingsOut,
    GroupUpdate,
    JoinIn,
    SetRoleIn,
)
from app.services import channel_live_service, group_service

router = APIRouter()


@router.get("", response_model=list[GroupOut])
async def list_my_groups(
    current_user: CurrentUser,
    db: DbSession,
    kind: GroupKind | None = Query(None, description="'group' | 'channel'"),
):
    return await group_service.my_groups(db, current_user, kind)


@router.post("", response_model=GroupOut, status_code=201)
async def create(body: GroupCreate, current_user: CurrentUser, db: DbSession):
    return await group_service.create_group(db, current_user, body)


@router.get("/preview", response_model=GroupPreview)
async def preview(
    current_user: CurrentUser, db: DbSession, code: str = Query(..., min_length=4, max_length=16)
):
    """Aperçu d'un groupe/chaine depuis un code d'invitation (avant de rejoindre)."""
    return await group_service.preview_by_code(db, current_user, code)


@router.post("/join", response_model=GroupOut)
async def join(body: JoinIn, current_user: CurrentUser, db: DbSession):
    return await group_service.join_by_code(db, current_user, body.invite_code)


@router.get("/live", response_model=list[ChannelLiveOut])
async def list_live_channels(current_user: CurrentUser, db: DbSession):
    """Chaînes auxquelles je suis abonné et qui diffusent EN DIRECT en ce
    moment — alimente la section « Chaînes en direct » de l'écran Stories."""
    return await channel_live_service.list_live(db, current_user)


@router.get("/{group_id}", response_model=GroupOut)
async def get_one(group_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    return await group_service.get_group(db, current_user, group_id)


@router.patch("/{group_id}", response_model=GroupOut)
async def edit(
    group_id: uuid.UUID, body: GroupUpdate, current_user: CurrentUser, db: DbSession
):
    return await group_service.update_group(db, current_user, group_id, body)


@router.delete("/{group_id}", response_model=Message)
async def delete_group(group_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await group_service.delete_group(db, current_user, group_id)
    return Message(message="deleted")


@router.post("/{group_id}/invite/reset", response_model=GroupOut)
async def reset_invite(group_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    return await group_service.reset_invite_code(db, current_user, group_id)


@router.get("/{group_id}/members", response_model=list[GroupMemberOut])
async def get_members(group_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    return await group_service.members(db, current_user, group_id)


# ── Paramètres du groupe (admins) ────────────────────────────────────────
@router.get("/{group_id}/settings", response_model=GroupSettingsOut)
async def get_settings(group_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    return await group_service.get_settings(db, current_user, group_id)


@router.put("/{group_id}/settings", response_model=GroupOut)
async def set_settings(
    group_id: uuid.UUID, body: GroupSettingsIn, current_user: CurrentUser, db: DbSession
):
    return await group_service.set_settings(
        db, current_user, group_id, body.model_dump(exclude_unset=True)
    )


@router.get("/{group_id}/join-requests", response_model=list[GroupJoinRequestOut])
async def join_requests(group_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    return await group_service.list_join_requests(db, current_user, group_id)


@router.post("/{group_id}/join-requests/{user_id}/approve", response_model=Message)
async def approve_join(
    group_id: uuid.UUID, user_id: uuid.UUID, current_user: CurrentUser, db: DbSession
):
    await group_service.decide_join_request(db, current_user, group_id, user_id, True)
    return Message(message="approved")


@router.post("/{group_id}/join-requests/{user_id}/reject", response_model=Message)
async def reject_join(
    group_id: uuid.UUID, user_id: uuid.UUID, current_user: CurrentUser, db: DbSession
):
    await group_service.decide_join_request(db, current_user, group_id, user_id, False)
    return Message(message="rejected")


@router.post("/{group_id}/members", response_model=list[GroupMemberOut])
async def add_members(
    group_id: uuid.UUID, body: AddMembersIn, current_user: CurrentUser, db: DbSession
):
    return await group_service.add_members(db, current_user, group_id, body.user_ids)


@router.put("/{group_id}/members/{user_id}/role", response_model=Message)
async def set_member_role(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    body: SetRoleIn,
    current_user: CurrentUser,
    db: DbSession,
):
    await group_service.set_member_role(db, current_user, group_id, user_id, body.role)
    return Message(message="role updated")


@router.delete("/{group_id}/members/{user_id}", response_model=Message)
async def remove_member(
    group_id: uuid.UUID, user_id: uuid.UUID, current_user: CurrentUser, db: DbSession
):
    await group_service.remove_member(db, current_user, group_id, user_id)
    return Message(message="removed")


@router.post("/{group_id}/leave", response_model=Message)
async def leave(group_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await group_service.leave(db, current_user, group_id)
    return Message(message="left")


@router.put("/{group_id}/mute", response_model=Message)
async def mute(group_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await group_service.set_muted(db, current_user, group_id, True)
    return Message(message="muted")


@router.put("/{group_id}/unmute", response_model=Message)
async def unmute(group_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await group_service.set_muted(db, current_user, group_id, False)
    return Message(message="unmuted")


@router.get("/{group_id}/messages", response_model=list[GroupMessageOut])
async def get_messages(
    group_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    page: PageParams,
    before: datetime | None = Query(None, description="Pagination : messages avant cette date ISO"),
):
    return await group_service.history(
        db, current_user, group_id, before=before, limit=page.limit
    )


@router.post("/{group_id}/messages", response_model=GroupMessageOut, status_code=201)
async def post_message(
    group_id: uuid.UUID,
    body: GroupMessageCreate,
    current_user: CurrentUser,
    db: DbSession,
):
    return await group_service.send_message(db, current_user, group_id, body)


@router.put("/{group_id}/read", response_model=Message)
async def mark_read(group_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await group_service.mark_read(db, current_user, group_id)
    return Message(message="ok")


# ── diffusion en direct (chaînes) ─────────────────────────────────────────
@router.get("/{group_id}/live", response_model=ChannelLiveOut | None)
async def get_channel_live(group_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    """Session live en cours pour CETTE chaîne, ou null — alimente le bouton
    Démarrer/Rejoindre le direct dans les paramètres/l'info de la chaîne."""
    return await channel_live_service.get_for_channel(db, group_id)


@router.post("/{group_id}/live", response_model=ChannelLiveStartOut, status_code=201)
async def start_channel_live(
    group_id: uuid.UUID,
    body: ChannelLiveStartIn,
    current_user: CurrentUser,
    db: DbSession,
):
    """Démarre un direct (admin de la chaîne uniquement)."""
    out = await channel_live_service.start(db, current_user, group_id, body)
    await db.commit()
    return out


@router.post("/{group_id}/live/join", response_model=ChannelLiveJoinOut)
async def join_channel_live(group_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    """Rejoint le direct en cours en spectateur (lecture seule)."""
    return await channel_live_service.join(db, current_user, group_id)


@router.post("/{group_id}/live/stop", response_model=ChannelLiveOut)
async def stop_channel_live(group_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    """Arrête le direct en cours (admin de la chaîne uniquement)."""
    out = await channel_live_service.stop(db, current_user, group_id)
    await db.commit()
    return out
