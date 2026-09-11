"""Stories : idempotence de la publication offline (client_id).

Un rejeu de l'outbox (retry apres reconnexion) avec le meme client_id ne
doit PAS creer une 2e story — condition necessaire pour rendre la
publication de statut local-first cote client sans risquer de doublons.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    async def ping(self):
        return True

    async def set(self, k, v, ex=None):
        self.store[k] = v

    async def get(self, k):
        return self.store.get(k)

    async def exists(self, k):
        return 1 if k in self.store else 0

    async def delete(self, *ks):
        for k in ks:
            self.store.pop(k, None)

    async def hset(self, k, mapping=None, **kw):
        d = self.store.setdefault(k, {})
        d.update(mapping or {})
        d.update(kw)

    async def hgetall(self, k):
        return dict(self.store.get(k, {}))

    async def hincrby(self, k, field, amount=1):
        d = self.store.setdefault(k, {})
        d[field] = str(int(d.get(field, "0")) + amount)
        return int(d[field])

    async def expire(self, k, ttl):
        return True

    async def publish(self, channel, msg):
        return 0

    def pipeline(self):
        return self

    async def execute(self):
        return []


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch):
    fake = _FakeRedis()
    import app.db.redis as redis_mod
    import app.services.otp_service as otp_mod
    import app.services.ws_manager as ws_mod

    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake)
    monkeypatch.setattr(otp_mod, "get_redis", lambda: fake)
    monkeypatch.setattr(ws_mod, "get_redis", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _capture_otp(monkeypatch):
    codes: dict[str, str] = {}

    async def _fake_sms(to, body):
        for token in body.split():
            digits = token.strip(".")
            if digits.isdigit() and len(digits) == 6:
                codes["last"] = digits

    import app.services.otp_service as otp_mod

    monkeypatch.setattr(otp_mod, "send_sms", _fake_sms)
    return codes


async def _register(client, codes, identifier: str) -> str:
    r = await client.post("/api/v1/auth/register", json={"phone": identifier})
    assert r.status_code == 201, r.text
    code = codes["last"]
    r = await client.post(
        "/api/v1/auth/verify-registration",
        json={"identifier": identifier, "code": code},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def test_story_create_idempotent_by_client_id(client, _capture_otp):
    token = await _register(client, _capture_otp, "+33699999901")
    h = {"Authorization": f"Bearer {token}"}

    payload = {
        "media_type": "text",
        "caption": "Salut !",
        "background_color": "#FF0000",
        "duration_sec": 5,
        "client_id": "outbox-abc-123",
    }

    r1 = await client.post("/api/v1/stories", json=payload, headers=h)
    assert r1.status_code == 201, r1.text
    story1 = r1.json()

    # rejeu (comme le ferait l'outbox après reconnexion) — même client_id
    r2 = await client.post("/api/v1/stories", json=payload, headers=h)
    assert r2.status_code == 201, r2.text
    story2 = r2.json()

    # même story renvoyée, pas de doublon
    assert story1["id"] == story2["id"]

    r3 = await client.get("/api/v1/stories/mine", headers=h)
    assert r3.status_code == 200, r3.text
    mine = r3.json()
    assert len([s for s in mine if s["id"] == story1["id"]]) == 1


async def test_story_create_without_client_id_still_works(client, _capture_otp):
    token = await _register(client, _capture_otp, "+33699999902")
    h = {"Authorization": f"Bearer {token}"}

    r1 = await client.post(
        "/api/v1/stories",
        json={"media_type": "text", "caption": "Sans client_id", "duration_sec": 5},
        headers=h,
    )
    assert r1.status_code == 201, r1.text

    # une 2e story sans client_id (None) ne doit pas être bloquée par
    # l'unicité (author_id, client_id) — plusieurs NULL sont distincts.
    r2 = await client.post(
        "/api/v1/stories",
        json={"media_type": "text", "caption": "Encore une", "duration_sec": 5},
        headers=h,
    )
    assert r2.status_code == 201, r2.text
    assert r1.json()["id"] != r2.json()["id"]
