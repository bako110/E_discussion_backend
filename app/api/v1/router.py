"""Agregation des routers de l'API v1."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routers import (
    auth,
    calls,
    contacts,
    conversations,
    devices,
    groups,
    media,
    messages,
    stories,
    users,
    ws,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(contacts.router, prefix="/contacts", tags=["Contacts"])
api_router.include_router(conversations.router, prefix="/conversations", tags=["Conversations"])
api_router.include_router(messages.router, prefix="/messages", tags=["Messages"])
api_router.include_router(stories.router, prefix="/stories", tags=["Stories"])
api_router.include_router(groups.router, prefix="/groups", tags=["Groups & Channels"])
api_router.include_router(media.router, prefix="/media", tags=["Media"])
api_router.include_router(devices.router, prefix="/devices", tags=["Devices / E2E Keys"])
api_router.include_router(calls.router, prefix="/calls", tags=["Calls (WebRTC)"])
api_router.include_router(ws.router, tags=["WebSocket"])
