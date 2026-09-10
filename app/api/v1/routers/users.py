"""Router utilisateurs — profil, recherche, blocage."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.schemas.common import Message
from app.schemas.user import (
    PrivacyFieldIn,
    PrivacyFieldOut,
    PrivacySettingsOut,
    UserMe,
    UserPublic,
    UserUpdate,
)
from app.services import user_service
from app.services.user_service import serialize_me, serialize_public

router = APIRouter()


@router.patch("/me", response_model=UserMe)
async def update_me(body: UserUpdate, current_user: CurrentUser, db: DbSession):
    user = await user_service.update_me(db, current_user, body)
    return await serialize_me(user)


@router.get("/me/privacy", response_model=PrivacySettingsOut)
async def get_privacy(current_user: CurrentUser, db: DbSession):
    """Confidentialite du profil : mode + liste de contacts par champ."""
    return await user_service.get_privacy(db, current_user)


@router.put("/me/privacy", response_model=PrivacyFieldOut)
async def set_privacy(body: PrivacyFieldIn, current_user: CurrentUser, db: DbSession):
    """Change le mode d'UN champ (online / last_seen / profile_photo / about)
    et, pour 'everyone_except' / 'only', sa liste de contacts."""
    return await user_service.set_privacy_field(
        db, current_user, body.field, body.mode, body.contact_ids
    )


@router.get("/search", response_model=list[UserPublic])
async def search(current_user: CurrentUser, db: DbSession, q: str = Query(..., min_length=2)):
    return await user_service.search_users(db, q=q, me=current_user)


@router.get("/blocked", response_model=list[UserPublic])
async def blocked(current_user: CurrentUser, db: DbSession):
    """Utilisateurs que j'ai bloqués."""
    return await user_service.list_blocked(db, current_user)


@router.get("/{user_id}", response_model=UserPublic)
async def get_user(user_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    user = await user_service.get_user_or_404(db, user_id)
    is_contact = await user_service.are_contacts(db, current_user.id, user.id)
    is_blocked = await user_service.is_blocked_between(db, current_user.id, user.id)
    return await serialize_public(
        user,
        db=db,
        viewer_id=current_user.id,
        viewer_is_contact=is_contact,
        blocked=is_blocked,
    )


@router.post("/{user_id}/block", response_model=Message)
async def block(user_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await user_service.block_user(db, current_user, user_id)
    return Message(message="blocked")


@router.delete("/{user_id}/block", response_model=Message)
async def unblock(user_id: uuid.UUID, current_user: CurrentUser, db: DbSession):
    await user_service.unblock_user(db, current_user, user_id)
    return Message(message="unblocked")
