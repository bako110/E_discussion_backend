"""Cles E2EE : modele single-device — un nouvel appareil revoque l'ancien,
`bundles` ne sert que l'appareil actif le plus recent.
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


async def _register(client, codes, phone: str) -> tuple[str, str]:
    await client.post("/api/v1/auth/register", json={"phone": phone})
    code = codes["last"]
    r = await client.post(
        "/api/v1/auth/verify-registration",
        json={"identifier": phone, "code": code},
    )
    body = r.json()
    return body["access_token"], body["user"]["id"]


def _keys_payload(device_id: str, spk_id: int = 1) -> dict:
    b64 = "A" * 43 + "="  # 32 octets base64 factices — le backend ne les valide pas
    return {
        "device_id": device_id,
        "device_label": "Test",
        "identity_public_key": b64,
        "identity_signing_key": b64,
        "signed_prekey_id": spk_id,
        "signed_prekey": b64,
        "prekey_signature": b64,
        "registration_id": 12345,
        "one_time_prekeys": [{"key_id": 100 + i, "public_key": b64} for i in range(5)],
    }


async def test_new_device_revokes_previous_and_bundle_is_latest(client, _capture_otp):
    a_token, _ = await _register(client, _capture_otp, "+33612345680")
    b_token, b_id = await _register(client, _capture_otp, "+33612345681")
    ah = {"Authorization": f"Bearer {a_token}"}
    bh = {"Authorization": f"Bearer {b_token}"}

    # B enregistre un 1er appareil
    r = await client.post("/api/v1/devices/keys", json=_keys_payload("dev-1", 1), headers=bh)
    assert r.status_code in (200, 201)

    # A recupere le bundle de B -> un seul appareil, dev-1
    r = await client.get(f"/api/v1/devices/{b_id}/bundles", headers=ah)
    bundles = r.json()
    assert [d["device_id"] for d in bundles] == ["dev-1"]

    # B reinstalle : nouvel appareil dev-2
    r = await client.post("/api/v1/devices/keys", json=_keys_payload("dev-2", 2), headers=bh)
    assert r.status_code in (200, 201)

    # bundles ne renvoie QUE dev-2 (dev-1 revoque)
    r = await client.get(f"/api/v1/devices/{b_id}/bundles", headers=ah)
    bundles = r.json()
    assert [d["device_id"] for d in bundles] == ["dev-2"]
    assert bundles[0]["signed_prekey_id"] == 2

    # la liste des appareils de B montre dev-1 revoque, dev-2 actif
    r = await client.get("/api/v1/devices/me", headers=bh)
    devs = {d["device_id"]: d["revoked"] for d in r.json()}
    assert devs.get("dev-1") is True
    assert devs.get("dev-2") is False
