"""Flux groupes & chaines : creation -> invitation -> adhesion -> message.

Reprend le fake Redis / OTP de test_auth_flow via des fixtures locales
simplifiees (deux comptes crees par telephone).
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


async def test_group_create_join_message(client, _capture_otp):
    alice_token, _ = await _register(client, _capture_otp, "+33611111111")
    bob_token, bob_id = await _register(client, _capture_otp, "+33622222222")
    ah = {"Authorization": f"Bearer {alice_token}"}
    bh = {"Authorization": f"Bearer {bob_token}"}

    # Alice cree un groupe avec Bob d'emblee
    r = await client.post(
        "/api/v1/groups",
        json={"kind": "group", "name": "Team", "member_ids": [bob_id]},
        headers=ah,
    )
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["kind"] == "group"
    assert g["member_count"] == 2
    assert g["my_role"] == "owner"
    assert g["can_post"] is True
    group_id = g["id"]
    code = g["invite_code"]

    # Bob voit le groupe dans sa liste
    r = await client.get("/api/v1/groups", headers=bh)
    assert r.status_code == 200
    assert any(x["id"] == group_id for x in r.json())

    # Alice publie un message
    r = await client.post(
        f"/api/v1/groups/{group_id}/messages",
        json={"type": "text", "body": "Bonjour l'équipe"},
        headers=ah,
    )
    assert r.status_code == 201, r.text
    assert r.json()["body"] == "Bonjour l'équipe"

    # Bob lit l'historique
    r = await client.get(f"/api/v1/groups/{group_id}/messages", headers=bh)
    assert r.status_code == 200
    bodies = [m["body"] for m in r.json()]
    assert "Bonjour l'équipe" in bodies

    # Bob a un non-lu, puis marque lu
    r = await client.get("/api/v1/groups", headers=bh)
    grp = next(x for x in r.json() if x["id"] == group_id)
    assert grp["unread_count"] >= 1
    r = await client.put(f"/api/v1/groups/{group_id}/read", headers=bh)
    assert r.status_code == 200

    # Bob quitte
    r = await client.post(f"/api/v1/groups/{group_id}/leave", headers=bh)
    assert r.status_code == 200
    r = await client.get("/api/v1/groups", headers=bh)
    assert not any(x["id"] == group_id for x in r.json())

    # idempotence de l'invite : Bob rejoint via le code
    r = await client.post("/api/v1/groups/join", json={"invite_code": code}, headers=bh)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == group_id


async def test_channel_read_only_for_subscribers(client, _capture_otp):
    alice_token, _ = await _register(client, _capture_otp, "+33633333333")
    bob_token, bob_id = await _register(client, _capture_otp, "+33644444444")
    ah = {"Authorization": f"Bearer {alice_token}"}
    bh = {"Authorization": f"Bearer {bob_token}"}

    r = await client.post(
        "/api/v1/groups",
        json={"kind": "channel", "name": "News", "member_ids": [bob_id]},
        headers=ah,
    )
    assert r.status_code == 201, r.text
    ch = r.json()
    channel_id = ch["id"]

    # Alice (owner) publie
    r = await client.post(
        f"/api/v1/groups/{channel_id}/messages",
        json={"type": "text", "body": "Édition du jour"},
        headers=ah,
    )
    assert r.status_code == 201, r.text

    # Bob (subscriber) NE PEUT PAS publier
    r = await client.get(f"/api/v1/groups/{channel_id}", headers=bh)
    assert r.json()["can_post"] is False
    r = await client.post(
        f"/api/v1/groups/{channel_id}/messages",
        json={"type": "text", "body": "coucou"},
        headers=bh,
    )
    assert r.status_code == 403, r.text

    # ... mais il lit
    r = await client.get(f"/api/v1/groups/{channel_id}/messages", headers=bh)
    assert r.status_code == 200
    assert any(m["body"] == "Édition du jour" for m in r.json())


async def test_group_preview_by_code(client, _capture_otp):
    alice_token, _ = await _register(client, _capture_otp, "+33655555555")
    bob_token, _ = await _register(client, _capture_otp, "+33666666666")
    ah = {"Authorization": f"Bearer {alice_token}"}
    bh = {"Authorization": f"Bearer {bob_token}"}

    r = await client.post(
        "/api/v1/groups", json={"kind": "group", "name": "Secret"}, headers=ah
    )
    code = r.json()["invite_code"]

    r = await client.get(f"/api/v1/groups/preview?code={code}", headers=bh)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["name"] == "Secret"
    assert p["is_member"] is False
    assert p["member_count"] == 1

    # code inconnu -> 404
    r = await client.get("/api/v1/groups/preview?code=zzzzzzzz", headers=bh)
    assert r.status_code == 404


async def test_group_settings_and_join_approval(client, _capture_otp):
    """Paramètres admin : message admins-only + adhésion sous approbation."""
    admin_token, _ = await _register(client, _capture_otp, "+33677777701")
    user_token, user_id = await _register(client, _capture_otp, "+33677777702")
    ah = {"Authorization": f"Bearer {admin_token}"}
    uh = {"Authorization": f"Bearer {user_token}"}

    g = (
        await client.post(
            "/api/v1/groups", json={"kind": "group", "name": "Réglé"}, headers=ah
        )
    ).json()
    gid, code = g["id"], g["invite_code"]

    # défauts
    r = await client.get(f"/api/v1/groups/{gid}/settings", headers=ah)
    s = r.json()
    assert s["send_messages_policy"] == "all"
    assert s["join_approval_required"] is False

    # un non-admin ne voit pas les paramètres
    r = await client.get(f"/api/v1/groups/{gid}/settings", headers=uh)
    assert r.status_code == 403

    # active : messages admins-only + approbation requise
    r = await client.put(
        f"/api/v1/groups/{gid}/settings",
        json={"send_messages_policy": "admins", "join_approval_required": True},
        headers=ah,
    )
    assert r.status_code == 200, r.text
    assert r.json()["send_messages_policy"] == "admins"

    # user tente de rejoindre -> mis en attente (403 join_pending)
    r = await client.post(
        "/api/v1/groups/join", json={"invite_code": code}, headers=uh
    )
    assert r.status_code == 403

    # l'admin voit la demande
    r = await client.get(f"/api/v1/groups/{gid}/join-requests", headers=ah)
    reqs = r.json()
    assert [x["user"]["id"] for x in reqs] == [user_id]

    # l'admin approuve
    r = await client.post(
        f"/api/v1/groups/{gid}/join-requests/{user_id}/approve", headers=ah
    )
    assert r.status_code == 200

    # user est maintenant membre mais ne peut pas écrire (admins-only)
    r = await client.get("/api/v1/groups", headers=uh)
    mine = next(x for x in r.json() if x["id"] == gid)
    assert mine["my_role"] == "member"
    assert mine["can_post"] is False

    r = await client.post(
        f"/api/v1/groups/{gid}/messages",
        json={"type": "text", "body": "coucou"},
        headers=uh,
    )
    assert r.status_code == 403

    # plus de demande en attente
    r = await client.get(f"/api/v1/groups/{gid}/join-requests", headers=ah)
    assert r.json() == []
