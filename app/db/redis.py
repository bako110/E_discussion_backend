"""Client Redis partage — presence utilisateurs, pub/sub WebSocket, cache OTP.

- Presence : cle `presence:{user_id}` avec TTL, rafraichie par le ping WS.
- Pub/sub  : canal `ws:user:{user_id}` pour pousser un event a toutes les
  connexions WS d'un utilisateur, meme reparties sur plusieurs workers.
- OTP      : cle `otp:{channel}:{identifier}` -> hash {code, attempts}.

En dev sans Redis : au premier echec de connexion, on bascule sur un
`_MemoryRedis` (memoire du process). Suffisant pour un seul worker :
presence + OTP + cooldown + PUB/SUB IN-PROCESS fonctionnent (le temps
reel WebSocket marche donc en dev mono-worker). Seul le pub/sub
INTER-process est perdu — sans effet avec un unique worker. Repasser sur
un vrai Redis = relancer avec Redis dispo (multi-worker).
"""
from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import time
from typing import Any

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_pool: Any | None = None
_use_memory = False


# ── Fallback in-memory (sous-ensemble de l'API redis-py utilise ici) ────────
class _MemoryRedis:
    def __init__(self) -> None:
        self._kv: dict[str, tuple[Any, float | None]] = {}  # key -> (value, expire_at|None)
        self._hash: dict[str, dict[str, str]] = {}
        self._lock = asyncio.Lock()
        # pub/sub in-process : chaque _MemoryPubSub actif s'enregistre ici et
        # recoit dans sa file les messages publies qui matchent ses patterns.
        self._subscribers: set[_MemoryPubSub] = set()

    def _alive(self, key: str) -> bool:
        item = self._kv.get(key)
        if item is None:
            return key in self._hash
        _, exp = item
        if exp is not None and exp < time.monotonic():
            self._kv.pop(key, None)
            self._hash.pop(key, None)
            return False
        return True

    async def ping(self) -> bool:
        return True

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        self._kv[key] = (value, time.monotonic() + ex if ex else None)

    async def get(self, key: str) -> Any:
        return self._kv[key][0] if self._alive(key) and key in self._kv else None

    async def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if self._kv.pop(k, None) is not None or self._hash.pop(k, None) is not None:
                n += 1
        return n

    async def exists(self, key: str) -> int:
        return 1 if self._alive(key) else 0

    async def expire(self, key: str, ttl: int) -> bool:
        if key in self._kv:
            v, _ = self._kv[key]
            self._kv[key] = (v, time.monotonic() + ttl)
            return True
        if key in self._hash:
            # on modelise le TTL d'un hash via une entree kv sentinelle
            self._kv[f"__ttl__:{key}"] = (1, time.monotonic() + ttl)
            return True
        return False

    async def hset(self, key: str, mapping: dict[str, str] | None = None, **kw: str) -> int:
        d = self._hash.setdefault(key, {})
        d.update(mapping or {})
        d.update(kw)
        return len(d)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self._hash.get(key, {}))

    async def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        d = self._hash.setdefault(key, {})
        d[field] = str(int(d.get(field, "0")) + amount)
        return int(d[field])

    async def keys(self, pattern: str = "*") -> list[str]:
        allk = set(self._kv) | set(self._hash)
        return [k for k in allk if fnmatch.fnmatch(k, pattern) and self._alive(k)]

    async def publish(self, channel: str, message: str) -> int:
        # livraison in-process : on pousse dans la file de chaque abonne dont
        # un pattern matche le canal. Suffit pour le temps reel WS mono-worker.
        n = 0
        for sub in list(self._subscribers):
            if sub._matches(channel):  # noqa: SLF001
                sub._queue.put_nowait(  # noqa: SLF001
                    {"type": "pmessage", "pattern": sub._pattern_for(channel),  # noqa: SLF001
                     "channel": channel, "data": message}
                )
                n += 1
        return n

    def pubsub(self) -> _MemoryPubSub:
        return _MemoryPubSub(self)

    def pipeline(self) -> _MemoryPipeline:
        return _MemoryPipeline(self)

    async def aclose(self) -> None:
        self._kv.clear()
        self._hash.clear()


class _MemoryPipeline:
    def __init__(self, r: _MemoryRedis) -> None:
        self._r = r
        self._ops: list[tuple[str, tuple]] = []

    def exists(self, key: str) -> _MemoryPipeline:
        self._ops.append(("exists", (key,)))
        return self

    async def execute(self) -> list[Any]:
        out = []
        for name, args in self._ops:
            out.append(await getattr(self._r, name)(*args))
        self._ops.clear()
        return out


class _MemoryPubSub:
    """Abonnement pub/sub in-process. `listen()` rend les vrais messages
    publies via `_MemoryRedis.publish` (pattern `fnmatch`)."""

    def __init__(self, parent: _MemoryRedis) -> None:
        self._parent = parent
        self._patterns: set[str] = set()
        self._exact: set[str] = set()
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._closed = False

    def _matches(self, channel: str) -> bool:
        if channel in self._exact:
            return True
        return any(fnmatch.fnmatch(channel, p) for p in self._patterns)

    def _pattern_for(self, channel: str) -> str:
        for p in self._patterns:
            if fnmatch.fnmatch(channel, p):
                return p
        return channel

    async def psubscribe(self, *patterns: str, **_k: Any) -> None:
        self._patterns.update(patterns)
        self._parent._subscribers.add(self)  # noqa: SLF001

    async def subscribe(self, *channels: str, **_k: Any) -> None:
        self._exact.update(channels)
        self._parent._subscribers.add(self)  # noqa: SLF001

    async def aclose(self) -> None:
        self._closed = True
        self._parent._subscribers.discard(self)  # noqa: SLF001

    async def listen(self):
        while not self._closed:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=30)
            except asyncio.TimeoutError:
                continue
            yield msg


_memory = _MemoryRedis()


def get_redis() -> Any:
    global _pool, _use_memory
    if _use_memory:
        return _memory
    if _pool is None:
        _pool = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
        )
    return _pool


async def init_redis() -> None:
    """Teste Redis au demarrage ; bascule en memoire si indisponible."""
    global _use_memory
    try:
        await asyncio.wait_for(get_redis().ping(), timeout=2.0)
        log.info("redis.connected")
    except Exception as e:  # pragma: no cover
        _use_memory = True
        log.warning("redis.unavailable_fallback_memory", error=str(e))


async def close_redis() -> None:
    global _pool
    if _pool is not None:
        with contextlib.suppress(Exception):  # pragma: no cover
            await _pool.aclose()
        _pool = None
    await _memory.aclose()


# ── Presence helpers ────────────────────────────────────────────────────────
PRESENCE_TTL = 60  # secondes — le client WS ping toutes les ~30s


async def mark_online(user_id: str) -> None:
    await get_redis().set(f"presence:{user_id}", "1", ex=PRESENCE_TTL)


async def mark_offline(user_id: str) -> None:
    await get_redis().delete(f"presence:{user_id}")


async def is_online(user_id: str) -> bool:
    return await get_redis().exists(f"presence:{user_id}") == 1


async def filter_online(user_ids: list[str]) -> set[str]:
    if not user_ids:
        return set()
    r = get_redis()
    pipe = r.pipeline()
    for uid in user_ids:
        pipe.exists(f"presence:{uid}")
    results = await pipe.execute()
    return {uid for uid, present in zip(user_ids, results, strict=True) if present}
