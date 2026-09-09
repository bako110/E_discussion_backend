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

cp .env.prod.example .env            # remplir POSTGRES_PASSWORD / JWT_SECRET / LIVEKIT_API_*
cp livekit.yaml.example livekit.yaml # remplir keys (mêmes valeurs) + IP publique
chmod 600 .env livekit.yaml

docker compose -f docker-compose.prod.yml up -d --build
docker network connect edisc_net stream_nginx

# Reverse-proxy : coller le contenu de deploy/nginx-edisc.conf dans le
# server{ 443; server_name gofolyx.com } de
#   /opt/backend-stack/nginx-config/nginx.conf   (juste avant `location / {`)
# puis REDÉMARRER le conteneur (bind-mount par inode -> reload ne suffit pas) :
cd /opt/backend-stack && docker compose -f docker-compose.prod.yml restart nginx

# Sauvegarde BDD quotidienne :
#   /opt/webhook/backup-edisc.sh   +   cron  17 3 * * *
```

Contrôles :
```sh
curl https://gofolyx.com/edisc/health                 # {"status":"ok",...}
curl https://gofolyx.com/edisc-sfu/                    # OK
curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' \
  -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
  https://gofolyx.com/edisc/api/v1/ws                  # 101
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
- Côté GitHub : Settings → Webhooks → URL `https://gofolyx.com/hooks/deploy-edisc`,
  content-type `application/json`, secret = contenu de `/root/.edisc-webhook-secret`,
  event *push* uniquement.

## Sauvegarde BDD

`/opt/webhook/backup-edisc.sh` → `pg_dump | gzip` dans `/root/backups/edisc/`,
rotation 14 jours. Cron `17 3 * * *`. Logs `/var/log/edisc-backup.log`.
Restauration : `gunzip -c edisc_AAAAMMJJ_HHMMSS.sql.gz | docker exec -i edisc_db psql -U ediscussion ediscussion`.

## Appels (LiveKit self-hosted, PAS LiveKit Cloud)

`.env` : `LIVEKIT_URL=wss://gofolyx.com/edisc-sfu`, `LIVEKIT_API_KEY/SECRET`
(mêmes valeurs que `livekit.yaml`). Le backend signe les JWT d'accès aux
rooms ; le webhook LiveKit pointe sur
`https://gofolyx.com/edisc/api/v1/calls/webhooks/livekit`. La clé E2EE est
générée par l'appelant et n'est jamais utilisée côté serveur.
