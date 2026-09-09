"""Flux bout-en-bout : inscription e-mail + OTP -> connexion -> conversation ->
message -> lecture. Le code OTP est recupere depuis Redis via un fake.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class _FakeRedis:
    """Redis minimal en memoire pour les tests (hset/hgetall/expire/set/exists/
    delete/hincrby/publish/ping)."""

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
    """Intercepte l'envoi d'e-mail/SMS et expose le dernier code."""
    codes: dict[str, str] = {}

    async def _fake_email(to, subject, body):
        # le corps contient "...code est : 123456" / "code is: 123456"
        for token in body.replace("\n", " ").split():
            if token.isdigit() and len(token) == 6:
                codes["last"] = token

    async def _fake_sms(to, body):
        for token in body.split():
            digits = token.strip(".")
            if digits.isdigit() and len(digits) == 6:
                codes["last"] = digits

    import app.services.otp_service as otp_mod

    monkeypatch.setattr(otp_mod, "send_email", _fake_email)
    monkeypatch.setattr(otp_mod, "send_sms", _fake_sms)
    return codes


async def test_email_register_then_message(client, _capture_otp):
    # 1. inscription
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "s3cret-pass", "display_name": "Alice"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["verification_channel"] == "email"
    code = _capture_otp["last"]
    assert code

    # 2. verification -> tokens
    r = await client.post(
        "/api/v1/auth/verify-registration",
        json={"identifier": "alice@example.com", "code": code},
    )
    assert r.status_code == 200, r.text
    alice_token = r.json()["access_token"]
    assert r.json()["user"]["email"] == "alice@example.com"

    # 3. Bob s'inscrit par telephone
    r = await client.post("/api/v1/auth/register", json={"phone": "+33612345678"})
    assert r.status_code == 201, r.text
    assert r.json()["verification_channel"] == "sms"
    bob_code = _capture_otp["last"]
    r = await client.post(
        "/api/v1/auth/verify-registration",
        json={"identifier": "+33612345678", "code": bob_code},
    )
    assert r.status_code == 200, r.text
    bob_token = r.json()["access_token"]
    bob_id = r.json()["user"]["id"]

    ah = {"Authorization": f"Bearer {alice_token}"}
    bh = {"Authorization": f"Bearer {bob_token}"}

    # 4. Alice ouvre une conversation avec Bob
    r = await client.post("/api/v1/conversations", json={"partner_id": bob_id}, headers=ah)
    assert r.status_code == 201, r.text
    conv_id = r.json()["id"]
    assert r.json()["request_status"] == "pending_outgoing"

    # 5. Alice envoie un message
    r = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"type": "text", "body": "Salut Bob !"},
        headers=ah,
    )
    assert r.status_code == 201, r.text
    msg_id = r.json()["id"]

    # 6. Bob voit la conversation avec 1 non-lu
    r = await client.get("/api/v1/conversations", headers=bh)
    assert r.status_code == 200
    convs = r.json()
    assert len(convs) == 1
    assert convs[0]["unread_count"] == 1
    assert convs[0]["last_message"] == "Salut Bob !"
    assert convs[0]["request_status"] == "pending_incoming"

    # 7. Bob accepte puis lit
    r = await client.post(f"/api/v1/conversations/{conv_id}/accept", headers=bh)
    assert r.status_code == 200, r.text
    r = await client.put(f"/api/v1/conversations/{conv_id}/read", headers=bh)
    assert r.status_code == 200

    r = await client.get("/api/v1/conversations", headers=bh)
    assert r.json()[0]["unread_count"] == 0
    assert r.json()[0]["request_status"] == "accepted"

    # 8. Bob reagit au message d'Alice
    r = await client.post(f"/api/v1/messages/{msg_id}/react", json={"emoji": "👍"}, headers=bh)
    assert r.status_code == 200, r.text

    # 9. Idempotence offline : rejeu du meme client_id -> pas de doublon
    cid = "offline-abc-123"
    first = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"type": "text", "body": "Rejeu", "client_id": cid},
        headers=ah,
    )
    assert first.status_code == 201, first.text
    replay = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"type": "text", "body": "Rejeu", "client_id": cid},
        headers=ah,
    )
    assert replay.status_code in (200, 201)
    assert replay.json()["id"] == first.json()["id"]

    # delta sync : since = maintenant -1s renvoie au moins le dernier message
    r = await client.get(
        f"/api/v1/conversations/{conv_id}/messages?since=2000-01-01T00:00:00Z",
        headers=ah,
    )
    assert r.status_code == 200
    assert len(r.json()) >= 1


async def test_login_wrong_password(client, _capture_otp):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "carol@example.com", "password": "correct-horse"},
    )
    code = _capture_otp["last"]
    await client.post(
        "/api/v1/auth/verify-registration",
        json={"identifier": "carol@example.com", "code": code},
    )
    r = await client.post(
        "/api/v1/auth/login",
        json={"identifier": "carol@example.com", "password": "wrong"},
    )
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "invalid_credentials"
