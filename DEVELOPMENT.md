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
export AUTH_ENABLED=false              # see below; the app refuses the default JWT_SECRET otherwise
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
admin — never set in production. With auth enabled (the default) the app,
`alembic` and the scripts refuse to start unless `JWT_SECRET` is set to
something other than the public default (fleet spec CFG-2).

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./pmoney.db` | Postgres URL in production |
| `AUTH_ENABLED` | `true` | `false` = local dev bypass |
| `GOOGLE_CLIENT_ID` | — | OAuth client |
| `JWT_SECRET` | — | app token signing; required (not the default) when auth is enabled |
| `ALLOWED_EMAILS` | — | comma-separated bootstrap allowlist (first admin) |
| `DEPLOY_SECRET` | — | HMAC key for `/deploy` webhook |
| `CURRENCY_SYMBOL` | `$` | display only |
| `SMTP_HOST` / `SMTP_PORT` | `smtp.gmail.com` / `587` | Gmail SMTP relay for the admin digest |
| `SMTP_USER` / `SMTP_PASSWORD` | — | Gmail address + App Password (see DEPLOYMENT.md); unset `SMTP_USER` = digest logs to stdout |
| `SMTP_FROM` | — | optional display `From:`; defaults to `SMTP_USER` |

## Tests

```bash
pytest                       # backend — tests/ — runs against SQLite
TEST_DATABASE_URL=postgresql+psycopg:///pmoney_test pytest   # same suite on Postgres
cd frontend && npm run lint  # eslint — flags hook/JSX bug patterns statically
cd frontend && npm test      # vitest — frontend/src/*.test.{js,jsx}
```

### Pre-push hook (optional)

```bash
scripts/install-hooks.sh     # installs a git pre-push hook; re-run safely, --force replaces a foreign one
```

Before each push it runs the cheap checks (about 20 seconds): `bash -n` on the
shell scripts, `pytest -x`, and the frontend lint and tests when
`frontend/node_modules` exists. CI still runs everything else (Postgres,
migrations, conformance, the build). Skip once with `git push --no-verify`, or
skip steps with `PREPUSH_SKIP="pytest frontend"`. The checks live in
`scripts/pre-push-checks.sh`, so editing them needs no reinstall.

Write tests alongside features: claim lifecycle and ledger invariants
(append-only, balance = sum) are the highest-value backend tests; the
approval queue and claim flows the highest-value frontend tests.

## Migrations

```bash
alembic revision --autogenerate -m "add chore.assignee_ids"
alembic upgrade head
```

Keep migrations working on SQLite **and** Postgres: CI runs them on both
(`backend-postgres` does upgrade, `alembic check`, `downgrade base`, and
upgrade again), so a `downgrade()` must drop everything its `upgrade()`
created, Postgres enum types included.

## Git workflow

1. Branch from `main`.
2. Make changes; run `pytest`, `npm run lint`, and `npm test`.
3. Commit source only — `backend/static/` is gitignored and built during
   deploy.
4. Push, open a PR, squash-merge to `main` once CI is green. A push to
   `main` triggers a production redeploy via the `/deploy` webhook (see
   [DEPLOYMENT.md](DEPLOYMENT.md)); check `/health` afterwards.
5. The repo follows `hamBank/fleetSpec`: see `CLAUDE.md` and
   `.fleet-spec.yml`.
