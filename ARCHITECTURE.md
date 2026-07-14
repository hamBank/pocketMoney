# Money Track — Architecture & Reference

> Snapshot for re-loading context in future sessions. Last updated: 2026-07-14.

## Overview

A family pocket money / chore web app. A FastAPI + SQL backend serves a REST API
**and** the compiled React SPA from the same origin. Administrator Users create 
chores, which may have a re-occuring schedule, 

Chores are a reccuring item with a schedule, value and other configuration options. Users
can 'claim' a chore is done, which routes the claim for approval by an administrator.
Claims when approved will increment an amount of money into a users 'account'
Administrators can add / modify / remove chores. 
Administrators can approve, modify or reject a claim.
Administrators can lodge and approve a claim on behalf of a user.
Administrators can lodge a on-off chore/claim against a user, optionally creating it as an 
on-going claim as part of the process
Administrators can arbitrarly edit a users balence.
Administrators can lodge a 'penalty' claim with a negative balance.

For all claims we need to log:
- who submitted the claim
- the user who the claim applies to
- when the claim was submitted
- the original values of the claim
- when it was approved
- the final approved value (which may have been edited by an administrator during approval)

- **Repo:** `https://github.com/hamBank/pocketMoney.git` (default branch `main`)
- **Local root:** `F:\Users\foobi\Downloads\pocketMoney\`
- **Production:** `https://pmoney.hups.club` on server `camelidcastle.hups.club`

## Stack

- **Backend:** FastAPI + SQLModel (SQLAlchemy) + Postgres (`pmoney`) + SQLite for local testing
- **Frontend:** React + Vite + Tailwind, built into `backend/static/`
- **Auth:** Google OAuth (JWT bearer tokens); auth can be disabled for local dev
- **Server:** systemd unit `pmoney` runs uvicorn on `127.0.0.1:8001`, behind
  Apache vhost (`pmoney.hups.club.conf`). Debian/Ubuntu.

## Repo layout

```
backend/
  main.py            # FastAPI app, auth middleware, static mount, /deploy, /health, /currency/convert
  database.py        # SQLite engine + startup migrations
  models.py          # SQLModel tables + Pydantic schemas (see Data Model)
  auth.py            # JWT + Google token verification, AUTH_ENABLED flag
  importer.py        # CSV → DB seeding
  permissions.py     # require_admin_role / require_user_role
  notifications.py  # push triggers: chore-due window, weekly summary
  routers/
    items.py         # /chores CRUD
    auth_router.py   # /auth/google, /auth/me, /auth/config
  static/            # COMPILED frontend output (committed) — served at /
scripts/
  send_notifications.py         # cron entry point: send_due_notifications +
frontend/
  src/
    App.jsx                  # Shell: auth gate, header, theme, settings gear,
                             # PendingReview modal trigger
    api.js                   # fetch wrapper + all endpoint helpers
    kinds.js                 # SINGLE SOURCE OF TRUTH for item kinds (see below)
    currency.js              # cost parsing, conversion, formatting, isFullyPaid
    settings.js              # reactive hide-completed store (useSyncExternalStore)
    themes.js
    index.css                # Tailwind + CSS variables per theme (5 themes)
    components/      
      UserSettings           # Config for User
      PendingReview          # modal: review/apply/discard email-ingested items
      ThemePicker, LoginPage, ShareModal
```

## Data Model (`backend/models.py`)

Hierarchy: 


## Key API endpoints

## Build & deploy workflow

```bash
# Frontend build (required after any frontend/src change) — outputs to backend/static/
cd F:\Users\foobi\Downloads\pocketMoney\frontend
npm run build

# Run backend locally
cd F:\Users\foobi\Downloads\pocketMoney
python -m uvicorn backend.main:app --reload   # → http://localhost:8000
```

**Git workflow used in this project:** make changes → build frontend if any
`frontend/src` changed → commit BOTH source and built `backend/static/` assets →
create a branch, push, merge to `main`, push `main`. Push via HTTPS with PAT
(credentials in project memory, not in repo).

**Production deploy:** `deploy.sh` (idempotent) provisions packages, the
`pocketMoney` system user, `/opt/pocketMoney`, the systemd service, and Apache vhost.
A push to `main` can trigger redeploy via the `/deploy` webhook (HMAC-signed,
`DEPLOY_SECRET`) which touches `.deploy-trigger`; a systemd path unit runs
`deploy.sh --update`. Deploy logs: `/var/log/pocketMoney-deploy.log` (each run
writes a timestamped header).

## Server access

SSH: `ssh -i C:/Users/foobi/.ssh/pocketMoney_id anto@camelidcastle.hups.club`
- App dir `/opt/pocketMoney`, service `pocketMoney`, deploy log
  `/var/log/pocketMoney-deploy.log`.

## Scheduled maintenance

- `powerbank-policy-refresh` scheduled task (Claude routine): monthly on the 20th,
  refreshes `frontend/src/powerbank.js` against current airline rules. Intended to
  run only July & August 2026 — delete after the August run.
- Power bank data reflects the **ICAO global standard effective 27 Mar 2026** (max 2
  power banks, cabin-only, no in-flight use/charging).

## Conventions / gotchas

- `SPEC.md` holds the original product spec + data model reference (note: predates
  email ingestion — `PendingChange`, `IngestedEmail`, `UserImportToken`, and the
  ingest/pending/me routers are not reflected there).
- The compiled `backend/static/` bundle is committed — always rebuild before commit.
- JSON `details` edits need `flag_modified` server-side (already handled in
  `routers/items.py`).
- Tests: `tests/` (pytest backend), `frontend/src/*.test.{js,jsx}` (vitest).
