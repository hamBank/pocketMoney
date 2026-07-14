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
- **assignees** — optionally restricted to specific users; default: any user
  may claim it
- **active** flag — inactive chores are hidden and unclaimable but kept for
  history

Administrators can add, modify, and remove (deactivate) chores. Removing a
chore never deletes historical claims against it.

The schedule determines when a chore is **due** (shown prominently to kids,
and used for chore-due notifications). A chore may be claimed once per
schedule period per user unless configured otherwise.

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

"Administrators can arbitrarily edit a user's balance" is implemented as an
adjustment transaction — the edit is recorded, not applied in place.

Balances may go negative (penalties/withdrawals are not blocked by
insufficient funds); the UI should highlight negative balances.

## Notifications

- **Chore due** — notify assignees when a chore enters its due window.
- **Weekly summary** — per-user digest: claims resolved, balance movement,
  current balance; admins additionally get pending-claim counts.

Delivered by a cron-invoked script (`scripts/send_notifications.py`).
**Open question:** delivery mechanism — web push (VAPID) vs email. Spec
assumes web push; revisit before implementation.

## Money & currency

Single currency for the whole app. Amounts are integer cents in storage and
API; the display symbol and format are app configuration (default: `$`,
two decimals). No conversion features.

## Non-goals (v1)

- Multi-family / multi-tenant support
- Multi-currency or currency conversion
- Interest, savings goals, or scheduled allowance not tied to chores
- Email ingestion of any kind
- Native mobile apps (responsive web only)

## Open questions

1. Notification delivery mechanism (web push vs email) — see above.
2. Should a chore be claimable by multiple kids in the same period (e.g.
   "empty dishwasher" done by whoever gets there first), or once per period
   total? Current assumption: once per period **per user**.
3. Do we want a scheduled base allowance (auto-credit per week) in v1? Easy
   to add as a system-generated transaction type later.
