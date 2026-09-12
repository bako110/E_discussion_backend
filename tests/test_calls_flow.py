"""Flux appels WebRTC : start -> ring -> accept/reject -> hangup -> history.

Le SFU LiveKit n'est pas requis : on stub la generation de token et on force
`calls_enabled`. On verifie surtout la signalisation (events WS) et
l'historisation (statut, duree, direction).
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}
        self.published: list[tuple[str, str]] = []

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
        self.published.append((channel, msg))
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


@pytest.fixture()
def _push_calls():
    """Capture tous les appels à push_service.push_to_user (appels)."""
    return []


@pytest.fixture(autouse=True)
def _enable_calls(monkeypatch, _push_calls):
    """Force calls_enabled + stub la generation de token LiveKit."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "LIVEKIT_URL", "wss://sfu.test", raising=False)
    monkeypatch.setattr(settings, "LIVEKIT_API_KEY", "devkey", raising=False)
    monkeypatch.setattr(settings, "LIVEKIT_API_SECRET", "devsecret", raising=False)

    import app.services.livekit_service as lk

    def _fake_token(*, room_name, identity, display_name=None, ttl=None):
        return f"jwt-for-{identity}-in-{room_name}"

    monkeypatch.setattr(lk, "build_access_token", _fake_token)
    monkeypatch.setattr(lk, "_ensure_ready", lambda: None)

    import app.services.call_service as call_mod

    async def _fake_push(db, user_id, *, title, body, data=None, high_priority=True):
        _push_calls.append({"user_id": str(user_id), "data": dict(data or {})})

    monkeypatch.setattr(call_mod.push_service, "push_to_user", _fake_push)


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


def _events(redis, user_id: str) -> list[dict]:
    import json

    out = []
    for ch, msg in redis.published:
        if ch == f"ws:user:{user_id}":
            out.append(json.loads(msg))
    return out


def _pushes_for(push_calls, user_id: str, ptype: str) -> list[dict]:
    return [
        p["data"] for p in push_calls if p["user_id"] == user_id and p["data"].get("type") == ptype
    ]


async def test_call_ring_accept_hangup(client, _capture_otp, _patch_redis, _push_calls):
    a_token, a_id = await _register(client, _capture_otp, "+33611111111")
    b_token, b_id = await _register(client, _capture_otp, "+33622222222")
    ah = {"Authorization": f"Bearer {a_token}"}
    bh = {"Authorization": f"Bearer {b_token}"}

    # config exposee au client
    r = await client.get("/api/v1/calls/config", headers=ah)
    assert r.status_code == 200
    assert r.json()["enabled"] is True
    assert r.json()["livekit_url"] == "wss://sfu.test"

    # A appelle B (video) avec une cle E2EE fournie par le client
    r = await client.post(
        "/api/v1/calls",
        json={"callee_id": b_id, "call_type": "video", "e2ee_key": "BASE64KEY=="},
        headers=ah,
    )
    assert r.status_code == 201, r.text
    call = r.json()
    call_id = call["id"]
    assert call["status"] == "ringing"
    assert call["room_name"].startswith("call_")
    assert call["token"].startswith("jwt-for-")
    assert call["livekit_url"] == "wss://sfu.test"

    # B a recu l'event call.incoming avec la cle E2EE relayee
    incoming = [e for e in _events(_patch_redis, b_id) if e["type"] == "call.incoming"]
    assert len(incoming) == 1
    assert incoming[0]["call_id"] == call_id
    assert incoming[0]["e2ee_key"] == "BASE64KEY=="
    assert incoming[0]["call_type"] == "video"
    # push FCM data-only envoyé EN PLUS du WS au démarrage (couvre le cas où
    # le destinataire a son app tuée : le WS seul ne suffit pas à le réveiller).
    assert len(_pushes_for(_push_calls, b_id, "call.incoming")) == 1

    # B accepte -> recoit son propre token, A est notifie (WS + push, pour
    # que l'appelant puisse fermer son écran de sonnerie même app tuée)
    r = await client.post(f"/api/v1/calls/{call_id}/accept", headers=bh)
    assert r.status_code == 200, r.text
    acc = r.json()
    assert acc["token"].startswith("jwt-for-")
    assert acc["room_name"] == call["room_name"]
    assert acc["e2ee_key"] == "BASE64KEY=="
    assert any(e["type"] == "call.accepted" for e in _events(_patch_redis, a_id))
    assert len(_pushes_for(_push_calls, a_id, "call.accepted")) == 1

    # A raccroche -> appel 'ended', B notifie (WS + push)
    r = await client.post(f"/api/v1/calls/{call_id}/hangup", headers=ah)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ended"
    assert any(e["type"] == "call.ended" for e in _events(_patch_redis, b_id))
    ended_pushes = _pushes_for(_push_calls, b_id, "call.ended")
    assert len(ended_pushes) == 1
    assert ended_pushes[0]["call_id"] == call_id

    # historique cote B : l'appel apparait avec le peer = A
    r = await client.get("/api/v1/calls", headers=bh)
    assert r.status_code == 200
    hist = r.json()
    assert len(hist) == 1
    assert hist[0]["id"] == call_id
    assert hist[0]["status"] == "ended"
    assert hist[0]["peer"]["id"] == a_id


async def test_call_rejected(client, _capture_otp, _patch_redis, _push_calls):
    a_token, a_id = await _register(client, _capture_otp, "+33633333333")
    b_token, b_id = await _register(client, _capture_otp, "+33644444444")
    ah = {"Authorization": f"Bearer {a_token}"}
    bh = {"Authorization": f"Bearer {b_token}"}

    r = await client.post(
        "/api/v1/calls", json={"callee_id": b_id, "call_type": "voice"}, headers=ah
    )
    call_id = r.json()["id"]

    r = await client.post(f"/api/v1/calls/{call_id}/reject", headers=bh)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "rejected"
    assert any(e["type"] == "call.rejected" for e in _events(_patch_redis, a_id))
    assert len(_pushes_for(_push_calls, a_id, "call.rejected")) == 1

    # A ne peut pas accepter/raccrocher un appel deja termine cote signalisation
    r = await client.post(f"/api/v1/calls/{call_id}/accept", headers=bh)
    assert r.status_code == 409

    # suppression de l'entree d'historique
    r = await client.delete(f"/api/v1/calls/{call_id}", headers=ah)
    assert r.status_code == 200
    r = await client.get("/api/v1/calls", headers=ah)
    assert r.json() == []


async def test_call_ring_timeout_pushes_both_sides(
    client, _capture_otp, _patch_redis, _push_calls, db_session
):
    """Le timeout serveur de sonnerie (pas de reponse) doit fermer la
    notification plein ecran des DEUX cotes meme si leur app a ete tuee
    entre-temps — donc pousser un FCM aux deux, pas seulement un WS."""
    a_token, a_id = await _register(client, _capture_otp, "+33677777777")
    b_token, b_id = await _register(client, _capture_otp, "+33688888888")
    ah = {"Authorization": f"Bearer {a_token}"}

    r = await client.post(
        "/api/v1/calls", json={"callee_id": b_id, "call_type": "voice"}, headers=ah
    )
    call_id = r.json()["id"]

    import app.services.call_service as call_mod

    await call_mod.expire_ringing(db_session, uuid.UUID(call_id))
    await db_session.commit()

    for uid in (a_id, b_id):
        pushes = _pushes_for(_push_calls, uid, "call.ended")
        assert len(pushes) == 1
        assert pushes[0]["status"] == "missed"
        assert pushes[0]["call_id"] == call_id


async def _age_call(db_session, call_id: str, seconds: int) -> None:
    """Recule started_at de `seconds` pour simuler un vieil appel sans
    attendre en vrai — sert à tester le filet de sécurité indépendamment du
    timer in-process (qu'on ne réarme volontairement PAS dans ces tests)."""
    from datetime import UTC, datetime, timedelta

    import app.services.call_service as call_mod
    from app.db.models.call import CallLog

    call = await db_session.get(CallLog, uuid.UUID(call_id))
    call_mod._cancel_ring_timer(call.id)  # on ne veut PAS que le timer réel interfère
    call.started_at = datetime.now(UTC) - timedelta(seconds=seconds)
    await db_session.flush()


async def test_stale_ringing_call_expires_on_next_touch(
    client, _capture_otp, _patch_redis, _push_calls, db_session
):
    """Filet de sécurité `_maybe_expire_stale` (via `_load`) : un appel
    resté 'ringing' plus longtemps que CALL_RING_TIMEOUT doit s'auto-expirer
    dès qu'une requête le touche (ici un simple GET), MÊME SI le timer
    in-process n'a jamais tourné — reproduit le bug observé en prod où le
    timer asyncio ne s'est jamais déclenché."""
    a_token, a_id = await _register(client, _capture_otp, "+33611112222")
    b_token, b_id = await _register(client, _capture_otp, "+33622223333")
    ah = {"Authorization": f"Bearer {a_token}"}

    r = await client.post(
        "/api/v1/calls", json={"callee_id": b_id, "call_type": "voice"}, headers=ah
    )
    call_id = r.json()["id"]
    assert r.json()["status"] == "ringing"

    from app.core.config import settings

    await _age_call(db_session, call_id, settings.CALL_RING_TIMEOUT + 5)
    await db_session.commit()

    # simple consultation -> _load -> _maybe_expire_stale doit corriger l'état
    r = await client.get(f"/api/v1/calls/{call_id}", headers=ah)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "missed"


async def test_sweep_stale_ringing_calls(
    client, _capture_otp, _patch_redis, _push_calls, db_session
):
    """Filet de sécurité de dernier recours (balayage périodique, voir
    app.main lifespan) : expire un appel bloqué sans qu'AUCUNE requête ne le
    touche jamais (personne ne consulte/accepte/rejette/annule)."""
    a_token, a_id = await _register(client, _capture_otp, "+33611114444")
    b_token, b_id = await _register(client, _capture_otp, "+33622225555")
    ah = {"Authorization": f"Bearer {a_token}"}

    r = await client.post(
        "/api/v1/calls", json={"callee_id": b_id, "call_type": "voice"}, headers=ah
    )
    call_id = r.json()["id"]

    from app.core.config import settings

    await _age_call(db_session, call_id, settings.CALL_RING_TIMEOUT + 5)
    await db_session.commit()

    import app.services.call_service as call_mod

    n = await call_mod.sweep_stale_ringing_calls(db_session)
    assert n == 1

    from app.db.models.call import CallLog

    call = await db_session.get(CallLog, uuid.UUID(call_id))
    assert call.status.value == "missed"


async def test_call_guards(client, _capture_otp):
    a_token, a_id = await _register(client, _capture_otp, "+33655555555")
    ah = {"Authorization": f"Bearer {a_token}"}

    # s'appeler soi-meme
    r = await client.post("/api/v1/calls", json={"callee_id": a_id}, headers=ah)
    assert r.status_code == 400

    # callee inexistant
    r = await client.post(
        "/api/v1/calls",
        json={"callee_id": "00000000-0000-0000-0000-000000000000"},
        headers=ah,
    )
    assert r.status_code == 404

    # double appel simultane -> 409
    b_token, b_id = await _register(client, _capture_otp, "+33666666666")
    r = await client.post("/api/v1/calls", json={"callee_id": b_id}, headers=ah)
    assert r.status_code == 201
    r = await client.post("/api/v1/calls", json={"callee_id": b_id}, headers=ah)
    assert r.status_code == 409
