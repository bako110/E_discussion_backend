"""Upload media : image traitee + miniature, refus type non supporte / trop gros."""
from __future__ import annotations

import io

import pytest
from PIL import Image

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


@pytest.fixture(autouse=True)
def _tmp_media(monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path / "media"))
    return tmp_path


async def _token(client, codes) -> str:
    await client.post("/api/v1/auth/register", json={"phone": "+33600000001"})
    code = codes["last"]
    r = await client.post(
        "/api/v1/auth/verify-registration",
        json={"identifier": "+33600000001", "code": code},
    )
    return r.json()["access_token"]


def _png_bytes(w=1000, h=800) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (30, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


async def test_upload_image_returns_url_and_thumbnail(client, _capture_otp):
    token = await _token(client, _capture_otp)
    h = {"Authorization": f"Bearer {token}"}

    r = await client.post(
        "/api/v1/media/upload",
        headers=h,
        files={"file": ("photo.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["media_type"] == "image"
    assert body["url"].startswith("/media/")
    assert body["thumbnail_url"] and body["thumbnail_url"].startswith("/media/")
    # redimensionne au cote max
    assert max(body["width"], body["height"]) <= 1600
    assert body["size"] > 0


async def test_upload_rejects_unsupported_type(client, _capture_otp):
    token = await _token(client, _capture_otp)
    h = {"Authorization": f"Bearer {token}"}

    r = await client.post(
        "/api/v1/media/upload",
        headers=h,
        files={"file": ("notes.txt", b"hello world", "text/plain")},
    )
    assert r.status_code == 415, r.text


async def test_upload_requires_auth(client):
    r = await client.post(
        "/api/v1/media/upload",
        files={"file": ("photo.png", _png_bytes(10, 10), "image/png")},
    )
    assert r.status_code == 401
