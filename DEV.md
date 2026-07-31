# Local development

Two ways to run a signed-in session locally. Use **dev-login** for everyday work;
use the **named tunnel** only when you need to exercise the real Telegram flow.

## Prerequisites

- Postgres 18 (the `voocab-pg18` container, port 5433 in this setup).
- Backend deps: `cd backend && uv sync`.
- Frontend deps: `cd frontend && npm install`.

---

## Mode 1 — dev-login (default, no tunnel)

Passwordless local login as a fixed `Dev User`. No Telegram, no tunnel, works
offline. Safe: the endpoint only exists when `DEV_LOGIN_ENABLED=true` **and** is
refused whenever `COOKIE_SECURE=true`, so it can never run in production.

**`backend/.env`:**

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/app
SESSION_SECRET=<any long random string>
COOKIE_SECURE=false
FRONTEND_URL=http://localhost:5173
DEV_LOGIN_ENABLED=true
```

**`frontend/.env.development.local`** (gitignored — points the SPA at the backend):

```env
VITE_API_BASE=http://localhost:8001
```

**Run** (two terminals):

```bash
cd backend  && uv run uvicorn app.main:app --reload --port 8001
cd frontend && npm run dev
```

Open http://localhost:5173 → **Dev login (local)** button on the login page. Done.
(The button only renders in Vite dev builds.)

---

## Mode 2 — real Telegram via a named tunnel (one-time setup, stable URL)

A named cloudflared tunnel gives a **stable** public URL, so — unlike a quick
tunnel — you register it in BotFather once and never reconfigure it.

**One-time setup** (needs your Cloudflare account; voocab.uz is on Cloudflare):

```bash
cloudflared tunnel login
cloudflared tunnel create voocab-dev
cloudflared tunnel route dns voocab-dev dev.voocab.uz
```

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: voocab-dev
credentials-file: /Users/<you>/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: dev.voocab.uz
    service: http://localhost:5173
  - service: http_status:404
```

In **@BotFather**, register the redirect URL once:
`https://dev.voocab.uz/api/auth/telegram/callback`

**Switch `backend/.env` to the tunnel profile:**

```env
COOKIE_SECURE=true
FRONTEND_URL=https://dev.voocab.uz
TELEGRAM_REDIRECT_URI=https://dev.voocab.uz/api/auth/telegram/callback
DEV_LOGIN_ENABLED=false
```

**Remove** `frontend/.env.development.local` (or set `VITE_API_BASE=` empty) so the
SPA is same-origin and Vite proxies `/api` to the backend.

**Run** (three terminals):

```bash
cd backend  && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
cloudflared tunnel run voocab-dev
```

Open https://dev.voocab.uz and sign in with Telegram.

> The dev-server proxy (`vite.config.ts`) forwards `/api` to
> `VITE_PROXY_TARGET` (default `http://localhost:8000`); set it if your backend
> runs elsewhere.
