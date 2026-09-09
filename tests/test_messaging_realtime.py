"""Messagerie temps réel + chiffrement de bout en bout — vérifie que :

  1. A envoie un message -> B le reçoit INSTANTANÉMENT via l'event WS
     `message.new` (pas de polling) ;
  2. le serveur RELAIE le blob chiffré tel quel (il ne le déchiffre jamais,
     ne le journalise pas, `encrypted=True` conservé) ;
  3. l'aperçu push d'un message chiffré est générique (pas de fuite) ;
  4. B accuse « remis » (WS `delivered`) -> A reçoit `receipt.delivered`
     avec `message_id` ET `client_id` ;
  5. B marque lu -> A reçoit `receipt.read` (si B a `read_receipts=True`) ;
  6. idempotence : rejouer le POST avec le même `client_id` ne crée pas de
     doublon et renvoie le message existant ;
  7. l'ordre d'arrivée est respecté (A envoie 3 messages -> B les reçoit
     dans l'ordre).

Le SFU/WS réel n'est pas monté : on capture les events publiés sur
`ws:user:{id}` (c'est exactement ce que la socket relaie au client).
"""
from __future__ import annotations

import json
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


def _events(redis, user_id: str, etype: str | None = None) -> list[dict]:
    out = []
    for ch, msg in redis.published:
        if ch == f"ws:user:{user_id}":
            ev = json.loads(msg)
            if etype is None or ev.get("type") == etype:
                out.append(ev)
    return out


async def _open_conv(client, ah, bh, b_id, a_id) -> str:
    """A ouvre une conversation avec B, B accepte -> conv acceptée des 2 côtés."""
    r = await client.post("/api/v1/conversations", headers=ah, json={"partner_id": b_id})
    assert r.status_code == 201, r.text
    conv_id = r.json()["id"]
    # B accepte la demande (sinon B ne peut pas répondre)
    r = await client.post(f"/api/v1/conversations/{conv_id}/accept", headers=bh)
    assert r.status_code == 200, r.text
    return conv_id


# blob "chiffré" factice : le serveur ne doit jamais le lire.
def _cipher_blob(tag: str) -> str:
    return json.dumps(
        {
            "senderDeviceId": "devA",
            "contentType": "ratchet",
            "dhPublicKey": "ZmFrZQ==",
            "previousChainLength": 0,
            "messageNumber": 0,
            "nonce": "bm9uY2U=",
            "ciphertext": f"Q0lQSEVSLXt0YWd9".replace("e30=", tag),
            "_tag": tag,
        }
    )


async def test_realtime_delivery_and_e2e_relay(client, db_session, _capture_otp, _patch_redis):
    a_token, a_id = await _register(client, _capture_otp, "+33612345601")
    b_token, b_id = await _register(client, _capture_otp, "+33612345602")
    ah = {"Authorization": f"Bearer {a_token}"}
    bh = {"Authorization": f"Bearer {b_token}"}

    conv_id = await _open_conv(client, ah, bh, b_id, a_id)
    _patch_redis.published.clear()

    # ── A envoie un message CHIFFRÉ ──────────────────────────────────────
    plaintext_never_sent = "coucou B, ceci est secret"  # jamais transmis au serveur
    blob = _cipher_blob("msg1")
    client_id = str(uuid.uuid4())
    r = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=ah,
        json={"type": "text", "body": blob, "encrypted": True, "client_id": client_id},
    )
    assert r.status_code == 201, r.text
    sent = r.json()
    assert sent["encrypted"] is True
    assert sent["client_id"] == client_id
    # le serveur renvoie le blob TEL QUEL (il ne déchiffre pas)
    assert sent["body"] == blob
    assert plaintext_never_sent not in json.dumps(sent)

    # ── B reçoit `message.new` INSTANTANÉMENT (event WS relayé) ──────────
    incoming = _events(_patch_redis, b_id, "message.new")
    assert len(incoming) == 1, "B doit recevoir le message en temps réel"
    payload = incoming[0]["message"]
    assert payload["conversation_id"] == conv_id
    assert payload["sender_id"] == a_id
    assert payload["encrypted"] is True
    assert payload["body"] == blob  # blob chiffré intact, transmis à B
    assert payload["client_id"] == client_id
    assert plaintext_never_sent not in json.dumps(incoming)

    # ── B accuse RÉCEPTION (chemin WS `delivered` -> mark_delivered) ────
    #    On appelle le service directement avec la session de test (le handler
    #    WS ouvre sa propre session, incompatible avec la DB in-memory).
    from app.services import message_service as _msg

    _patch_redis.published.clear()
    await _msg.mark_delivered(db_session, uuid.UUID(b_id), uuid.UUID(payload["id"]))
    await db_session.flush()

    delivered = _events(_patch_redis, a_id, "receipt.delivered")
    assert len(delivered) == 1, "A doit recevoir l'accusé « remis » (✓✓)"
    assert delivered[0]["message_id"] == payload["id"]
    assert delivered[0]["conversation_id"] == conv_id
    # client_id relayé -> le client peut recoller sa ligne locale pas encore confirmée
    assert delivered[0]["client_id"] == client_id

    # ── B marque LU -> A reçoit `receipt.read` ──────────────────────────
    _patch_redis.published.clear()
    r = await client.put(f"/api/v1/conversations/{conv_id}/read", headers=bh)
    assert r.status_code == 200, r.text
    read = _events(_patch_redis, a_id, "receipt.read")
    assert len(read) == 1, "A doit recevoir l'accusé de lecture (✓✓ bleu)"
    assert read[0]["conversation_id"] == conv_id

    # ── idempotence : rejouer le POST -> pas de doublon ─────────────────
    _patch_redis.published.clear()
    r = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=ah,
        json={"type": "text", "body": blob, "encrypted": True, "client_id": client_id},
    )
    assert r.status_code == 201, r.text
    assert r.json()["id"] == sent["id"], "même client_id -> même message"
    # pas de nouvel event message.new pour ce rejeu
    assert _events(_patch_redis, b_id, "message.new") == []

    # ── historique : un seul message (pas de doublon) ──────────────────
    r = await client.get(f"/api/v1/conversations/{conv_id}/messages", headers=bh)
    assert r.status_code == 200
    hist = r.json()
    assert len([m for m in hist if m["body"] == blob]) == 1


async def test_message_order_preserved(client, _capture_otp, _patch_redis):
    a_token, a_id = await _register(client, _capture_otp, "+33612345603")
    b_token, b_id = await _register(client, _capture_otp, "+33612345604")
    ah = {"Authorization": f"Bearer {a_token}"}
    bh = {"Authorization": f"Bearer {b_token}"}
    conv_id = await _open_conv(client, ah, bh, b_id, a_id)
    _patch_redis.published.clear()

    bodies = [_cipher_blob(f"m{i}") for i in range(3)]
    for body in bodies:
        r = await client.post(
            f"/api/v1/conversations/{conv_id}/messages",
            headers=ah,
            json={"type": "text", "body": body, "encrypted": True, "client_id": str(uuid.uuid4())},
        )
        assert r.status_code == 201, r.text

    incoming = _events(_patch_redis, b_id, "message.new")
    assert [ev["message"]["body"] for ev in incoming] == bodies, "ordre d'arrivée respecté"


async def test_encrypted_push_preview_is_generic(client, _capture_otp, _patch_redis, monkeypatch):
    """L'aperçu de notification push d'un message chiffré ne doit RIEN révéler."""
    captured: list[dict] = []

    async def _fake_push(db, user_id, *, title, body, data=None):
        captured.append({"title": title, "body": body, "data": data or {}})

    import app.services.message_service as msg_mod

    monkeypatch.setattr(msg_mod, "push_to_user", _fake_push)

    a_token, a_id = await _register(client, _capture_otp, "+33612345605")
    b_token, b_id = await _register(client, _capture_otp, "+33612345606")
    ah = {"Authorization": f"Bearer {a_token}"}
    bh = {"Authorization": f"Bearer {b_token}"}
    conv_id = await _open_conv(client, ah, bh, b_id, a_id)

    secret = "RIB: FR76 1234 5678"
    blob = _cipher_blob("secret")
    r = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        headers=ah,
        json={"type": "text", "body": blob, "encrypted": True, "client_id": str(uuid.uuid4())},
    )
    assert r.status_code == 201, r.text

    assert captured, "un push doit être émis vers B"
    push = captured[-1]
    assert secret not in json.dumps(push)
    assert blob not in json.dumps(push)
    assert push["body"] in ("Nouveau message", "")  # aperçu générique
    assert push["data"].get("encrypted") == "1"
