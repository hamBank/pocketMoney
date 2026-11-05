# Pocket Money — Architecture & Reference

> Snapshot for re-loading context in future sessions. Last updated: 2026-07-14.
>
> Companion docs: [SPEC.md](SPEC.md) (product spec), [DATA_MODEL.md](DATA_MODEL.md)
> (tables & schemas), [API.md](API.md) (endpoints), [DEVELOPMENT.md](DEVELOPMENT.md)
> (local dev workflow), [DEPLOYMENT.md](DEPLOYMENT.md) (server & deploy),
> [SHEETS_SETUP.md](SHEETS_SETUP.md) (Google Sheets ledger mirror setup).

## Overview

A single-family pocket money / chore web app. A FastAPI + SQL backend serves a
REST API **and** the compiled React SPA from the same origin.

Administrators (parents) create **chores** — recurring items with a schedule, a
monetary value, a claim mode (`per_user` / `shared` / `open`), and other
configuration. Users (kids) **claim** that a chore is done; the claim routes to
an administrator for approval. An approved claim credits money into the user's
**account** via an append-only transaction ledger, which also records
withdrawals (money paid out / spent), penalties (negative claims), manual
balance adjustments, and an optional per-user weekly allowance applied every
Monday. Kids see a "chores due" list on their screen; admins get an in-app
approval queue plus a once-per-day email digest of pending claims.

See [SPEC.md](SPEC.md) for the full behavioural spec, including the audit
fields every claim must record.

- **Repo:** `https://github.com/hamBank/pocketMoney.git` (default branch `main`)
- **Production:** `https://pmoney.hups.club` on server `camelidcastle.hups.club`

## Stack

- **Backend:** FastAPI + SQLModel (SQLAlchemy) + Postgres (`pmoney`) in
  production, SQLite for local dev/testing. Schema migrations via Alembic.
- **Frontend:** React + Vite + Tailwind, built into `backend/static/`
- **Auth:** Google OAuth for all users (JWT bearer tokens issued by the
  backend). Sign-in restricted to an admin-managed allowlist of family
  accounts. Auth can be disabled for local dev (`AUTH_ENABLED=false`).
- **Money:** single currency, stored as integer cents. Display symbol/format
  is app-level configuration. No currency conversion.
- **Server:** systemd unit `pmoney` runs uvicorn on `127.0.0.1:8001`, behind an
  Apache vhost (`pmoney.hups.club.conf`). Debian/Ubuntu.

## Repo layout (planned)

```
backend/
  main.py            # FastAPI app factory, auth middleware, static mount,
                     # /deploy webhook, /health
  database.py        # engine setup (Postgres/SQLite), session dependency
  models.py          # SQLModel tables + Pydantic schemas (see DATA_MODEL.md)
  auth.py            # JWT issue/verify, Google token verification,
                     # AUTH_ENABLED flag, email allowlist
  permissions.py     # require_admin_role / require_user_role dependencies
  schedule.py        # chore recurrence + claimability (per_user/shared/open modes)
  emails.py          # SMTP send + admin daily-digest composition
  sheets.py          # Google Sheets REST client (service account)
  sheets_sync.py     # ledger → Google Sheet mirror: tab per child + Totals
  routers/
    auth_router.py   # /auth/google, /auth/me, /auth/config
    chores.py        # /chores CRUD (admin) + listing (all users)
    claims.py        # /claims submit/approve/reject/modify, ad-hoc & penalty
    users.py         # /users admin management, balances
    transactions.py  # /transactions ledger: withdrawals, adjustments, history
  static/            # compiled frontend output — served at /
alembic/             # migration scripts
scripts/
  send_admin_digest.py       # timer (daily): email admins pending claims +
                             # that day's submitted/resolved claim activity
  apply_weekly_allowance.py  # timer (Mondays): idempotent allowance transactions
  sync_sheet.py              # timer (every 10 min): Google Sheet ledger catch-up
  check_config.py            # deploy preflight: refuse a config the app won't start with
  smoke_check.sh             # post-deploy check; deploy.sh fails if it fails
  seed_dev_data.py           # optional local fixtures (users, chores, claims)
frontend/
  src/
    App.jsx              # Shell: auth gate, header, theme, settings gear
    api.js               # fetch wrapper + all endpoint helpers
    currency.js          # cents ↔ display formatting (single currency)
    settings.js          # reactive client settings store (useSyncExternalStore)
    themes.js
    index.css            # Tailwind + CSS variables per theme
    components/
      ChoreList          # kid view: chores due now, claim button
      ClaimHistory       # per-user claim + transaction history
      ApprovalQueue      # admin: pending claims — approve/modify/reject
      ChoreManager       # admin: chore CRUD, schedules, values
      UserManager        # admin: users, roles, balance adjustments, payouts
      UserSettings, ThemePicker, LoginPage
tests/                   # pytest (backend); frontend/src/*.test.{js,jsx} (vitest)
deploy.sh                # idempotent server provisioning + --update mode
```

## Data model

Hierarchy (details in [DATA_MODEL.md](DATA_MODEL.md)):

```
User ─┬─< Claim >─── Chore        (a claim is a user asserting a chore is done;
      │                            chore_id is null for ad-hoc/penalty claims)
      └─< Transaction >── Claim?  (append-only ledger; balance = SUM(amount);
                                   claim payouts, withdrawals, penalties,
                                   manual adjustments)
```

## Key API endpoints

See [API.md](API.md) for the full list. Highlights:

- `POST /auth/google` — exchange Google ID token for app JWT
- `GET /chores`, `POST/PATCH/DELETE /chores/{id}` (admin)
- `POST /claims` — user claims a chore; admins can lodge on behalf of a user,
  as ad-hoc one-offs, or as penalties (negative value)
- `POST /claims/{id}/approve|reject` — admin resolution; approval may edit value
- `GET /users/{id}/balance`, `GET /transactions?user_id=`
- `POST /transactions` — admin: withdrawal / manual adjustment
- `GET /health`, `POST /deploy` (HMAC-signed redeploy webhook)

## Build & deploy workflow

```bash
# Frontend build (required after any frontend/src change) — outputs to backend/static/
cd frontend && npm run build

# Run backend locally (from repo root)
python -m uvicorn backend.main:app --reload   # → http://localhost:8000
```

**Git workflow:** make changes → build frontend if any `frontend/src` changed →
commit → branch, push, PR, merge to `main`. The compiled `backend/static/`
bundle is **not** committed; it is built server-side during deploy (see
[DEPLOYMENT.md](DEPLOYMENT.md)).

**Production deploy:** `deploy.sh` (idempotent) provisions packages, the
`pocketMoney` system user, `/opt/pocketMoney`, the systemd service, and Apache
vhost. A push to `main` can trigger redeploy via the `/deploy` webhook
(HMAC-signed, `DEPLOY_SECRET`) which touches `.deploy-trigger`; a systemd path
unit runs `deploy.sh --update` (git pull → npm build → alembic upgrade →
service restart). Deploy logs: `/var/log/pocketMoney-deploy.log`.

## Conventions / gotchas

- Money is integer cents everywhere in the backend and API; only the frontend
  formats for display (`currency.js`).
- The transaction ledger is append-only: corrections are new adjustment rows,
  never edits — this is what makes balances auditable.
- Claims are immutable after resolution; "editing" an approved claim means
  rejecting/reversing and re-lodging.
- JSON column edits need `flag_modified` server-side (SQLAlchemy doesn't detect
  in-place mutation of JSON values).
- Tests: `tests/` (pytest backend), `frontend/src/*.test.{js,jsx}` (vitest).
