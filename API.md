# Pocket Money — API Reference

> FastAPI routers in `backend/routers/`. All endpoints require a bearer JWT
> unless noted. Admin-only endpoints return 403 for `user` role. Money is
> integer cents.

## Auth — `routers/auth_router.py`

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/auth/google` | public | Exchange Google ID token for app JWT. Rejects emails not on the allowlist. First sign-in creates the `user` row. |
| GET | `/auth/me` | any | Current user profile + role + balance |
| GET | `/auth/config` | public | Client bootstrap: Google client ID, `AUTH_ENABLED`, currency symbol/format |

## Chores — `routers/chores.py`

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/chores` | any | List chores. Users see active chores available to them with a computed `claimable` flag (per claim mode + schedule — this drives the kid "chores due" list); `?all=true` (admin) includes inactive |
| POST | `/chores` | admin | Create chore |
| GET | `/chores/{id}` | any | Chore detail |
| PATCH | `/chores/{id}` | admin | Modify (value, schedule, assignees, active flag) |
| DELETE | `/chores/{id}` | admin | Deactivate (soft delete; history kept) |

## Claims — `routers/claims.py`

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/claims` | any | Users: own claims. Admin: all; filters `?status=pending&user_id=&chore_id=` |
| POST | `/claims` | any | User claims a chore (`chore_id`, optional note). Admin extras: `user_id` (on behalf of), `kind=adhoc` with ad-hoc name/value, `kind=penalty` with negative value, `auto_approve=true`, `create_chore=true` (promote an ad-hoc into a recurring chore in the same call) |
| POST | `/claims/{id}/approve` | admin | Approve; optional `approved_value` / `resolution_note` override. Writes the ledger transaction atomically |
| POST | `/claims/{id}/reject` | admin | Reject with optional note |
| POST | `/claims/{id}/cancel` | owner | Submitter cancels own pending claim |

Resolved claims are immutable — no PATCH after resolution.

## Users & ledger — `routers/users.py`, `routers/transactions.py`

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/users` | admin | List users with balances |
| PATCH | `/users/{id}` | admin | Role, active flag, display name, `weekly_allowance` (cents, signed) |
| GET | `/users/{id}/balance` | owner/admin | Current balance (ledger sum) |
| GET | `/transactions` | owner/admin | Ledger history; `?user_id=` (admin), paginated, newest first |
| POST | `/transactions` | admin | Record `withdrawal` or `adjustment` (adjustment requires `note`) |

Allowlist management (who may sign in) lives under `PATCH /users` +
`POST /users/invite` (admin adds an email before the person first signs in).

## Ops — `backend/main.py`

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | `/health` | public | Liveness: DB reachable, version |
| POST | `/deploy` | HMAC | Redeploy webhook (`DEPLOY_SECRET`-signed); touches `.deploy-trigger` |
| GET | `/{spa_path}` | public | Static mount serving the compiled SPA (catch-all → `index.html`) |

Cron entry points (not HTTP): `scripts/send_admin_digest.py` (daily admin
email: pending claims + that day's submitted/approved claim activity) and
`scripts/apply_weekly_allowance.py` (Monday allowance run, idempotent per
ISO week).

## Conventions

- Errors: FastAPI-standard `{"detail": ...}`; 401 unauthenticated, 403 wrong
  role, 404 not found or not yours, 409 for invalid state transitions (e.g.
  approving a non-pending claim).
- Pagination: `?limit=&offset=` with `X-Total-Count` header on list endpoints
  that can grow (claims, transactions).
- All mutation endpoints validate role server-side via `permissions.py`
  dependencies — the frontend hiding a button is never the security boundary.
