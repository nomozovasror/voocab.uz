# Deploying voocab.uz

This is the human-run ops runbook. The repo already contains the code and
config; the steps below are the manual actions **you** perform (DNS, R2,
BotFather, server) — Claude Code does not do these.

## Topology

| Piece            | Where                    | Domain          |
| ---------------- | ------------------------ | --------------- |
| Frontend (SPA)   | Cloudflare Pages         | `voocab.uz`     |
| Backend (API)    | Office server (Docker)   | `api.voocab.uz` |
| Postgres 18      | Same server (Docker)     | internal only   |
| Audio + DB backups | Cloudflare R2          | S3-compatible   |

TLS for the API is handled by Caddy (Let's Encrypt). The frontend and API sit
on different subdomains, so the session cookie is scoped to `.voocab.uz` and
CORS is enabled with credentials.

---

## 1. DNS (Cloudflare)

Both records must be **DNS-only (grey cloud)** — Caddy needs to reach the
origin directly to solve the ACME challenge, and proxying would hide the real
client IP.

- `A  api.voocab.uz  → <server public IP>`   (DNS-only)
- `voocab.uz` / `www` → managed by Cloudflare Pages (step 6)

Ensure the server's firewall allows inbound **80** and **443** (Caddy needs 80
for the HTTP-01 challenge and redirects).

## 2. Cloudflare R2

1. Create a bucket, e.g. `voocab`.
2. Create an R2 API token (S3-compatible) → note the Access Key ID + Secret.
3. Note the endpoint: `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.

These go into `.env.prod` (`R2_BUCKET`, `R2_ENDPOINT`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`).

## 3. Server: fill in `.env.prod`

On the server, clone the repo and create `.env.prod` from the template:

```bash
git clone <repo> /srv/voocab && cd /srv/voocab
cp .env.prod.example .env.prod
```

Fill in every value. Highlights:

- `POSTGRES_*` + `DATABASE_URL` — use the same user/password/db; host is `db`.
- `SESSION_SECRET` — `openssl rand -hex 32`.
- `COOKIE_SECURE=true`, `COOKIE_DOMAIN=.voocab.uz`.
- `FRONTEND_URL=https://voocab.uz`, `CORS_ORIGINS=https://voocab.uz,https://www.voocab.uz`.
- `TELEGRAM_*` — from step 5.

`.env.prod` is gitignored — never commit it.

## 4. Server: bring up the stack + migrate

```bash
docker compose -f docker-compose.prod.yml up -d --build
# Apply the schema (run inside the backend container):
docker compose -f docker-compose.prod.yml exec backend uv run alembic upgrade head
```

Caddy will obtain the TLS cert for `api.voocab.uz` automatically on first hit.
Verify: `curl https://api.voocab.uz/health` → `{"status":"ok"}`.

## 5. BotFather (Telegram)

In `@BotFather` for your bot:

1. Enable **Web Login** (OpenID Connect), not the legacy Login Widget.
2. Set the allowed/redirect URL to:
   `https://api.voocab.uz/api/auth/telegram/callback`
3. Copy the **bot id** → `TELEGRAM_BOT_ID` and the **client secret** →
   `TELEGRAM_BOT_TOKEN` in `.env.prod`, then restart the backend:
   `docker compose -f docker-compose.prod.yml up -d backend`.

## 6. Cloudflare Pages (frontend)

Create a Pages project from the repo:

- **Root directory:** `frontend`
- **Build command:** `npm ci && npm run build`
- **Output directory:** `dist`
- **Environment variable:** `VITE_API_BASE=https://api.voocab.uz`
- Add a **SPA fallback** so client routes work: redirect `/*` → `/index.html`
  (200). (Add a `frontend/public/_redirects` file with `/* /index.html 200`
  if not configured in the dashboard.)

Point `voocab.uz` (and `www`) at the Pages project via the custom-domain flow.

## 7. Database backups (cron)

The `backup-db.sh` script dumps Postgres and uploads a gzipped snapshot to R2.
It reads credentials from `.env.prod` and needs the `aws` CLI on the host.

```bash
# nightly at 03:00
0 3 * * *  cd /srv/voocab && ./backup-db.sh >> /var/log/voocab-backup.log 2>&1
```

---

## Updating a deployment

```bash
cd /srv/voocab && git pull
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec backend uv run alembic upgrade head
```

The frontend redeploys automatically on push (Cloudflare Pages).
