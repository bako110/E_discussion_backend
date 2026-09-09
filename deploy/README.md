# Déploiement — E-discussion backend

Hébergé sur le VPS **à côté des autres projets** (`/opt/e-discussion`), stack
Docker isolé, routé en **sous-chemin** de `gofolyx.com` (le DNS Hostinger n'a
pas de wildcard, donc pas de sous-domaine dédié).

| URL publique | → | Cible |
|---|---|---|
| `https://gofolyx.com/edisc/`      | API REST + WebSocket + médias | `edisc_api:8000` |
| `https://gofolyx.com/edisc-sfu/`  | SFU LiveKit auto-hébergé      | `127.0.0.1:7880` |

## Stack (`deploy/docker-compose.prod.yml`, projet `e-discussion`)

- `edisc_db`      PostgreSQL 16 (réseau interne `edisc_net`)
- `edisc_redis`   Redis 7 (présence + pub/sub WebSocket)
- `edisc_api`     FastAPI/uvicorn — `127.0.0.1:8090`, migrations Alembic au boot
- `edisc_livekit` LiveKit 1.8 en `network_mode: host` (média WebRTC UDP 50000-50200)

Le reverse-proxy partagé `stream_nginx` est rattaché à `edisc_net` et porte
les deux `location` (voir `/opt/backend-stack/nginx-config/nginx.conf`).

## Premier déploiement

```sh
ssh root@VPS
git clone https://github.com/bako110/E_discussion_backend.git /opt/e-discussion
cd /opt/e-discussion/deploy
cp .env.prod.example .env            # remplir POSTGRES_PASSWORD / JWT_SECRET
cp livekit.yaml.example livekit.yaml # remplir keys + IP publique
docker compose -f docker-compose.prod.yml up -d --build
docker network connect edisc_net stream_nginx
# + ajouter les 2 location dans nginx.conf, puis: docker compose -f ... restart nginx (backend-stack)
```

## Déploiement continu — webhook dédié

Push sur `main` → GitHub appelle `https://gofolyx.com/hooks/deploy-edisc`
→ `/opt/webhook/deploy-edisc.sh` : `git pull` + rebuild `edisc_api` +
(recreate `edisc_livekit` seulement si `deploy/livekit.yaml` ou le compose a
changé) + contrôle santé. **N'affecte aucun autre projet du VPS.**

- Secret : `/root/.edisc-webhook-secret`
- Logs : `/var/log/edisc-deploy.log`
- Hook enregistré dans `/opt/webhook/hooks.json` (id `deploy-edisc`, filtre
  `ref == refs/heads/main`)

## Appels (LiveKit self-hosted, PAS LiveKit Cloud)

`.env` : `LIVEKIT_URL=wss://gofolyx.com/edisc-sfu`, `LIVEKIT_API_KEY/SECRET`
(mêmes valeurs que `livekit.yaml`). Le backend signe les JWT d'accès aux
rooms ; le webhook LiveKit pointe sur
`https://gofolyx.com/edisc/api/v1/calls/webhooks/livekit`. La clé E2EE est
générée par l'appelant et n'est jamais utilisée côté serveur.
