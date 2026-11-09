# Pocket Money — Deployment

> Production: `https://pmoney.hups.club` on `camelidcastle.hups.club`
> (Debian/Ubuntu).

## Topology

- **App:** uvicorn serving `backend.main:app` on `127.0.0.1:8001`, run by
  systemd unit `pmoney`, as system user `pocketMoney`, from
  `/opt/pocketMoney`.
- **Web:** Apache vhost `pmoney.hups.club.conf` — TLS termination + reverse
  proxy to :8001. The FastAPI app serves both the API and the built SPA, so
  Apache proxies everything.
- **DB:** Postgres, database `pmoney` (local to the server).
- **Scheduled jobs:** systemd timers with oneshot services, from
  `deploy/pmoney-<job>.{service,timer}` (fleet spec DEP-5). Each service
  loads `/opt/pocketMoney/.env` via `EnvironmentFile` and logs to journald.

  | unit | runs | when |
  |---|---|---|
  | `pmoney-digest` | `scripts/send_admin_digest.py` | daily 18:00 |
  | `pmoney-allowance` | `scripts/apply_weekly_allowance.py` (idempotent per ISO week) | Mondays 06:00 |
  | `pmoney-sheet-sync` | `scripts/sync_sheet.py` (no-op without `GOOGLE_SHEET_ID`) | every 10 min |
  | `pmoney-backup` | `pg_dump pmoney` (as `postgres`) | daily 02:30 |

  Times are the server's local time, as the old cron jobs were. Units are
  installed and enabled by a full `sudo ./deploy.sh`, never by `--update`
  (a `daemon-reload` inside the running deploy unit loops). These replaced
  the old `/etc/cron.d/pocketmoney` (removed from prod 2026-11-05); never
  run a job from cron as well, or the digest is sent twice.

## Repo access (deploy key)

The repo is public (since 2026-11-09, so GitHub auto-merge is available), but
the server still clones it over SSH with a read-only deploy key belonging to the
`pocketMoney` system user, so nothing changes if it goes private again. Never
commit secrets: anyone can read the repo and its history.

```bash
sudo -u pocketMoney ssh-keygen -t ed25519 -N "" -f /home/pocketMoney/.ssh/id_ed25519
sudo -u pocketMoney cat /home/pocketMoney/.ssh/id_ed25519.pub
```

Add the printed public key under **repo → Settings → Deploy keys** with
write access **off**, *before* the first `deploy.sh` run. `deploy.sh`
verifies the key exists, seeds `known_hosts` via `ssh-keyscan`, and
converges any older HTTPS checkout onto the SSH remote
(`git@github.com:hamBank/pocketMoney.git`).

## Provisioning — `deploy.sh`

Idempotent script that:

1. Installs OS packages (python, node, postgres client, apache modules)
2. Creates the `pocketMoney` system user and `/opt/pocketMoney`
3. Clones/updates the repo, creates the venv, installs requirements
4. Builds the frontend (`npm ci && npm run build` → `backend/static/`)
5. Checks the config the service will start with (`scripts/check_config.py`,
   e.g. no default `JWT_SECRET`) and aborts before touching the running
   service if it would not start
6. Runs `alembic upgrade head`
7. Installs/refreshes the systemd service, path unit and timers, and installs
   the Apache vhost only if it is missing or still identical to the repo copy
   (once certbot has edited it, or `pmoney.hups.club-le-ssl.conf` exists, it is
   left alone and logged). Apache is reloaded only after `apachectl configtest`
   passes; a failed test aborts the provision (fleet spec DEP-8)
8. Restarts the service and runs `scripts/smoke_check.sh` (below); a failed
   check makes `deploy.sh` exit non-zero, so `pmoney-deploy.service` shows
   as failed

`deploy.sh --update` runs steps 3–6 and 8 (used by the webhook path below).
Any failure logs `ERROR: deploy.sh:<line>: <command> exited <rc>` to
`/var/log/pocketMoney-deploy.log`.

The built `backend/static/` is produced on the server at deploy time — it is
**not** committed to the repo.

## Auto-redeploy webhook

A push to `main` → GitHub webhook `POST /deploy` (HMAC-signed with
`DEPLOY_SECRET`) → app touches `.deploy-trigger` → systemd **path unit**
watches that file and runs `deploy.sh --update`.

The path-unit indirection means the deploy runs with root privileges without
the web app itself needing any.

## Google OAuth setup (one-time, manual)

1. Go to <https://console.cloud.google.com/> and create a project (e.g.
   "Pocket Money").
2. **APIs & Services → OAuth consent screen**: choose **External**, fill in
   the app name and your email. Add your family members' Google accounts as
   **Test users** — an app in "Testing" status only allows listed test users,
   which is exactly the allowlist behaviour we want; there is no need to
   publish the app.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Web application**
   - Authorized JavaScript origins: `https://pmoney.hups.club`
     (add `http://localhost:5173` and `http://localhost:8000` for local
     testing with real Google sign-in)
   - No redirect URIs are needed — the app uses Google Identity Services'
     ID-token flow, not a redirect flow.
4. Copy the **Client ID** (ends in `.apps.googleusercontent.com`) into
   `GOOGLE_CLIENT_ID` in `/opt/pocketMoney/.env`.
5. Put the family's Gmail addresses in `ALLOWED_EMAILS` (comma-separated).
   The **first** of them to sign in becomes the admin; invite/promote the
   rest from the app's Users tab afterwards.

No client secret is required anywhere: the backend only *verifies* Google's
ID tokens against the client ID.

## Gmail App Password setup (one-time, manual)

The admin daily digest (`scripts/send_admin_digest.py`) sends through Gmail's
SMTP relay. This is a **separate** Google credential from `GOOGLE_CLIENT_ID`
above — it authenticates the *server* to send mail, not a user signing in.
Any Gmail address works, including one dedicated just for this (recommended,
so a personal inbox's password never lives in `.env`).

1. On that Gmail account: **Google Account → Security → 2-Step Verification**
   — must be turned on; App Passwords aren't offered without it.
2. **Google Account → Security → App passwords** (search "App passwords" if
   the link isn't visible) → create one, name it "Pocket Money" → copy the
   16-character password shown (spaces don't matter, Google ignores them).
3. In `/opt/pocketMoney/.env`:
   ```
   SMTP_USER=that-address@gmail.com
   SMTP_PASSWORD="the 16-character app password"
   ```
   `SMTP_HOST`/`SMTP_PORT` already default to `smtp.gmail.com`/`587` — no
   need to set them unless using a different provider. `SMTP_FROM` is
   optional (defaults to `SMTP_USER`); set it to e.g.
   `SMTP_FROM="Pocket Money <that-address@gmail.com>"` for a friendlier
   display name. Quote any value containing spaces or `<>` (see
   Configuration below).
4. `sudo systemctl restart pmoney`, then trigger a digest run manually to
   confirm delivery: `sudo systemctl start pmoney-digest.service` (check it
   with `journalctl -u pmoney-digest -n 20`).

A regular Gmail password will **not** work here (Google rejects it) — it
must be an App Password. Leaving `SMTP_USER` unset is fine too: the digest
just prints to the service log (`journalctl -u pmoney`) instead of emailing.

## Google Sheets ledger mirror setup (one-time, manual, optional)

The app can mirror the ledger into a Google Sheet: one append-only tab per
child plus a **Totals** tab (see SPEC.md). It writes as a Google Cloud
**service account** — a separate credential from both `GOOGLE_CLIENT_ID`
and the Gmail App Password. Full step-by-step instructions (project, API,
service account, JSON key, sharing, `.env`, backfill, troubleshooting, key
rotation) are in **[SHEETS_SETUP.md](SHEETS_SETUP.md)**. In short:

1. Enable the **Google Sheets API** in a Google Cloud project; create a
   service account (no roles) and download a **JSON key**.
2. Share a blank sheet with the service account's email as **Editor**.
3. Install the key as `/opt/pocketMoney/google-service-account.json`
   (owner `pocketMoney`, mode 600) and set `GOOGLE_SHEET_ID`,
   `GOOGLE_SERVICE_ACCOUNT_FILE`, `SHEET_TIMEZONE` in `.env`.
4. `sudo systemctl restart pmoney`, then backfill with
   `scripts/sync_sheet.py`; the 10-minute `pmoney-sheet-sync` timer keeps it caught up.

## Configuration

Environment for the service lives in `/opt/pocketMoney/.env` (loaded by the
systemd unit; not in the repo): `DATABASE_URL`, `GOOGLE_CLIENT_ID`,
`JWT_SECRET`, `ALLOWED_EMAILS`, `DEPLOY_SECRET`, `CURRENCY_SYMBOL`, plus
Gmail SMTP settings for the admin digest (`SMTP_HOST`, `SMTP_PORT`,
`SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` — see Gmail App Password setup
above) and the optional Google Sheets mirror (`GOOGLE_SHEET_ID`,
`GOOGLE_SERVICE_ACCOUNT_FILE`, `SHEET_TIMEZONE` — see above).

The same file is also sourced by bash (`set -a && . ./.env`) in `deploy.sh`
for alembic, so it must be valid for both systemd and bash: plain
`KEY=value` lines, no `export`, and **double-quote any value containing
spaces or shell characters** (`SMTP_PASSWORD="abcd efgh ijkl mnop"`).

With `AUTH_ENABLED=true` (the default), `JWT_SECRET` **must** be set to a
long random value: the app refuses to start with it empty or equal to the
public default, and the deploy aborts at the config check rather than
restart into a crash loop.

## Logs & operations

```bash
journalctl -u pmoney -f                      # app logs
tail -f /var/log/pocketMoney-deploy.log      # deploy runs (timestamped headers)
systemctl list-timers 'pmoney-*'             # scheduled jobs: last/next run
journalctl -u pmoney-digest -n 40            # one job's output (digest, allowance, sheet-sync, backup)
systemctl restart pmoney                     # manual restart
sudo systemctl start pmoney-backup.service   # DB backup now
```

## Verifying a deploy

Every deploy runs `scripts/smoke_check.sh` after the restart (fleet spec
DEP-4) and fails if it fails. It waits up to 60s for `/health`, then checks:

- `status` is `ok` (the DB answered);
- `backend_sha` **and** `build_sha` both equal the checked-out `HEAD` —
  the new code is running and the frontend was rebuilt from it;
- every `pmoney-*.timer` is enabled and its service's last run succeeded
  (a disabled timer only warns);
- the newest `/var/backups/pmoney/*.sql.gz` is under 36h old (warns only).

By hand:

```bash
curl -s https://pmoney.hups.club/health
# {"status":"ok","backend_sha":"6420c36","frontend_sha":"5f1e2d3","build_sha":"6420c36","built_at":"...","started_at":"..."}
sudo -u pocketMoney bash /opt/pocketMoney/scripts/smoke_check.sh http://127.0.0.1:8001 "$(git -C /opt/pocketMoney rev-parse --short HEAD)"
```

`frontend_sha` is the last commit that changed `frontend/src`, so it lags
`build_sha` after backend-only deploys; that is expected. Open browser tabs
compare it with the bundle they are running and offer a reload when it
changes. If `build_sha` differs from `backend_sha`, the frontend build
failed or was skipped — check `/var/log/pocketMoney-deploy.log` and rerun
`sudo ./deploy.sh --update`.

## Backups

`pmoney-backup.timer` dumps the database nightly at 02:30 to
`/var/backups/pmoney/pmoney-<weekday>.sql.gz` (7-day rotation); the unit
fails if `pg_dump` fails, and the smoke check warns when the newest dump
is over 36h old.

**Still TODO (fleet spec DEP-6): an off-box copy.** The dumps live on the
same VM as the database, so losing the VM loses both. Pick a destination
(another host, object storage) and add a step after the dump.
