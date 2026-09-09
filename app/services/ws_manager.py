"""Gestionnaire de connexions WebSocket temps reel.

Multi-worker : chaque event destine a un utilisateur est publie sur le canal
Redis `ws:user:{id}`. Chaque worker est abonne a ses propres utilisateurs
connectes et relaie l'event a leurs sockets locales.

Types d'events pousses (champ `type`) :
  - message.new        nouveau message recu
  - message.edited     message modifie
  - message.deleted    message supprime
  - message.reaction   reaction ajoutee/retiree
  - receipt.delivered  / receipt.read
  - typing.start / typing.stop
  - presence.update    { user_id, online, last_seen_at? }
  - conversation.request  nouvelle demande de conversation
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import WebSocket

from app.core.logging import get_logger
from app.db.redis import get_redis, mark_offline, mark_online

log = get_logger(__name__)


class WsManager:
    def __init__(self) -> None:
        self._local: dict[str, set[WebSocket]] = defaultdict(set)
        self._pubsub_task: asyncio.Task | None = None
        self._subscribed: set[str] = set()
        self._lock = asyncio.Lock()

    # ── cycle de vie d'une connexion ────────────────────────────────────
    async def connect(self, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            first_for_user = not self._local[user_id]
            self._local[user_id].add(ws)
        await mark_online(user_id)
        await self._ensure_subscribed(user_id)
        if first_for_user:
            await self.publish_presence(user_id, online=True)

    async def disconnect(self, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._local[user_id].discard(ws)
            still_here = bool(self._local[user_id])
            if not still_here:
                self._local.pop(user_id, None)
        if not still_here:
            await mark_offline(user_id)
            await self.publish_presence(user_id, online=False)

    # ── envoi ──────────────────────────────────────────────────────────
    async def send_to_user(self, user_id: str, payload: dict) -> None:
        """Publie via Redis -> tous les workers -> toutes les sockets de l'user."""
        await get_redis().publish(f"ws:user:{user_id}", json.dumps(payload))

    async def _deliver_local(self, user_id: str, raw: str) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._local.get(user_id, ())):
            try:
                await ws.send_text(raw)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(user_id, ws)

    async def publish_presence(self, user_id: str, *, online: bool) -> None:
        # notifie l'utilisateur lui-meme (multi-device) — les partenaires
        # recoivent la presence via le fetch de conversations / un event dedie
        payload: dict = {"type": "presence.update", "user_id": user_id, "online": online}
        if not online:
            # horodatage de deconnexion : permet l'affichage « vu à … » cote pair
            payload["last_seen_at"] = datetime.now(tz=timezone.utc).isoformat()
        await self.send_to_user(user_id, payload)

    # ── pub/sub Redis ──────────────────────────────────────────────────
    async def _ensure_subscribed(self, user_id: str) -> None:
        channel = f"ws:user:{user_id}"
        async with self._lock:
            if channel in self._subscribed:
                return
            self._subscribed.add(channel)
        if self._pubsub_task is None:
            self._pubsub_task = asyncio.create_task(self._pubsub_loop())

    async def _pubsub_loop(self) -> None:
        r = get_redis()
        pubsub = r.pubsub()
        await pubsub.psubscribe("ws:user:*")
        log.info("ws.pubsub.started")
        try:
            async for msg in pubsub.listen():
                if msg["type"] != "pmessage":
                    continue
                channel: str = msg["channel"]
                user_id = channel.rsplit(":", 1)[-1]
                if user_id in self._local:
                    await self._deliver_local(user_id, msg["data"])
        except asyncio.CancelledError:
            await pubsub.aclose()
            raise

    async def shutdown(self) -> None:
        if self._pubsub_task:
            self._pubsub_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._pubsub_task


manager = WsManager()
