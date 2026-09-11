"""Flux diffusion en direct d'une chaine : demarrage (admin) -> liste ->
rejoindre en spectateur (abonne) -> arret.
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


@pytest.fixture(autouse=True)
def _enable_calls(monkeypatch):
    """Force calls_enabled (LiveKit requis) + stub la generation de token."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "LIVEKIT_URL", "wss://sfu.test", raising=False)
    monkeypatch.setattr(settings, "LIVEKIT_API_KEY", "devkey", raising=False)
    monkeypatch.setattr(settings, "LIVEKIT_API_SECRET", "devsecret", raising=False)

    import app.services.livekit_service as lk

    def _fake_token(*, room_name, identity, display_name=None, ttl=None, publish=True):
        mode = "pub" if publish else "sub"
        return f"jwt-{mode}-for-{identity}-in-{room_name}"

    monkeypatch.setattr(lk, "build_access_token", _fake_token)
    monkeypatch.setattr(lk, "_ensure_ready", lambda: None)


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


async def test_channel_live_start_join_stop(client, _capture_otp):
    owner_token, _ = await _register(client, _capture_otp, "+33655555555")
    sub_token, sub_id = await _register(client, _capture_otp, "+33666666666")
    oh = {"Authorization": f"Bearer {owner_token}"}
    sh = {"Authorization": f"Bearer {sub_token}"}

    # Owner cree une chaine avec l'abonne d'emblee
    r = await client.post(
        "/api/v1/groups",
        json={"kind": "channel", "name": "Ma chaine", "member_ids": [sub_id]},
        headers=oh,
    )
    assert r.status_code == 201, r.text
    group_id = r.json()["id"]

    # pas encore de live pour cette chaine
    r = await client.get(f"/api/v1/groups/{group_id}/live", headers=oh)
    assert r.status_code == 200
    assert r.json() is None

    # l'abonne ne peut pas demarrer un direct (pas admin)
    r = await client.post(f"/api/v1/groups/{group_id}/live", json={}, headers=sh)
    assert r.status_code == 403, r.text

    # l'owner demarre un direct
    r = await client.post(
        f"/api/v1/groups/{group_id}/live", json={"title": "Live du soir"}, headers=oh
    )
    assert r.status_code == 201, r.text
    live = r.json()
    assert live["status"] == "live"
    assert live["title"] == "Live du soir"
    assert live["channel_name"] == "Ma chaine"
    assert live["subscriber_count"] == 2
    assert live["token"].startswith("jwt-pub-")
    room_name = live["room_name"]

    # un 2e demarrage echoue (deja live)
    r = await client.post(f"/api/v1/groups/{group_id}/live", json={}, headers=oh)
    assert r.status_code == 409, r.text

    # la chaine apparait dans la liste "chaines en direct" de l'abonne
    r = await client.get("/api/v1/groups/live", headers=sh)
    assert r.status_code == 200
    assert any(x["group_id"] == group_id for x in r.json())

    # l'abonne rejoint EN SPECTATEUR (token lecture seule, meme room)
    r = await client.post(f"/api/v1/groups/{group_id}/live/join", headers=sh)
    assert r.status_code == 200, r.text
    joined = r.json()
    assert joined["room_name"] == room_name
    assert joined["token"].startswith("jwt-sub-")

    # un non-abonne ne peut pas rejoindre
    other_token, _ = await _register(client, _capture_otp, "+33677777777")
    oth = {"Authorization": f"Bearer {other_token}"}
    r = await client.post(f"/api/v1/groups/{group_id}/live/join", headers=oth)
    assert r.status_code == 403, r.text

    # l'abonne ne peut pas arreter le direct (pas admin)
    r = await client.post(f"/api/v1/groups/{group_id}/live/stop", headers=sh)
    assert r.status_code == 403, r.text

    # l'owner arrete le direct
    r = await client.post(f"/api/v1/groups/{group_id}/live/stop", headers=oh)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ended"

    # plus dans la liste "chaines en direct"
    r = await client.get("/api/v1/groups/live", headers=sh)
    assert r.status_code == 200
    assert not any(x["group_id"] == group_id for x in r.json())

    # rejoindre echoue maintenant (plus live)
    r = await client.post(f"/api/v1/groups/{group_id}/live/join", headers=sh)
    assert r.status_code == 404, r.text

    # un nouveau direct peut redemarrer ensuite
    r = await client.post(f"/api/v1/groups/{group_id}/live", json={}, headers=oh)
    assert r.status_code == 201, r.text
