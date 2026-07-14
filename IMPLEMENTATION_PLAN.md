# Pocket Money — Implementation Plan

> Phased build order for the from-scratch app defined in [SPEC.md](SPEC.md) /
> [DATA_MODEL.md](DATA_MODEL.md) / [API.md](API.md). Each phase ends with
> working, tested software; later phases never require reworking earlier ones.
> Tick items off as they land.

## Phase 0 — Scaffolding

- [ ] Python project: `backend/` package, `requirements.txt` (fastapi,
      sqlmodel, alembic, uvicorn, google-auth, pyjwt, pytest, httpx)
- [ ] `backend/main.py` app factory, `/health`, config loading from env
- [ ] `backend/database.py`: engine from `DATABASE_URL` (SQLite default),
      session dependency; Alembic init with first empty migration
- [ ] Frontend: Vite + React + Tailwind in `frontend/`, dev proxy `/api` →
      :8000, `npm run build` → `backend/static/`; static mount + SPA
      catch-all in `main.py`; `backend/static/` gitignored
- [ ] Test rigs: pytest with per-test SQLite + FastAPI `TestClient`; vitest
- [ ] CI (GitHub Actions): pytest + vitest + frontend build on PR

**Exit:** `uvicorn backend.main:app` serves the built SPA and `/health`; CI green.

## Phase 1 — Auth & users

- [ ] `user` table + migration
- [ ] `POST /auth/google`: verify Google ID token, enforce allowlist
      (`ALLOWED_EMAILS` bootstrap + invited users), create user on first
      sign-in, issue app JWT
- [ ] `auth.py` JWT issue/verify; `permissions.py` role dependencies;
      `AUTH_ENABLED=false` dev bypass (fake admin)
- [ ] `GET /auth/me`, `GET /auth/config`; `GET/PATCH /users`,
      `POST /users/invite` (admin)
- [ ] Frontend: `LoginPage` (Google Sign-In), auth gate in `App.jsx`,
      `api.js` fetch wrapper with bearer token

**Exit:** family members can sign in; admins can invite and manage users.

## Phase 2 — Chores

- [ ] `chore` table + migration (schedule, claim_mode, cooldown, assignees)
- [ ] `backend/schedule.py`: period calculation (daily/weekly/monthly/none)
      and `is_claimable(chore, user, now)` implementing the three claim
      modes from claim history — **pure functions, heavily unit-tested**
      (this is the trickiest logic in the app; build it before the UI)
- [ ] `/chores` CRUD router; list returns computed `claimable` per user
- [ ] Frontend: `ChoreManager` (admin CRUD) and `ChoreList` (kid "chores
      due" view with claim button, disabled until claimable)

**Exit:** admins define chores; kids see a correct chores-due list per mode.

## Phase 3 — Claims & ledger (the core)

- [ ] `claim` + `transaction` tables + migration
- [ ] `POST /claims` (user path): validates claimability, records original
      values; `POST /claims/{id}/cancel`
- [ ] Approve/reject endpoints: status change + `claim_payout`/`penalty`
      transaction written **in one DB transaction**; immutability guards
      (409 on re-resolution)
- [ ] Admin claim extras: on-behalf-of, `adhoc`, `penalty`, `auto_approve`,
      `create_chore` promotion
- [ ] `/transactions`: history + admin `withdrawal`/`adjustment` (note
      required); balance = ledger sum on `UserRead`
- [ ] Frontend: claim submission from `ChoreList`, `ApprovalQueue` (admin:
      approve / edit-value-then-approve / reject), `ClaimHistory` +
      balance display, `UserManager` payouts & adjustments
- [ ] Tests: full lifecycle (submit → approve → balance), value-edited
      approval preserves original, penalty flow, ledger append-only
      invariants, per-mode re-claimability after reject/cancel

**Exit:** the end-to-end pocket money loop works — this is the MVP.

## Phase 4 — Allowance & admin digest

- [ ] `weekly_allowance` on user (+ `UserManager` field)
- [ ] `scripts/apply_weekly_allowance.py`: Monday run, one `allowance`
      transaction per user per ISO week (idempotent; tested for re-runs)
- [ ] `backend/emails.py` SMTP sender (logs to stdout when unconfigured);
      `scripts/send_admin_digest.py`: daily digest to admin emails —
      pending claims + claims submitted/resolved since the previous run
      (approved values flagged when edited); silent when there is nothing
      pending and no activity

**Exit:** allowances land every Monday; parents get the daily email.

## Phase 5 — Polish

- [ ] Themes (`themes.js`, CSS variables), `ThemePicker`, `UserSettings`
- [ ] Negative-balance highlighting; pagination on claims/transactions
      (`X-Total-Count`); empty states; responsive/mobile pass
- [ ] `scripts/seed_dev_data.py` fixtures

## Phase 6 — Production

- [ ] `deploy.sh` per [DEPLOYMENT.md](DEPLOYMENT.md): packages, system user,
      `/opt/pocketMoney`, venv, `npm ci && npm run build`,
      `alembic upgrade head`, systemd service + path unit, Apache vhost,
      cron entries for the two scripts
- [ ] `/deploy` HMAC webhook + `.deploy-trigger`; GitHub webhook on `main`
- [ ] Postgres database `pmoney`; nightly `pg_dump` backup job
- [ ] Google OAuth production credentials for `pmoney.hups.club`; smoke test

**Exit:** push to `main` auto-deploys; family onboarded.

## Sequencing notes

- Phases are strictly ordered; within a phase, backend before frontend.
- `schedule.py` (Phase 2) is deliberately isolated and pure so claim-mode
  edge cases (period boundaries, cooldowns, rejected claims freeing slots)
  are testable without HTTP or a browser.
- Deploy tooling last: until Phase 6 the app runs locally on SQLite, which
  is all the earlier phases need.
