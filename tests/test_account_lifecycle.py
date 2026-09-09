"""Cycle de vie du compte : sync du carnet -> contacts sur l'app, export des
donnees, suppression definitive (cascade)."""
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


async def _register(client, codes, phone: str) -> tuple[str, str]:
    await client.post("/api/v1/auth/register", json={"phone": phone})
    code = codes["last"]
    r = await client.post(
        "/api/v1/auth/verify-registration",
        json={"identifier": phone, "code": code},
    )
    body = r.json()
    return body["access_token"], body["user"]["id"]


async def test_contact_sync_returns_only_registered(client, _capture_otp):
    alice_token, _ = await _register(client, _capture_otp, "+22670000010")
    bob_token, bob_id = await _register(client, _capture_otp, "+22670000011")
    ah = {"Authorization": f"Bearer {alice_token}"}

    # Alice synchronise : un numero qui EST sur l'app (Bob) + un inconnu
    r = await client.post(
        "/api/v1/contacts/sync",
        json={
            "contacts": [
                {"phone": "+22670000011", "display_name": "Bob Perso"},
                {"phone": "+22670000099", "display_name": "Inconnu"},
            ]
        },
        headers=ah,
    )
    assert r.status_code == 200, r.text
    matches = r.json()
    # seuls les numeros ayant un compte sont renvoyes (l'inconnu est ecarte)
    assert len(matches) == 1
    assert matches[0]["phone"] == "+22670000011"
    assert matches[0]["user"]["id"] == bob_id
    assert matches[0]["display_name"] == "Bob Perso"


async def test_export_my_data(client, _capture_otp):
    token, _ = await _register(client, _capture_otp, "+22670000012")
    h = {"Authorization": f"Bearer {token}"}

    await client.patch("/api/v1/users/me", json={"about": "hello"}, headers=h)
    r = await client.get("/api/v1/auth/me/export", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["format_version"] == 1
    assert data["profile"]["about"] == "hello"
    assert "conversations" in data and "stories" in data and "groups" in data


async def test_delete_account_cascades(client, _capture_otp):
    alice_token, alice_id = await _register(client, _capture_otp, "+22670000013")
    bob_token, bob_id = await _register(client, _capture_otp, "+22670000014")
    ah = {"Authorization": f"Bearer {alice_token}"}
    bh = {"Authorization": f"Bearer {bob_token}"}

    # Alice cree une conversation + un message + une story
    r = await client.post("/api/v1/conversations", json={"partner_id": bob_id}, headers=ah)
    conv_id = r.json()["id"]
    await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"type": "text", "body": "coucou"},
        headers=ah,
    )
    await client.post(
        "/api/v1/stories", json={"media_type": "text", "caption": "hi"}, headers=ah
    )

    # suppression
    r = await client.delete("/api/v1/auth/me", headers=ah)
    assert r.status_code == 200, r.text
    assert r.json()["message"] == "account_deleted"

    # le token d'Alice ne marche plus
    r = await client.get("/api/v1/auth/me", headers=ah)
    assert r.status_code == 401

    # Bob ne voit plus Alice (compte + conversation supprimes en cascade)
    r = await client.get(f"/api/v1/users/{alice_id}", headers=bh)
    assert r.status_code == 404
    r = await client.get("/api/v1/conversations", headers=bh)
    assert all(c["id"] != conv_id for c in r.json())
