"""Import de tous les modeles — Alembic autogenerate lit `Base.metadata`,
donc chaque modele doit etre importe ici.
"""
from app.db.base import Base
from app.db.models.appointment import (
    Appointment,
    AppointmentParticipant,
    AppointmentParticipantStatus,
    AppointmentReminder,
    AppointmentReminderKind,
    AppointmentStatus,
)
from app.db.models.appointment_note import (
    AppointmentHiddenByUser,
    AppointmentNote,
    AppointmentNoteVisibility,
)
from app.db.models.auth import OtpChallenge, RefreshToken
from app.db.models.block import UserBlock
from app.db.models.call import CallDirection, CallLog, CallStatus, CallType
from app.db.models.call_rating import CallRating
from app.db.models.channel_discussion import ChannelDiscussion
from app.db.models.channel_live import ChannelLive, ChannelLiveStatus
from app.db.models.contact import UserContact
from app.db.models.conversation import (
    Conversation,
    ConversationHide,
    ConversationMute,
    ConversationRequest,
)
from app.db.models.device import Device, OneTimePreKey
from app.db.models.group import (
    Group,
    GroupJoinRequest,
    GroupMember,
    GroupMessage,
    GroupMessageReaction,
)
from app.db.models.message import Message, MessageReaction, MessageReceipt
from app.db.models.pinned_message import PinnedMessage
from app.db.models.privacy import PrivacyAudienceEntry, PrivacyField
from app.db.models.push import DeviceToken
from app.db.models.report import ReportReason, UserReport
from app.db.models.story import (
    Story,
    StoryAudienceEntry,
    StoryAudienceMode,
    StoryReaction,
    StoryView,
    StoryViewerMute,
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
    "StoryViewerMute",
    "Group",
    "GroupMember",
    "GroupMessage",
    "GroupMessageReaction",
    "GroupJoinRequest",
    "ChannelLive",
    "ChannelLiveStatus",
    "UserReport",
    "ReportReason",
    "PinnedMessage",
    "ChannelDiscussion",
    "CallRating",
    "Appointment",
    "AppointmentStatus",
    "AppointmentParticipant",
    "AppointmentParticipantStatus",
    "AppointmentReminder",
    "AppointmentReminderKind",
    "AppointmentNote",
    "AppointmentNoteVisibility",
    "AppointmentHiddenByUser",
]
