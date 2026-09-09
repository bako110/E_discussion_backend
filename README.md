# E-discussion — Backend

Messagerie 1-to-1 chiffrée de bout en bout (Signal Protocol), authentification
par **e-mail et/ou numéro de téléphone**, temps réel WebSocket, multilingue.

## Stack

| Couche | Choix |
|---|---|
| API | FastAPI (async), OpenAPI sur `/docs` |
| DB | PostgreSQL 16 — SQLAlchemy 2 async + Alembic |
| Temps réel / présence | Redis (pub/sub multi-worker, TTL présence, cache OTP) |
| Auth | JWT access/refresh (rotation), OTP SMS (Twilio) + e-mail (SMTP) |
| E2EE | Distribution des clés publiques X3DH (le serveur ne déchiffre jamais) |
| Push | Firebase Cloud Messaging (best-effort) |
| i18n | Catalogues JSON `app/i18n/locales/` — `Accept-Language` / `?lang=` / `X-Lang` |

## Architecture

```
app/
  core/        config, sécurité (hash + JWT), logging, erreurs i18n, middlewares
  i18n/        moteur de traduction + locales/{fr,en}.json
  db/          base déclarative, session async, client Redis, models/
  schemas/     DTO Pydantic (in/out)
  services/    logique métier (auth, otp, users, conversations, messages, devices, ws)
  api/
    deps.py            dépendances (utilisateur courant, pagination, locale)
    v1/router.py       agrégation
    v1/routers/        auth, users, contacts, conversations, messages, devices, ws
  main.py      création de l'app + lifespan
alembic/       migrations
tests/         pytest (SQLite in-memory pour l'unité)
```

### Modèle de données (v1)

`users` · `refresh_tokens` · `otp_challenges` · `user_contacts` · `user_blocks`
· `conversations` (paire ordonnée, unique) · `conversation_requests`
· `conversation_mutes` · `messages` · `message_reactions` · `message_receipts`
(delivered/read) · `devices` + `one_time_prekeys` (E2E) · `device_tokens` (push)
· `call_logs` (structure prête, appels réels en v2).

## Démarrage

### Avec Docker (recommandé)

```bash
cp .env.example .env          # ajuster JWT_SECRET au minimum
make up                       # db + redis + api sur :8000
# dans un autre terminal, une fois l'api up :
docker compose exec api alembic revision --autogenerate -m "init"
docker compose exec api alembic upgrade head
```

### En local

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
make install
cp .env.example .env
# Postgres + Redis doivent tourner (docker compose up db redis)
alembic revision --autogenerate -m "init"
alembic upgrade head
make dev                      # http://localhost:8000/docs
make test
```

## Flux d'authentification

| Cas | Étapes |
|---|---|
| Inscription e-mail | `POST /auth/register {email,password}` → OTP e-mail → `POST /auth/verify-registration {identifier,code}` → tokens |
| Inscription téléphone | `POST /auth/register {phone}` → OTP SMS → `POST /auth/verify-registration` → tokens |
| Connexion mot de passe | `POST /auth/login {identifier,password}` (`identifier` = e-mail, username ou E.164) |
| Connexion OTP (sans mdp) | `POST /auth/otp/send {identifier,purpose:"login"}` → `POST /auth/otp/verify` → tokens |
| Lier un téléphone | `POST /auth/otp/send {identifier:"+33…",purpose:"link_phone"}` → `POST /auth/phone/link {phone,code}` |
| Rafraîchir | `POST /auth/refresh {refresh_token}` (rotation : l'ancien est révoqué) |

En dev, si Twilio/SMTP ne sont pas configurés, **le code OTP est écrit dans les
logs** (`sms.console` / `email.console`).

## WebSocket

`ws://<host>/api/v1/ws` — premier message : `{"type":"auth","token":"<access_jwt>"}`.

Events poussés : `message.new`, `message.edited`, `message.deleted`,
`message.reaction`, `receipt.delivered`, `receipt.read`, `typing.start/stop`,
`presence.update`.
Messages client acceptés : `ping`, `typing`, `delivered`.

## i18n

Ajouter une langue : créer `app/i18n/locales/<code>.json` (mêmes clés que `fr.json`)
puis l'ajouter à `SUPPORTED_LOCALES` dans `.env`. Les messages d'erreur, sujets
d'e-mail et corps de SMS sont tous des clés traduites.
