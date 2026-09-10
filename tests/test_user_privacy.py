"""Parametres de confidentialite : masquage last_seen / photo / about selon
`privacy` + liste des utilisateurs bloques + gating des accuses de lecture.
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
    # is_online / filter_online utilisent get_redis via redis_mod
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


async def test_last_seen_hidden_from_non_contacts(client, _capture_otp):
    alice_token, alice_id = await _register(client, _capture_otp, "+33681111111")
    bob_token, _ = await _register(client, _capture_otp, "+33682222222")
    ah = {"Authorization": f"Bearer {alice_token}"}
    bh = {"Authorization": f"Bearer {bob_token}"}

    # Alice se donne une photo + un about
    await client.patch(
        "/api/v1/users/me",
        json={"avatar_url": "https://x/a.jpg", "about": "hello"},
        headers=ah,
    )

    # par defaut 'everyone' -> Bob (non contact) voit tout
    r = await client.get(f"/api/v1/users/{alice_id}", headers=bh)
    assert r.json()["avatar_url"] == "https://x/a.jpg"
    assert r.json()["about"] == "hello"

    # Alice restreint aux contacts
    await client.patch(
        "/api/v1/users/me",
        json={
            "profile_photo_privacy": "contacts",
            "about_privacy": "nobody",
            "last_seen_privacy": "contacts",
        },
        headers=ah,
    )

    # Bob n'est pas contact -> photo + about + presence masques
    r = await client.get(f"/api/v1/users/{alice_id}", headers=bh)
    body = r.json()
    assert body["avatar_url"] is None
    assert body["about"] is None
    assert body["last_seen_at"] is None
    assert body["is_online"] is False

    # Alice elle-meme voit toujours ses propres champs
    r = await client.get("/api/v1/auth/me", headers=ah)
    me = r.json()
    assert me["profile_photo_privacy"] == "contacts"
    assert me["about_privacy"] == "nobody"


async def test_blocked_users_list(client, _capture_otp):
    alice_token, _ = await _register(client, _capture_otp, "+33683333333")
    bob_token, bob_id = await _register(client, _capture_otp, "+33684444444")
    ah = {"Authorization": f"Bearer {alice_token}"}

    r = await client.get("/api/v1/users/blocked", headers=ah)
    assert r.status_code == 200
    assert r.json() == []

    await client.post(f"/api/v1/users/{bob_id}/block", headers=ah)
    r = await client.get("/api/v1/users/blocked", headers=ah)
    assert [u["id"] for u in r.json()] == [bob_id]

    await client.delete(f"/api/v1/users/{bob_id}/block", headers=ah)
    r = await client.get("/api/v1/users/blocked", headers=ah)
    assert r.json() == []


async def test_block_hides_profile_and_blocks_contact(client, _capture_otp):
    """Bloquer quelqu'un = il ne voit plus ma photo / mes infos / ma presence,
    et ne peut plus me contacter (messages)."""
    alice_token, alice_id = await _register(client, _capture_otp, "+33687777777")
    bob_token, bob_id = await _register(client, _capture_otp, "+33688888888")
    ah = {"Authorization": f"Bearer {alice_token}"}
    bh = {"Authorization": f"Bearer {bob_token}"}

    # Alice a une photo + un about, visibilite 'everyone'
    await client.patch(
        "/api/v1/users/me",
        json={"avatar_url": "https://x/a.jpg", "about": "hey"},
        headers=ah,
    )
    # Bob voit tout AVANT le blocage
    r = await client.get(f"/api/v1/users/{alice_id}", headers=bh)
    assert r.json()["avatar_url"] == "https://x/a.jpg"
    assert r.json()["about"] == "hey"

    # Alice bloque Bob
    r = await client.post(f"/api/v1/users/{bob_id}/block", headers=ah)
    assert r.status_code == 200

    # Bob ne voit plus la photo / about / presence d'Alice
    r = await client.get(f"/api/v1/users/{alice_id}", headers=bh)
    body = r.json()
    assert body["avatar_url"] is None
    assert body["about"] is None
    assert body["last_seen_at"] is None
    assert body["is_online"] is False

    # Bob ne peut plus creer de conversation / envoyer un message a Alice
    r = await client.post(
        "/api/v1/conversations", json={"partner_id": alice_id}, headers=bh
    )
    assert r.status_code == 403

    # Alice non plus dans l'autre sens (le blocage coupe les deux cotes)
    r = await client.post(
        "/api/v1/conversations", json={"partner_id": bob_id}, headers=ah
    )
    assert r.status_code == 403

    # Apres deblocage, Bob revoit le profil
    await client.delete(f"/api/v1/users/{bob_id}/block", headers=ah)
    r = await client.get(f"/api/v1/users/{alice_id}", headers=bh)
    assert r.json()["avatar_url"] == "https://x/a.jpg"


async def test_read_receipts_toggle_persists(client, _capture_otp):
    token, _ = await _register(client, _capture_otp, "+33685555555")
    h = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/v1/auth/me", headers=h)
    assert r.json()["read_receipts"] is True

    r = await client.patch("/api/v1/users/me", json={"read_receipts": False}, headers=h)
    assert r.json()["read_receipts"] is False

    r = await client.get("/api/v1/auth/me", headers=h)
    assert r.json()["read_receipts"] is False


async def test_invalid_privacy_level_rejected(client, _capture_otp):
    token, _ = await _register(client, _capture_otp, "+33686666666")
    h = {"Authorization": f"Bearer {token}"}
    r = await client.patch(
        "/api/v1/users/me", json={"last_seen_privacy": "friends"}, headers=h
    )
    assert r.status_code == 422
