# Pocket Money — Product Specification

> The behavioural source of truth. Data shapes live in
> [DATA_MODEL.md](DATA_MODEL.md); endpoints in [API.md](API.md).

## Purpose

A self-hosted web app for one family to manage kids' pocket money earned
through chores. Parents define chores with values and schedules; kids claim
completed chores; parents approve; balances accumulate in an auditable ledger.

## Roles

| Role | Who | Can do |
|---|---|---|
| **Administrator** | Parents | Everything below, plus all user actions on behalf of any user |
| **User** | Kids | View chores, submit claims, view own balance & history |

Single-family deployment: there is no household/tenant entity. Sign-in is
Google OAuth for everyone, restricted to an allowlist of family Google
accounts managed by administrators. A new allowlisted account signing in for
the first time gets a `user` role; admins can promote/demote.

## Chores

A chore is a recurring task with:

- **name** and optional **description**
- **value** — amount credited when an approved claim resolves (integer cents)
- **schedule** — how often it recurs: `daily`, `weekly` (choose weekdays),
  `monthly` (choose day of month), or `none` (always available / ad-hoc)
- **claim mode** — who can claim it and how often (see below)
- **assignees** — optionally restricted to specific users; default: any user
  may claim it
- **active** flag — inactive chores are hidden and unclaimable but kept for
  history

Administrators can add, modify, and remove (deactivate) chores. Removing a
chore never deletes historical claims against it.

The schedule determines when a chore is **due** (shown prominently on kids'
screens as their "chores due" list).

### Claim modes

Each chore is configured with one of three claim modes:

| Mode | Behaviour |
|---|---|
| `per_user` | Every eligible user has their own claimable instance per schedule period. When a user claims it, the schedule immediately lines up the next claimable instance **for that user**; other users' instances are unaffected. |
| `shared` | One claimable instance per period shared between users — first user to claim it gets it, then the schedule sets up the next period's instance. |
| `open` | Infinitely recurring: any user can claim it, and it becomes claimable again for anyone after a short cooldown (configurable per chore, default 5 minutes). |

Availability is derived from claim history rather than materialised
occurrence rows: a chore is claimable by user X when there is no
*pending-or-approved* claim in the current period by X (`per_user`), by
anyone (`shared`), or within the cooldown window (`open`). Rejected and
cancelled claims do **not** consume the slot — the chore becomes claimable
again.

## Claims

A claim is an assertion that a chore was done, routed for admin approval.

**Lifecycle:** `pending → approved | rejected` (terminal). Users may cancel
their own pending claims.

- A user submits a claim against a chore (optionally with a note).
- An administrator approves, modifies-then-approves, or rejects it.
- On approval, a credit transaction for the **approved value** is written to
  the user's ledger.

**Admin-originated claims:**

- Lodge and approve a claim **on behalf of** a user (e.g. kid told parent
  verbally).
- Lodge a **one-off** chore/claim against a user for a task that isn't a
  defined chore — optionally converting it into a recurring chore in the same
  flow.
- Lodge a **penalty** claim with a negative value (writes a debit on
  approval).

**Audit — every claim records:**

- who submitted the claim
- the user the claim applies to
- when it was submitted
- the original values of the claim (value, note, chore reference)
- who resolved it and when it was approved/rejected
- the final approved value (which may have been edited by an administrator
  during approval)

Resolved claims are immutable. Corrections are made by reversing via an
adjustment transaction and, if needed, lodging a new claim.

## Accounts & ledger

Each user has a balance derived from an **append-only transaction ledger**
(`balance = SUM(amount)`); balances are never stored as a mutable field.

Transaction types:

| Type | Sign | Created by |
|---|---|---|
| `claim_payout` | + | System, on claim approval |
| `penalty` | − | System, on penalty-claim approval |
| `withdrawal` | − | Admin, when money is paid out / spent |
| `adjustment` | ± | Admin, arbitrary balance correction (requires a note) |
| `allowance` | ± | System, weekly allowance run (see below) |

"Administrators can arbitrarily edit a user's balance" is implemented as an
adjustment transaction — the edit is recorded, not applied in place.

Balances may go negative (penalties/withdrawals are not blocked by
insufficient funds); the UI should highlight negative balances.

## Weekly allowance

Each user has an admin-configurable **weekly allowance** amount (default:
none). At the start of each week (Monday), a scheduled job writes an
`allowance` transaction for every user with a non-zero allowance. The value
may be negative (an automatic weekly deduction) — hence "added/removed".

The job is idempotent: at most one allowance transaction per user per ISO
week, so re-runs and missed-then-caught-up runs can't double-credit.
Changing a user's allowance affects future weeks only; past allowance
transactions are ledger history like any other.

## Notifications

No push infrastructure. Everything is either on-screen or a daily admin
email:

- **Kids:** the app home screen shows their **"chores due" list** — chores
  currently claimable by them, derived from schedule + claim mode.
- **Admins:** the app shows an **approval-due list** (pending claims queue),
  and a **once-per-day email digest** (cron-invoked,
  `scripts/send_admin_digest.py`) summarising pending claims awaiting
  approval. No email is sent when there is nothing pending.

Email goes out via SMTP (settings in server config, see
[DEVELOPMENT.md](DEVELOPMENT.md) env vars).

## Money & currency

Single currency for the whole app. Amounts are integer cents in storage and
API; the display symbol and format are app configuration (default: `$`,
two decimals). No conversion features.

## Non-goals (v1)

- Multi-family / multi-tenant support
- Multi-currency or currency conversion
- Interest or savings goals
- Web/mobile push notifications (on-screen lists + admin email only)
- Email ingestion of any kind
- Native mobile apps (responsive web only)
