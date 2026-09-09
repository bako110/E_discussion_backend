"""Services utilisateur — serialisation, recherche, contacts, blocage."""
from __future__ import annotations

import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.db.models.block import UserBlock
from app.db.models.contact import UserContact
from app.db.models.user import User
from app.db.redis import filter_online, is_online
from app.schemas.user import (
    ContactMatch,
    ContactSyncIn,
    UserMe,
    UserPublic,
    UserUpdate,
)
from app.utils.phone import to_e164


def _visible(privacy: str, *, viewer_is_contact: bool, is_self: bool) -> bool:
    """Regle de visibilite d'un champ selon le parametre de confidentialite."""
    if is_self:
        return True
    if privacy == "nobody":
        return False
    if privacy == "contacts":
        return viewer_is_contact
    return True  # 'everyone'


async def serialize_public(
    user: User,
    *,
    online: bool | None = None,
    viewer_id: uuid.UUID | None = None,
    viewer_is_contact: bool = True,
) -> UserPublic:
    """Serialise le profil public.

    `viewer_id` / `viewer_is_contact` : applique les parametres de
    confidentialite (derniere connexion, photo, a propos). Par defaut on
    considere le lecteur comme un contact (cas des listes de conversations /
    contacts) ; `GET /users/{id}` passe l'info reelle.
    """
    data = UserPublic.model_validate(user)
    is_self = viewer_id is not None and viewer_id == user.id

    if not _visible(user.last_seen_privacy, viewer_is_contact=viewer_is_contact, is_self=is_self):
        data.last_seen_at = None
    if not _visible(user.profile_photo_privacy, viewer_is_contact=viewer_is_contact, is_self=is_self):
        data.avatar_url = None
    if not _visible(user.about_privacy, viewer_is_contact=viewer_is_contact, is_self=is_self):
        data.about = None

    # presence en ligne : masquee si la "derniere connexion" l'est
    show_presence = _visible(
        user.last_seen_privacy, viewer_is_contact=viewer_is_contact, is_self=is_self
    )
    if show_presence:
        data.is_online = online if online is not None else await is_online(str(user.id))
    else:
        data.is_online = False
    return data


async def serialize_me(user: User) -> UserMe:
    data = UserMe.model_validate(user)
    data.is_online = True
    return data


async def get_user_or_404(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise NotFoundError("user.not_found", code="user_not_found")
    return user


async def update_me(db: AsyncSession, user: User, data: UserUpdate) -> User:
    patch = data.model_dump(exclude_unset=True)
    if "username" in patch and patch["username"]:
        exists = await db.execute(
            select(User.id).where(
                func.lower(User.username) == patch["username"].lower(), User.id != user.id
            )
        )
        if exists.first():
            raise AppError("auth.username_taken", status_code=409, code="username_taken")
    for field, value in patch.items():
        setattr(user, field, value)
    await db.flush()
    return user


async def search_users(db: AsyncSession, *, q: str, me: User, limit: int = 20) -> list[UserPublic]:
    term = q.strip()
    if len(term) < 2:
        return []
    blocked = await _blocked_ids(db, me.id)
    stmt = (
        select(User)
        .where(
            User.is_active.is_(True),
            User.id != me.id,
            User.id.notin_(blocked) if blocked else True,
            or_(
                func.lower(User.username).like(f"{term.lower()}%"),
                func.lower(User.display_name).like(f"%{term.lower()}%"),
                User.phone == (to_e164(term) or "___"),
            ),
        )
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    online = await filter_online([str(r.id) for r in rows])
    return [await serialize_public(r, online=str(r.id) in online) for r in rows]


# ── Contacts ───────────────────────────────────────────────────────────────
async def sync_contacts(db: AsyncSession, user: User, payload: ContactSyncIn) -> list[ContactMatch]:
    normalized: dict[str, str | None] = {}
    for entry in payload.contacts:
        e164 = to_e164(entry.phone)
        if e164 and e164 != user.phone:
            normalized[e164] = entry.display_name

    if not normalized:
        return []

    # upsert simple : on efface le repertoire puis on re-insere (v1)
    await db.execute(UserContact.__table__.delete().where(UserContact.owner_id == user.id))

    matched_rows = (
        await db.execute(select(User).where(User.phone.in_(list(normalized.keys()))))
    ).scalars().all()
    by_phone = {u.phone: u for u in matched_rows}

    results: list[ContactMatch] = []
    for phone, name in normalized.items():
        matched = by_phone.get(phone)
        db.add(
            UserContact(
                owner_id=user.id,
                phone=phone,
                display_name=name,
                matched_user_id=matched.id if matched else None,
            )
        )
        results.append(
            ContactMatch(
                phone=phone,
                display_name=name,
                user=(await serialize_public(matched)) if matched else None,
            )
        )
    await db.flush()
    return [r for r in results if r.user is not None]


async def list_contacts(db: AsyncSession, me: User, limit: int = 200) -> list[UserPublic]:
    """Mes contacts E-discussion : union
      - des comptes reconnus lors de la synchro du repertoire (UserContact
        avec matched_user_id),
      - des personnes avec qui j'ai deja une conversation.
    Tries par nom. Exclut moi-meme et les personnes bloquees."""
    from app.db.models.conversation import Conversation  # local: evite un cycle

    blocked = await _blocked_ids(db, me.id)

    contact_ids = set(
        (
            await db.execute(
                select(UserContact.matched_user_id).where(
                    UserContact.owner_id == me.id,
                    UserContact.matched_user_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )

    conv_rows = (
        await db.execute(
            select(Conversation.user_a_id, Conversation.user_b_id).where(
                or_(Conversation.user_a_id == me.id, Conversation.user_b_id == me.id)
            )
        )
    ).all()
    for a, b in conv_rows:
        contact_ids.add(b if a == me.id else a)

    contact_ids.discard(me.id)
    contact_ids -= blocked
    if not contact_ids:
        return []

    rows = (
        await db.execute(
            select(User)
            .where(User.id.in_(contact_ids), User.is_active.is_(True))
            .order_by(func.lower(func.coalesce(User.display_name, User.username)))
            .limit(limit)
        )
    ).scalars().all()
    online = await filter_online([str(r.id) for r in rows])
    return [await serialize_public(r, online=str(r.id) in online) for r in rows]


async def are_contacts(db: AsyncSession, a_id: uuid.UUID, b_id: uuid.UUID) -> bool:
    """True si `a` et `b` sont en relation : entree de repertoire reconnue OU
    conversation existante (dans un sens ou l'autre)."""
    from app.db.models.conversation import Conversation  # local: evite un cycle

    contact = await db.scalar(
        select(UserContact.id).where(
            or_(
                and_(UserContact.owner_id == a_id, UserContact.matched_user_id == b_id),
                and_(UserContact.owner_id == b_id, UserContact.matched_user_id == a_id),
            )
        )
    )
    if contact is not None:
        return True
    conv = await db.scalar(
        select(Conversation.id).where(
            or_(
                and_(Conversation.user_a_id == a_id, Conversation.user_b_id == b_id),
                and_(Conversation.user_a_id == b_id, Conversation.user_b_id == a_id),
            )
        )
    )
    return conv is not None


async def list_blocked(db: AsyncSession, me: User) -> list[UserPublic]:
    """Utilisateurs que J'AI bloques (pas ceux qui m'ont bloque)."""
    rows = (
        await db.execute(
            select(User)
            .join(UserBlock, UserBlock.blocked_id == User.id)
            .where(UserBlock.blocker_id == me.id)
            .order_by(func.lower(func.coalesce(User.display_name, User.username)))
        )
    ).scalars().all()
    # pas de presence / photo cachee ici : c'est une liste d'administration
    return [UserPublic.model_validate(u) for u in rows]


# ── Blocage ────────────────────────────────────────────────────────────────
async def _blocked_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    rows = await db.execute(
        select(UserBlock.blocked_id, UserBlock.blocker_id).where(
            or_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == user_id)
        )
    )
    ids: set[uuid.UUID] = set()
    for blocked_id, blocker_id in rows.all():
        ids.add(blocked_id if blocker_id == user_id else blocker_id)
    return ids


async def is_blocked_between(db: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    res = await db.execute(
        select(UserBlock.id).where(
            or_(
                and_(UserBlock.blocker_id == a, UserBlock.blocked_id == b),
                and_(UserBlock.blocker_id == b, UserBlock.blocked_id == a),
            )
        )
    )
    return res.first() is not None


async def block_user(db: AsyncSession, blocker: User, blocked_id: uuid.UUID) -> None:
    if blocker.id == blocked_id:
        raise AppError("user.cannot_block_self", status_code=400, code="cannot_block_self")
    await get_user_or_404(db, blocked_id)
    exists = await db.execute(
        select(UserBlock.id).where(
            UserBlock.blocker_id == blocker.id, UserBlock.blocked_id == blocked_id
        )
    )
    if exists.first():
        return
    db.add(UserBlock(blocker_id=blocker.id, blocked_id=blocked_id))
    await db.flush()


async def unblock_user(db: AsyncSession, blocker: User, blocked_id: uuid.UUID) -> None:
    await db.execute(
        UserBlock.__table__.delete().where(
            UserBlock.blocker_id == blocker.id, UserBlock.blocked_id == blocked_id
        )
    )
