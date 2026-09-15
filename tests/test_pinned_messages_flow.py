"""Messages épinglés — 1-1 (les deux participants) et groupe (owner/admin
uniquement), limite de 3 épinglés en même temps.
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

    async def _fake_email(to, subject, body):
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


async def _register(client, codes, identifier: str) -> tuple[str, str]:
    r = await client.post("/api/v1/auth/register", json={"phone": identifier})
    assert r.status_code == 201, r.text
    code = codes["last"]
    r = await client.post(
        "/api/v1/auth/verify-registration",
        json={"identifier": identifier, "code": code},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["access_token"], body["user"]["id"]


# ── 1-1 ──────────────────────────────────────────────────────────────────
async def test_pin_unpin_conversation_message(client, _capture_otp):
    alice_token, _ = await _register(client, _capture_otp, "+33644440001")
    bob_token, bob_id = await _register(client, _capture_otp, "+33644440002")
    ah = {"Authorization": f"Bearer {alice_token}"}
    bh = {"Authorization": f"Bearer {bob_token}"}

    r = await client.post(
        "/api/v1/conversations", json={"partner_id": bob_id}, headers=ah
    )
    conv_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"type": "text", "body": "Voici ton mail professionnel"},
        headers=ah,
    )
    msg_id = r.json()["id"]

    # pas encore epingle
    r = await client.get(f"/api/v1/conversations/{conv_id}/pinned", headers=ah)
    assert r.status_code == 200
    assert r.json() == []

    # Bob (l'AUTRE participant, pas l'auteur) peut epingler -- 1-1 : tout le
    # monde peut, pas de notion d'admin a deux.
    r = await client.post(
        f"/api/v1/conversations/{conv_id}/pinned",
        json={"message_id": msg_id},
        headers=bh,
    )
    assert r.status_code == 201, r.text
    assert r.json()["message_id"] == msg_id
    assert r.json()["message"]["body"] == "Voici ton mail professionnel"

    # visible par les deux participants
    r = await client.get(f"/api/v1/conversations/{conv_id}/pinned", headers=ah)
    assert len(r.json()) == 1
    r = await client.get(f"/api/v1/conversations/{conv_id}/pinned", headers=bh)
    assert len(r.json()) == 1

    # ré-épingler le même message est idempotent (pas de doublon)
    r = await client.post(
        f"/api/v1/conversations/{conv_id}/pinned",
        json={"message_id": msg_id},
        headers=ah,
    )
    assert r.status_code == 201, r.text
    r = await client.get(f"/api/v1/conversations/{conv_id}/pinned", headers=ah)
    assert len(r.json()) == 1

    # Alice désépingle
    r = await client.delete(
        f"/api/v1/conversations/{conv_id}/pinned/{msg_id}", headers=ah
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/v1/conversations/{conv_id}/pinned", headers=bh)
    assert r.json() == []


async def test_pin_conversation_limit_3(client, _capture_otp):
    alice_token, _ = await _register(client, _capture_otp, "+33644440003")
    bob_token, bob_id = await _register(client, _capture_otp, "+33644440004")
    ah = {"Authorization": f"Bearer {alice_token}"}

    r = await client.post(
        "/api/v1/conversations", json={"partner_id": bob_id}, headers=ah
    )
    conv_id = r.json()["id"]

    msg_ids = []
    for i in range(4):
        r = await client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            json={"type": "text", "body": f"msg {i}"},
            headers=ah,
        )
        msg_ids.append(r.json()["id"])

    for mid in msg_ids[:3]:
        r = await client.post(
            f"/api/v1/conversations/{conv_id}/pinned",
            json={"message_id": mid},
            headers=ah,
        )
        assert r.status_code == 201, r.text

    # le 4e echoue -- limite atteinte
    r = await client.post(
        f"/api/v1/conversations/{conv_id}/pinned",
        json={"message_id": msg_ids[3]},
        headers=ah,
    )
    assert r.status_code == 409, r.text


# ── groupe ─────────────────────────────────────────────────────────────────
async def test_pin_group_message_admin_only(client, _capture_otp):
    alice_token, _ = await _register(client, _capture_otp, "+33644440005")
    bob_token, bob_id = await _register(client, _capture_otp, "+33644440006")
    ah = {"Authorization": f"Bearer {alice_token}"}
    bh = {"Authorization": f"Bearer {bob_token}"}

    r = await client.post(
        "/api/v1/groups",
        json={"kind": "group", "name": "Epingle", "member_ids": [bob_id]},
        headers=ah,
    )
    group_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/groups/{group_id}/messages",
        json={"type": "text", "body": "Annonce importante"},
        headers=bh,
    )
    msg_id = r.json()["id"]

    # Bob (membre simple, pas admin) ne peut pas epingler
    r = await client.post(
        f"/api/v1/groups/{group_id}/pinned",
        json={"message_id": msg_id},
        headers=bh,
    )
    assert r.status_code == 403, r.text

    # Alice (owner) peut epingler
    r = await client.post(
        f"/api/v1/groups/{group_id}/pinned",
        json={"message_id": msg_id},
        headers=ah,
    )
    assert r.status_code == 201, r.text

    # visible par Bob (simple membre)
    r = await client.get(f"/api/v1/groups/{group_id}/pinned", headers=bh)
    assert len(r.json()) == 1

    # Bob ne peut pas désépingler non plus
    r = await client.delete(
        f"/api/v1/groups/{group_id}/pinned/{msg_id}", headers=bh
    )
    assert r.status_code == 403, r.text

    # Alice désépingle
    r = await client.delete(
        f"/api/v1/groups/{group_id}/pinned/{msg_id}", headers=ah
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"/api/v1/groups/{group_id}/pinned", headers=bh)
    assert r.json() == []
