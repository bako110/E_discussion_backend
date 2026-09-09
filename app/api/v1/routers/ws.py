"""WebSocket temps reel — /api/v1/ws

Auth : le client envoie en premier message JSON `{"type":"auth","token":"<jwt>"}`.
Ensuite le serveur pousse les events (message.new, receipt.*, typing.*,
presence.update, ...). Le client peut envoyer :
  {"type":"ping"}                                   -> {"type":"pong"} + refresh presence
  {"type":"typing","conversation_id":"...","state":"start|stop"}
  {"type":"delivered","message_id":"..."}
"""
from __future__ import annotations

import json
import uuid

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_token
from app.db.models.user import User
from app.db.redis import mark_online
from app.db.session import AsyncSessionLocal
from app.services import message_service
from app.services.conversation_service import get_owned
from app.services.ws_manager import manager

router = APIRouter()


async def _authenticate(ws: WebSocket) -> str | None:
    """Attend le premier message d'auth (max ~10s cote client). Retourne
    l'user_id ou None si echec."""
    try:
        raw = await ws.receive_text()
        data = json.loads(raw)
        if data.get("type") != "auth" or "token" not in data:
            return None
        payload = decode_token(data["token"], expected_type="access")
        return payload.get("sub")
    except (WebSocketDisconnect, json.JSONDecodeError, jwt.PyJWTError, KeyError):
        return None


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    user_id = await _authenticate(ws)
    if not user_id:
        await ws.close(code=4401)
        return

    # re-accept via manager n'est pas possible (deja accepte) -> on gere le
    # registre local directement
    await ws.send_text(json.dumps({"type": "auth.ok", "user_id": user_id}))
    await mark_online(user_id)
    manager._local[user_id].add(ws)  # noqa: SLF001 — enregistrement local
    await manager._ensure_subscribed(user_id)  # noqa: SLF001
    await manager.publish_presence(user_id, online=True)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await _handle_client_event(user_id, data)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(user_id, ws)


async def _handle_client_event(user_id: str, data: dict) -> None:
    kind = data.get("type")

    if kind == "ping":
        await mark_online(user_id)
        await manager.send_to_user(user_id, {"type": "pong"})
        return

    if kind == "typing":
        conv_id = data.get("conversation_id")
        state = data.get("state", "start")
        if not conv_id:
            return
        async with AsyncSessionLocal() as db:
            me = await db.get(User, uuid.UUID(user_id))
            if me is None:
                return
            try:
                conv = await get_owned(db, me, uuid.UUID(conv_id))
            except Exception:
                return
            partner_id = conv.user_b_id if conv.user_a_id == me.id else conv.user_a_id
        await manager.send_to_user(
            str(partner_id),
            {
                "type": f"typing.{'start' if state == 'start' else 'stop'}",
                "conversation_id": conv_id,
                "user_id": user_id,
            },
        )
        return

    if kind == "delivered":
        message_id = data.get("message_id")
        if not message_id:
            return
        async with AsyncSessionLocal() as db:
            await message_service.mark_delivered(db, uuid.UUID(user_id), uuid.UUID(message_id))
            await db.commit()
        return
