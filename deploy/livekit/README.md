# Appels Gofolyx — SFU LiveKit auto-hébergé

Ce dossier déploie **votre propre** serveur LiveKit (SFU WebRTC) sur un VPS.
**Aucun passage par LiveKit Cloud.** Le backend Gofolyx ne fait que signer
les tokens d'accès ; tout le média audio/vidéo transite par ce conteneur.

## Architecture

```
  App mobile ──(JWT signé par le backend)──▶ SFU LiveKit (ce VPS)
       │                                          ▲
       │  POST /api/v1/calls  (signalisation)     │  webhook room_finished
       ▼                                          │
   Backend Gofolyx ────────────────────────────────┘
   - génère les tokens (livekit_service.build_access_token)
   - relaie la sonnerie via WebSocket (call.incoming / accepted / …)
   - historise l'appel (call_logs)
   - NE voit jamais le média ni la clé E2EE
```

Le chiffrement bout-en-bout (insertable streams / `e2ee_key`) est géré côté
client : la clé est générée par l'appelant, transmise au destinataire dans
l'événement WebSocket `call.incoming`, et le serveur ne l'utilise ni ne la
journalise.

## Déploiement (VPS)

1. **DNS** : `sfu.gofolyx.com` → IP publique du VPS (enregistrement A).
2. **Pare-feu** : ouvrir
   - `7880/tcp` (signaling + API)
   - `7881/tcp` (WebRTC/TCP fallback)
   - `50000-50100/udp` (média RTP)
   - `3478/udp` + `5349/tcp` (TURN)
   - `443/tcp` si TURN via Let's Encrypt automatique
3. **Clés API** :
   ```sh
   docker run --rm livekit/livekit-server generate-keys
   ```
4. **Config** :
   ```sh
   cd deploy/livekit
   cp livekit.yaml.example livekit.yaml
   # éditez : keys, webhook.api_key, turn.domain, rtc.external_ip si besoin
   ```
5. **Backend** — dans le `.env` de l'API :
   ```
   LIVEKIT_URL=wss://sfu.gofolyx.com
   LIVEKIT_API_KEY=<clé générée>
   LIVEKIT_API_SECRET=<secret généré>
   ```
   (mêmes valeurs que dans `livekit.yaml`)
6. **Lancer** :
   ```sh
   docker compose up -d
   docker compose logs -f livekit
   ```
7. **Vérifier** : `curl https://sfu.gofolyx.com` doit répondre `OK`.
   Le backend expose `GET /api/v1/calls/config` → `{"enabled": true, …}`.

## Endpoints backend (déjà câblés)

| Méthode | Route | Rôle |
|---|---|---|
| `GET`  | `/api/v1/calls/config` | dispo + URL du SFU |
| `POST` | `/api/v1/calls` | démarrer un appel (renvoie le token de l'appelant) |
| `POST` | `/api/v1/calls/{id}/accept` | accepter (renvoie le token du destinataire) |
| `POST` | `/api/v1/calls/{id}/reject` | refuser une sonnerie |
| `POST` | `/api/v1/calls/{id}/cancel` | l'appelant annule avant réponse |
| `POST` | `/api/v1/calls/{id}/hangup` | raccrocher un appel en cours |
| `GET`  | `/api/v1/calls` | historique |
| `DELETE` | `/api/v1/calls/{id}` | supprimer une entrée d'historique |
| `POST` | `/api/v1/calls/webhooks/livekit` | webhook signé (interne) |

Événements WebSocket poussés à l'app : `call.incoming`, `call.accepted`,
`call.rejected`, `call.cancelled`, `call.ended`.

## Coûts

Bande passante uniquement (le média relaie par le VPS). Un appel vidéo
1-to-1 ≈ 1–3 Mbit/s symétrique ; un appel voix ≈ 40–80 kbit/s.
