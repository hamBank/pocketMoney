# Pocket Money — Claude Instructions

## Project
Family pocket-money ledger: kids claim chores, admins approve, every change is an
append-only transaction. FastAPI + SQLModel + Alembic backend, React + Vite + Tailwind
frontend built into `backend/static/` and served by the same uvicorn process
(`127.0.0.1:8001` behind Apache at `pmoney.hups.club`). Reference docs: `ARCHITECTURE.md`,
`DATA_MODEL.md`, `API.md`, `DEPLOYMENT.md`, `DEVELOPMENT.md`, `SPEC.md`.

## Running the app
```bash
AUTH_ENABLED=false python -m uvicorn backend.main:app --reload   # :8000
cd frontend && npm run dev                                       # :5173, proxies the API
```
Authentication fails closed (fleet spec CFG-2): with auth enabled (the default) the app
refuses to start while `JWT_SECRET` is unset or the public default. Local dev, `alembic`
and `scripts/*.py` therefore say `AUTH_ENABLED=false` on purpose; `tests/conftest.py`
sets its own secret.

## Tests
```bash
pytest                                          # backend, SQLite
TEST_DATABASE_URL=postgresql+psycopg:///db pytest   # the same suite on Postgres
cd frontend && npm run lint && npm test
```
CI (`.github/workflows/ci.yml`) runs `backend` (SQLite), `backend-postgres` (migrations up,
`check`, `downgrade base`, up again, then the whole suite), `frontend` (lint, test, build) and
`fleet-spec` (conformance).

## Database & schema migrations
Alembic owns the schema; the models are the source of truth. After changing a model:
`AUTH_ENABLED=false alembic revision --autogenerate -m "..."`, review it, then `alembic upgrade
head` and `alembic check` (CI fails on drift). Tests build the schema with `create_all()`.
Migrations must run on SQLite **and** Postgres, and `downgrade()` must undo everything
`upgrade()` created, including Postgres enum types.

## Frontend build
`backend/static/` is build output: gitignored, never committed. `deploy.sh --update` builds it
on every deploy after checking out the commit. `npm run build` writes `version.json`
(`build_sha` = HEAD, `frontend_sha` = last commit touching `frontend/src`) and fails if it
can't tell which commit it is building (pass `BUILD_SHA` without a git checkout). `/health`
reports `backend_sha`, `build_sha`, `frontend_sha`, `built_at`, `started_at`; the bundle polls
it and offers a reload when `frontend_sha` changes.

## Deploy
Push to `main` → webhook → `deploy.sh --update`: pull, `pip install`, `scripts/check_config.py`
(aborts before touching the running service), `alembic upgrade head`, frontend build,
restart, then `scripts/smoke_check.sh`, which fails the deploy unless `/health` is ok,
`backend_sha == build_sha == HEAD`, and every `pmoney-*.timer` job last succeeded. New or
changed systemd units are installed only by a full `sudo ./deploy.sh`, never by `--update`.

## Git workflow
Branch from fresh `origin/main` → run both test suites → PR (non-draft) → CI green →
squash-merge → the webhook deploys → verify `/health` `backend_sha` and `build_sha`. After
each squash-merge, reset your branch onto `origin/main`.

## Fleet spec — conformance is checked in CI
This app follows `hamBank/fleetSpec`. `.fleet-spec.yml` lists the deviations (rule, reason,
`until` date). CI fails on a new MUST violation, an expired deviation, or a stale one: when
you fix a deviation, delete its entry in the same PR.

## Incident rules
- **Never pass a function reference to `useEffect`.** 2026-07-14: leaving the Chores or Users
  tab blanked the whole page, because an async `refresh` returned a Promise that React then
  called as the cleanup function. Nothing caught it because no test unmounted a tab. Now an
  ESLint rule forbids the pattern and `mount-unmount.test.jsx` unmounts every tab.
- **Instants are aware UTC; compare aware with aware.** 2026-10-07: sqlmodel 0.0.48 started
  rejecting naive datetimes, so the digest would have crashed after the next deploy. CI didn't
  catch it on its own because requirements had no upper bounds. Now sqlmodel is pinned to
  0.0.48.x and every dependency is capped.
- **Timestamp columns are `timestamptz`.** 2026-10-25: migrations had created
  `timestamp without time zone`; on a server whose Postgres TimeZone isn't UTC, values were
  stored as local time and read back as UTC (shifted 10–11h in Canberra). SQLite-only tests
  can't see this; `alembic check` and the Postgres CI job now do.
- **Scripts read real env vars, and `.env` must parse in both systemd and bash.** 2026-10-07:
  the cron digest and allowance jobs silently fell back to the SQLite/no-SMTP defaults because
  cron didn't load `.env`. Scheduled jobs are now systemd timers with `EnvironmentFile=`;
  double-quote any `.env` value with spaces.
- **A deploy must fail loudly.** Until 2026-11, a deploy was verified by someone remembering
  to `curl /health`. `deploy.sh` now runs the smoke check and exits non-zero.
