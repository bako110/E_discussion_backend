#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
#  Déploiement / mise à jour du backend E-discussion sur le VPS.
#
#  Premier déploiement :
#    ssh root@VPS
#    git clone https://github.com/bako110/E_discussion_backend.git /opt/e-discussion
#    cd /opt/e-discussion/deploy && ./deploy.sh --init
#
#  Mises à jour :
#    cd /opt/e-discussion && git pull && cd deploy && ./deploy.sh
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE="docker compose -f docker-compose.prod.yml"
NGINX_CONF="/opt/backend-stack/nginx-config/nginx.conf"
CERTBOT_WWW="/var/lib/docker/volumes/backend-stack_certbot_www/_data"
DOMAIN_API="msg.gofolyx.com"
DOMAIN_SFU="sfu.gofolyx.com"
LE_EMAIL="${LE_EMAIL:-admin@gofolyx.com}"

init=false
[[ "${1:-}" == "--init" ]] && init=true

# ── 1. Secrets / .env ──────────────────────────────────────────────────
if [[ ! -f .env ]]; then
  echo "→ génération de deploy/.env"
  cp .env.prod.example .env
  PG_PW=$(openssl rand -hex 24)
  JWT=$(openssl rand -hex 32)
  LK_KEY="APIed$(openssl rand -hex 6)"
  LK_SECRET=$(openssl rand -hex 32)
  sed -i "s|CHANGE_ME_STRONG|${PG_PW}|"            .env
  sed -i "s|CHANGE_ME_openssl_rand_hex_32|${JWT}|" .env
  sed -i "s|^LIVEKIT_API_KEY=.*|LIVEKIT_API_KEY=${LK_KEY}|"       .env
  sed -i "s|^LIVEKIT_API_SECRET=.*|LIVEKIT_API_SECRET=${LK_SECRET}|" .env
  echo "  clés générées (PG, JWT, LiveKit)"
fi
# shellcheck disable=SC1091
set -a; source .env; set +a

# ── 2. livekit.yaml ───────────────────────────────────────────────────
if [[ ! -f livekit.yaml ]]; then
  echo "→ génération de deploy/livekit.yaml"
  cp livekit.yaml.example livekit.yaml
  sed -i "s|PLACEHOLDER_KEY|${LIVEKIT_API_KEY}|g"    livekit.yaml
  sed -i "s|PLACEHOLDER_SECRET|${LIVEKIT_API_SECRET}|g" livekit.yaml
fi

# ── 3. Certificats TLS (webroot certbot déjà en place) ────────────────
issue_cert() {
  local d=$1
  if [[ ! -d "/var/lib/docker/volumes/backend-stack_certbot_conf/_data/live/${d}" ]]; then
    echo "→ émission du certificat ${d}"
    docker run --rm \
      -v backend-stack_certbot_conf:/etc/letsencrypt \
      -v backend-stack_certbot_www:/var/www/certbot \
      certbot/certbot certonly --webroot -w /var/www/certbot \
      -d "${d}" --email "${LE_EMAIL}" --agree-tos --no-eff-email -n
  else
    echo "  certificat ${d} déjà présent"
  fi
}

# ── 4. Build + up ────────────────────────────────────────────────────
echo "→ build & up"
$COMPOSE up -d --build

# rattache le reverse-proxy partagé au réseau e-discussion (idempotent)
docker network connect edisc_net stream_nginx 2>/dev/null && \
  echo "  stream_nginx rattaché à edisc_net" || true

if $init; then
  issue_cert "$DOMAIN_API"
  issue_cert "$DOMAIN_SFU"

  # ── 5. Bloc nginx (une seule fois) ─────────────────────────────────
  if ! grep -q "server_name ${DOMAIN_API}" "$NGINX_CONF"; then
    echo "→ ajout des server blocks nginx"
    python3 - "$NGINX_CONF" <<'PYEOF'
import sys, pathlib
conf = pathlib.Path(sys.argv[1])
txt = conf.read_text()
block = r'''
    # ── E-discussion (messagerie) — msg.gofolyx.com ───────────────────────────
    server {
        listen 443 ssl http2;
        server_name msg.gofolyx.com;

        ssl_certificate     /etc/letsencrypt/live/msg.gofolyx.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/msg.gofolyx.com/privkey.pem;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_session_cache   shared:SSL:10m;

        add_header Strict-Transport-Security "max-age=63072000" always;
        client_max_body_size 128M;

        location / {
            proxy_pass http://edisc_api:8000;
            proxy_http_version 1.1;
            proxy_set_header Host              $host;
            proxy_set_header X-Real-IP         $remote_addr;
            proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            # WebSocket (/api/v1/ws)
            proxy_set_header Upgrade    $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_read_timeout  3600s;
            proxy_send_timeout  3600s;
        }
    }

    # ── E-discussion — SFU LiveKit — sfu.gofolyx.com ──────────────────────────
    server {
        listen 443 ssl http2;
        server_name sfu.gofolyx.com;

        ssl_certificate     /etc/letsencrypt/live/sfu.gofolyx.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/sfu.gofolyx.com/privkey.pem;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_session_cache   shared:SSL:10m;

        location / {
            # LiveKit tourne en host network -> joignable via l'IP de la gateway docker
            proxy_pass http://172.17.0.1:7880;
            proxy_http_version 1.1;
            proxy_set_header Host              $host;
            proxy_set_header X-Real-IP         $remote_addr;
            proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Upgrade    $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_read_timeout  3600s;
            proxy_send_timeout  3600s;
        }
    }
'''
# map $connection_upgrade — ajouté dans http{} s'il manque
if "connection_upgrade" not in txt.split("server {")[0]:
    txt = txt.replace(
        "http {\n",
        'http {\n    map $http_upgrade $connection_upgrade {\n'
        '        default upgrade;\n        "" close;\n    }\n',
        1,
    )
# insère les blocs juste avant la dernière accolade fermante de http{}
idx = txt.rfind("}")
txt = txt[:idx] + block + "\n" + txt[idx:]
conf.write_text(txt)
print("  nginx.conf mis à jour")
PYEOF
  else
    echo "  server blocks nginx déjà présents"
  fi

  echo "→ test + reload nginx"
  docker exec stream_nginx nginx -t
  docker exec stream_nginx nginx -s reload
fi

echo
echo "✓ Déployé."
echo "  API   : https://${DOMAIN_API}/health"
echo "  SFU   : https://${DOMAIN_SFU}   (doit répondre 'OK')"
echo "  Appels: $(grep -E '^LIVEKIT_(URL|API_KEY)=' .env)"
$COMPOSE ps
