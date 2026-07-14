# Pocket Money — Local Development

## Prerequisites

- Python 3.11+
- Node 20+
- (Optional) Postgres — local dev defaults to SQLite

## First-time setup

```bash
git clone https://github.com/hamBank/pocketMoney.git
cd pocketMoney

# Backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # or: pip install -e ".[dev]"
alembic upgrade head                   # creates local SQLite DB
python scripts/seed_dev_data.py        # optional fixtures

# Frontend
cd frontend && npm install
```

## Running

```bash
# Backend (repo root) → http://localhost:8000
AUTH_ENABLED=false python -m uvicorn backend.main:app --reload

# Frontend dev server with HMR → http://localhost:5173
# (proxies API prefixes — /health /auth /chores /claims /users /transactions — to :8000)
cd frontend && npm run dev

# Or: production-style single origin — build then serve from the backend
cd frontend && npm run build           # outputs to backend/static/
```

`AUTH_ENABLED=false` bypasses Google OAuth and signs you in as a local dev
admin — never set in production.

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./pmoney.db` | Postgres URL in production |
| `AUTH_ENABLED` | `true` | `false` = local dev bypass |
| `GOOGLE_CLIENT_ID` | — | OAuth client |
| `JWT_SECRET` | — | app token signing |
| `ALLOWED_EMAILS` | — | comma-separated bootstrap allowlist (first admin) |
| `DEPLOY_SECRET` | — | HMAC key for `/deploy` webhook |
| `CURRENCY_SYMBOL` | `$` | display only |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `SMTP_FROM` | — | admin daily digest email; unset locally = digest logs to stdout |

## Tests

```bash
pytest                       # backend — tests/ — runs against SQLite
cd frontend && npm test      # vitest — frontend/src/*.test.{js,jsx}
```

Write tests alongside features: claim lifecycle and ledger invariants
(append-only, balance = sum) are the highest-value backend tests; the
approval queue and claim flows the highest-value frontend tests.

## Migrations

```bash
alembic revision --autogenerate -m "add chore.assignee_ids"
alembic upgrade head
```

Keep migrations SQLite-compatible (no Postgres-only types) so local dev and
CI stay on SQLite.

## Git workflow

1. Branch from `main`.
2. Make changes; run `pytest` and `npm test`.
3. Commit source only — `backend/static/` is gitignored and built during
   deploy.
4. Push, open a PR, merge to `main`. A push to `main` can trigger production
   redeploy via the `/deploy` webhook (see [DEPLOYMENT.md](DEPLOYMENT.md)).
