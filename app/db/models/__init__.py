"""Import de tous les modeles — Alembic autogenerate lit `Base.metadata`,
donc chaque modele doit etre importe ici.
"""
from app.db.base import Base
from app.db.models.auth import OtpChallenge, RefreshToken
from app.db.models.block import UserBlock
from app.db.models.call import CallDirection, CallLog, CallStatus, CallType
from app.db.models.contact import UserContact
from app.db.models.conversation import (
    Conversation,
    ConversationHide,
    ConversationMute,
    ConversationRequest,
)
from app.db.models.device import Device, OneTimePreKey
from app.db.models.group import Group, GroupJoinRequest, GroupMember, GroupMessage
from app.db.models.message import Message, MessageReaction, MessageReceipt
from app.db.models.privacy import PrivacyAudienceEntry, PrivacyField
from app.db.models.push import DeviceToken
from app.db.models.story import (
    Story,
    StoryAudienceEntry,
    StoryAudienceMode,
    StoryReaction,
    StoryView,
)
from app.db.models.user import User

__all__ = [
    "Base",
    "User",
    "RefreshToken",
    "OtpChallenge",
    "UserContact",
    "UserBlock",
    "PrivacyAudienceEntry",
    "PrivacyField",
    "Conversation",
    "ConversationRequest",
    "ConversationMute",
    "ConversationHide",
    "Message",
    "MessageReaction",
    "MessageReceipt",
    "Device",
    "OneTimePreKey",
    "DeviceToken",
    "CallLog",
    "CallStatus",
    "CallType",
    "CallDirection",
    "Story",
    "StoryView",
    "StoryReaction",
    "StoryAudienceEntry",
    "StoryAudienceMode",
    "Group",
    "GroupMember",
    "GroupMessage",
    "GroupJoinRequest",
]
