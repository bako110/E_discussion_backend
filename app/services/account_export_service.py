"""Export des donnees d'un compte (portabilite / RGPD).

Rassemble en un seul JSON : profil, identifiants, parametres de confidentialite,
contacts reconnus, conversations (metadonnees), messages envoyes, stories,
appartenance a des groupes. Ne contient PAS les cles privees E2E (elles ne
quittent jamais l'appareil) ni les messages chiffres en clair (le serveur ne
les dechiffre pas).
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.contact import UserContact
from app.db.models.conversation import Conversation
from app.db.models.group import Group, GroupMember, GroupMessage
from app.db.models.message import Message
from app.db.models.story import Story
from app.db.models.user import User


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def build_export(db: AsyncSession, user: User) -> dict:
    # ── profil ────────────────────────────────────────────────────────────
    profile = {
        "id": str(user.id),
        "username": user.username,
        "display_name": user.display_name,
        "about": user.about,
        "avatar_url": user.avatar_url,
        "email": user.email,
        "phone": user.phone,
        "locale": user.locale,
        "created_at": _iso(user.created_at),
        "privacy": {
            "online": user.online_privacy,
            "last_seen": user.last_seen_privacy,
            "profile_photo": user.profile_photo_privacy,
            "about": user.about_privacy,
            "read_receipts": user.read_receipts,
            "story_audience_mode": user.story_audience_mode,
        },
        "call_preferences": {
            "ringtone": user.call_ringtone,
            "vibrate": user.call_vibrate,
            "answer_on_speaker": user.call_answer_on_speaker,
            "low_data": user.call_low_data,
            "block_unknown": user.call_block_unknown,
        },
    }

    # ── contacts reconnus ─────────────────────────────────────────────────
    contact_rows = (
        await db.execute(
            select(UserContact).where(UserContact.owner_id == user.id)
        )
    ).scalars().all()
    contacts = [
        {
            "phone": c.phone,
            "display_name": c.display_name,
            "is_on_app": c.matched_user_id is not None,
        }
        for c in contact_rows
    ]

    # ── conversations + mes messages ─────────────────────────────────────
    conv_rows = (
        await db.execute(
            select(Conversation).where(
                or_(
                    Conversation.user_a_id == user.id,
                    Conversation.user_b_id == user.id,
                )
            )
        )
    ).scalars().all()
    conversations = []
    for conv in conv_rows:
        partner_id = conv.user_b_id if conv.user_a_id == user.id else conv.user_a_id
        my_msgs = (
            await db.execute(
                select(Message)
                .where(
                    Message.conversation_id == conv.id,
                    Message.sender_id == user.id,
                )
                .order_by(Message.created_at)
            )
        ).scalars().all()
        conversations.append(
            {
                "id": str(conv.id),
                "partner_id": str(partner_id),
                "created_at": _iso(conv.created_at),
                "my_messages": [
                    {
                        "id": str(m.id),
                        "type": m.type.value,
                        # message chiffre : on n'a que le blob, on l'omet
                        "body": None if m.encrypted else m.body,
                        "encrypted": m.encrypted,
                        "created_at": _iso(m.created_at),
                        "edited_at": _iso(m.edited_at),
                    }
                    for m in my_msgs
                ],
            }
        )

    # ── stories ──────────────────────────────────────────────────────────
    story_rows = (
        await db.execute(
            select(Story)
            .where(Story.author_id == user.id)
            .order_by(Story.created_at)
        )
    ).scalars().all()
    stories = [
        {
            "id": str(s.id),
            "media_type": s.media_type.value,
            "media_url": s.media_url,
            "caption": s.caption,
            "audience": s.audience,
            "created_at": _iso(s.created_at),
            "expires_at": _iso(s.expires_at),
        }
        for s in story_rows
    ]

    # ── groupes ──────────────────────────────────────────────────────────
    member_rows = (
        await db.execute(
            select(GroupMember, Group)
            .join(Group, Group.id == GroupMember.group_id)
            .where(GroupMember.user_id == user.id)
        )
    ).all()
    groups = []
    for gm, g in member_rows:
        sent = await db.scalar(
            select(GroupMessage.id).where(
                GroupMessage.group_id == g.id, GroupMessage.sender_id == user.id
            ).limit(1)
        )
        groups.append(
            {
                "id": str(g.id),
                "kind": g.kind.value,
                "name": g.name,
                "role": gm.role.value,
                "joined_at": _iso(gm.created_at),
                "has_posted": sent is not None,
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "format_version": 1,
        "profile": profile,
        "contacts": contacts,
        "conversations": conversations,
        "stories": stories,
        "groups": groups,
    }
