"""Services utilisateur — serialisation, recherche, contacts, blocage."""
from __future__ import annotations

import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.db.models.block import UserBlock
from app.db.models.contact import UserContact
from app.db.models.privacy import PrivacyAudienceEntry
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


PRIVACY_FIELDS = ("online", "last_seen", "profile_photo", "about")
# modes acceptes par l'API (les 3 heritage restent valides pour retro-compat)
PRIVACY_MODES = {
    "everyone",
    "contacts",
    "nobody",
    "everyone_except",
    "only",
    "match_last_seen",  # 'online' uniquement
}


def _visible(privacy: str, *, viewer_is_contact: bool, is_self: bool) -> bool:
    """Regle de visibilite d'un champ selon le parametre de confidentialite
    HERITAGE ('everyone' | 'contacts' | 'nobody'). Pour les modes 'sauf' /
    'uniquement', voir `PrivacyResolver`."""
    if is_self:
        return True
    if privacy == "nobody":
        return False
    if privacy == "contacts":
        return viewer_is_contact
    return True  # 'everyone'


async def _field_audience(
    db: AsyncSession, owner_id: uuid.UUID
) -> dict[str, set[uuid.UUID]]:
    """Toutes les listes de confidentialite d'un utilisateur, par champ."""
    rows = (
        await db.execute(
            select(PrivacyAudienceEntry.field, PrivacyAudienceEntry.target_id).where(
                PrivacyAudienceEntry.owner_id == owner_id
            )
        )
    ).all()
    out: dict[str, set[uuid.UUID]] = {}
    for field, target in rows:
        out.setdefault(field, set()).add(target)
    return out


class PrivacyResolver:
    """Resout la visibilite des 4 champs de profil de `owner` pour un lecteur
    donne, en tenant compte des modes ('everyone' / 'contacts' / 'nobody' /
    'everyone_except' / 'only' / 'match_last_seen') et des listes par champ.

    Evalue a la lecture (liste courante), facon WhatsApp.
    """

    def __init__(
        self,
        owner: User,
        *,
        audience: dict[str, set[uuid.UUID]],
        viewer_id: uuid.UUID | None,
        viewer_is_contact: bool,
        blocked: bool,
    ) -> None:
        self.owner = owner
        self.audience = audience
        self.viewer_id = viewer_id
        self.viewer_is_contact = viewer_is_contact
        self.blocked = blocked
        self.is_self = viewer_id is not None and viewer_id == owner.id

    @classmethod
    async def load(
        cls,
        db: AsyncSession,
        owner: User,
        *,
        viewer_id: uuid.UUID | None,
        viewer_is_contact: bool,
        blocked: bool = False,
    ) -> "PrivacyResolver":
        aud = (
            {}
            if (viewer_id is not None and viewer_id == owner.id)
            else await _field_audience(db, owner.id)
        )
        return cls(
            owner,
            audience=aud,
            viewer_id=viewer_id,
            viewer_is_contact=viewer_is_contact,
            blocked=blocked,
        )

    def _mode(self, field: str) -> str:
        if field == "online":
            return self.owner.online_privacy or "match_last_seen"
        return getattr(self.owner, f"{field}_privacy", "everyone") or "everyone"

    def visible(self, field: str) -> bool:
        if self.is_self:
            return True
        if self.blocked:
            return False  # un blocage masque tout

        mode = self._mode(field)
        if field == "online" and mode == "match_last_seen":
            return self.visible("last_seen")

        if mode == "nobody":
            return False
        if mode == "everyone":
            return True
        if mode == "contacts":
            return self.viewer_is_contact
        listed = self.audience.get(field, set())
        if mode == "everyone_except":
            return self.viewer_id not in listed
        if mode == "only":
            return self.viewer_id in listed
        return True


async def serialize_public(
    user: User,
    *,
    db: AsyncSession | None = None,
    online: bool | None = None,
    viewer_id: uuid.UUID | None = None,
    viewer_is_contact: bool = True,
    blocked: bool = False,
) -> UserPublic:
    """Serialise le profil public.

    `viewer_id` / `viewer_is_contact` : applique les parametres de
    confidentialite (en ligne, derniere connexion, photo, a propos). Par
    defaut on considere le lecteur comme un contact (listes de conversations /
    contacts) ; `GET /users/{id}` passe l'info reelle.

    `db` : requis pour appliquer les modes 'sauf' / 'uniquement' (listes par
    champ). Sans `db`, seul le mode heritage est evalue (suffisant pour les
    listes internes ou le lecteur est un contact).

    `blocked` : blocage entre le lecteur et `user` -> on masque TOUT (photo,
    a propos, derniere connexion, statut en ligne). Le blocage d'envoi de
    messages / d'appels est applique ailleurs.
    """
    data = UserPublic.model_validate(user)
    is_self = viewer_id is not None and viewer_id == user.id

    if blocked and not is_self:
        data.avatar_url = None
        data.about = None
        data.last_seen_at = None
        data.is_online = False
        return data

    if db is not None:
        pr = await PrivacyResolver.load(
            db,
            user,
            viewer_id=viewer_id,
            viewer_is_contact=viewer_is_contact,
            blocked=blocked,
        )
        show_last_seen = pr.visible("last_seen")
        show_photo = pr.visible("profile_photo")
        show_about = pr.visible("about")
        show_online = pr.visible("online")
    else:
        show_last_seen = _visible(
            user.last_seen_privacy, viewer_is_contact=viewer_is_contact, is_self=is_self
        )
        show_photo = _visible(
            user.profile_photo_privacy, viewer_is_contact=viewer_is_contact, is_self=is_self
        )
        show_about = _visible(
            user.about_privacy, viewer_is_contact=viewer_is_contact, is_self=is_self
        )
        # heritage : "en ligne" suit la derniere connexion
        show_online = show_last_seen

    if not show_last_seen:
        data.last_seen_at = None
    if not show_photo:
        data.avatar_url = None
    if not show_about:
        data.about = None

    if show_online:
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


# ── Confidentialite du profil (mode + liste par champ) ────────────────────
async def _contact_id_set(db: AsyncSession, me_id: uuid.UUID) -> set[uuid.UUID]:
    """Contacts de `me` (conversations + repertoire), sans les bloques."""
    from app.db.models.conversation import Conversation  # local: cycle

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
    rc = (
        await db.execute(
            select(UserContact.owner_id, UserContact.matched_user_id).where(
                or_(UserContact.owner_id == me_id, UserContact.matched_user_id == me_id)
            )
        )
    ).all()
    for owner, matched in rc:
        if matched is None:
            continue
        ids.add(matched if owner == me_id else owner)
    return ids - await blocked_ids(db, me_id)


async def get_privacy(db: AsyncSession, me: User) -> dict:
    aud = await _field_audience(db, me.id)

    def field(name: str, mode: str) -> dict:
        return {
            "mode": mode,
            "contact_ids": [str(x) for x in aud.get(name, set())],
        }

    return {
        "online": field("online", me.online_privacy or "match_last_seen"),
        "last_seen": field("last_seen", me.last_seen_privacy or "everyone"),
        "profile_photo": field(
            "profile_photo", me.profile_photo_privacy or "everyone"
        ),
        "about": field("about", me.about_privacy or "everyone"),
    }


async def set_privacy_field(
    db: AsyncSession, me: User, field: str, mode: str, contact_ids: list[uuid.UUID]
) -> dict:
    if field not in PRIVACY_FIELDS:
        raise AppError("privacy.bad_field", status_code=400, code="bad_field")
    valid = PRIVACY_MODES if field == "online" else PRIVACY_MODES - {"match_last_seen"}
    if mode not in valid:
        raise AppError("privacy.bad_mode", status_code=400, code="bad_mode")

    if field == "online":
        me.online_privacy = mode
    else:
        setattr(me, f"{field}_privacy", mode)

    # liste : uniquement pertinente pour 'everyone_except' / 'only'
    wanted: set[uuid.UUID] = set()
    if mode in ("everyone_except", "only"):
        contacts = await _contact_id_set(db, me.id)
        wanted = {c for c in contact_ids if c in contacts}

    current = (await _field_audience(db, me.id)).get(field, set())
    to_del = current - wanted
    if to_del:
        await db.execute(
            PrivacyAudienceEntry.__table__.delete().where(
                PrivacyAudienceEntry.owner_id == me.id,
                PrivacyAudienceEntry.field == field,
                PrivacyAudienceEntry.target_id.in_(to_del),
            )
        )
    for tid in wanted - current:
        db.add(
            PrivacyAudienceEntry(owner_id=me.id, field=field, target_id=tid)
        )
    await db.flush()
    return {"mode": mode, "contact_ids": [str(x) for x in wanted]}


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
async def blocked_ids(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Tous les ids en relation de blocage avec `user_id` (dans un sens ou
    l'autre) — a exclure de toute vue sociale (contacts, stories, presence)."""
    rows = await db.execute(
        select(UserBlock.blocked_id, UserBlock.blocker_id).where(
            or_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == user_id)
        )
    )
    ids: set[uuid.UUID] = set()
    for blocked_id, blocker_id in rows.all():
        ids.add(blocked_id if blocker_id == user_id else blocker_id)
    return ids


# alias historique (compat interne)
_blocked_ids = blocked_ids


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
