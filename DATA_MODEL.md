# Pocket Money — Data Model

> SQLModel tables in `backend/models.py`. Behaviour in [SPEC.md](SPEC.md).
> All money fields are **integer cents**. All timestamps are UTC.

## Entity relationships

```
User ─┬─< Claim >─── Chore        (chore_id nullable: ad-hoc / penalty claims)
      │
      └─< Transaction >── Claim?  (claim_id set for claim_payout / penalty rows)
```

## Tables

### `user`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `google_sub` | str, unique, indexed | Google account subject ID |
| `email` | str, unique | must be on the allowlist to sign in |
| `name` | str | display name (editable, defaults from Google profile) |
| `avatar_url` | str, nullable | from Google profile |
| `role` | enum `admin` \| `user` | |
| `weekly_allowance` | int, default 0 | cents, signed; auto-applied each Monday (0 = no allowance) |
| `is_active` | bool, default true | deactivated users can't sign in; history kept |
| `created_at` | datetime | |

Balance is **not** a column — it is `SELECT COALESCE(SUM(amount),0) FROM
transaction WHERE user_id = :id`, exposed via API/schema.

### `chore`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `name` | str | |
| `description` | str, nullable | |
| `value` | int | cents credited on approval (default for claims) |
| `schedule` | enum `none` \| `daily` \| `weekly` \| `monthly` | |
| `schedule_config` | JSON, nullable | `{"weekdays":[0,5]}` or `{"day_of_month":1}` |
| `claim_mode` | enum `per_user` \| `shared` \| `open` | see SPEC.md claim modes |
| `cooldown_minutes` | int, default 5 | `open` mode only: delay before re-claimable |
| `assignee_ids` | JSON, nullable | list of user ids; null = any user may claim |
| `is_active` | bool, default true | soft delete — inactive chores hidden, history kept |
| `created_by` | int FK → user | |
| `created_at` | datetime | |
| `updated_at` | datetime | |

`schedule_config` is a JSON column — mutations need SQLAlchemy
`flag_modified` (see gotchas in [ARCHITECTURE.md](ARCHITECTURE.md)).

**Claimability is computed, not stored** — no occurrence table. A chore is
claimable by user X when no *pending-or-approved* claim exists in the
current schedule period by X (`per_user`), by anyone (`shared`), or within
the last `cooldown_minutes` (`open`). Rejected/cancelled claims free the
slot. Logic lives in `backend/schedule.py`.

### `claim`

Immutable after resolution. Original submission values are separate columns
from resolution values, satisfying the audit requirements in the spec.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `chore_id` | int FK → chore, nullable | null for ad-hoc / penalty claims |
| `user_id` | int FK → user | the user the claim applies to |
| `submitted_by` | int FK → user | who lodged it (user, or admin on behalf) |
| `submitted_at` | datetime | |
| `kind` | enum `chore` \| `adhoc` \| `penalty` | |
| `adhoc_name` | str, nullable | label for ad-hoc/penalty claims that have no chore |
| `original_value` | int | cents as submitted (negative for penalties) |
| `original_note` | str, nullable | submitter's note |
| `status` | enum `pending` \| `approved` \| `rejected` \| `cancelled` | |
| `approved_value` | int, nullable | final value — may differ from original if admin edited during approval |
| `resolution_note` | str, nullable | admin's note on resolution |
| `resolved_by` | int FK → user, nullable | |
| `resolved_at` | datetime, nullable | |

On approval the API creates the matching `transaction` row in the same DB
transaction as the status change.

### `transaction`

Append-only ledger. Rows are never updated or deleted; corrections are new
`adjustment` rows.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `user_id` | int FK → user, indexed | |
| `claim_id` | int FK → claim, nullable | set for `claim_payout` / `penalty` |
| `type` | enum `claim_payout` \| `penalty` \| `withdrawal` \| `adjustment` \| `allowance` | |
| `amount` | int | cents, signed (+ credit / − debit) |
| `note` | str, nullable | **required** for `adjustment`; allowance rows store the ISO week (e.g. `2026-W29`) |
| `created_by` | int FK → user, nullable | null for system rows (allowance); claim payouts use the resolving admin |
| `created_at` | datetime | |

Allowance idempotency: the weekly job skips a user if an `allowance` row
already exists for that ISO week (unique partial index or note lookup), so
re-runs never double-credit.

### `app_config` (optional, v1-simple)

Key/value store for runtime settings not worth env vars: currency symbol,
due-window hours, weekly-summary day. Can start as env vars and move here if
admins need a settings UI.

## Pydantic / API schemas

Each table gets the usual trio in `models.py`: `XCreate` (client → server),
`XUpdate` (partial), `XRead` (server → client). `UserRead` includes computed
`balance`. `ClaimRead` embeds `ChoreRead` and submitter/resolver display
names to keep list views one-request.

## Migrations

Alembic from day one (`alembic/`). SQLite locally and Postgres in production
are both exercised in CI (pytest runs against SQLite; a smoke job can run
against Postgres). Avoid Postgres-only column types so the SQLite dev path
keeps working.
