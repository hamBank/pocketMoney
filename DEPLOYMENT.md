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
`DEPLOY_SECRET`) → app creates `.deploy-trigger` → systemd **path unit**
(`PathExists`) starts `deploy.sh --update`.

The path-unit indirection means the deploy runs with root privileges without
the web app itself needing any.

How overlapping and failing deploys are handled (fleet spec DEP-3):

- `deploy.sh --update` **deletes `.deploy-trigger` first**. The path unit fires
  while the file exists, so a deploy that fails halfway cannot re-fire forever.
- A push that lands **during** a deploy re-creates the file, and the path unit
  starts the next deploy as soon as the running one ends. Nothing is dropped.
- A second `deploy.sh` (for example one run by hand while a webhook deploy is in
  flight) takes `/var/lock/pmoney-deploy.lock`, so it **waits** for the first
  rather than overlapping it, for up to 30 minutes, and then fails loudly. It
  waits instead of skipping because it has already consumed its trigger, and its
  own fetch picks up whatever was pushed meanwhile.
- The path unit is a systemd unit, so changing it takes a full `sudo ./deploy.sh`
  (which also restarts it), never `--update`.

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

## Monitoring (Prometheus)

Set up the same way as travelCompantion (fleet spec OBS-2).

- `GET /metrics` serves `pmoney_external_requests_total{service, status}` (`status` is
  `success` or `error`; `service` is `google_sheets`, `google_oauth` or `smtp`). It is
  unauthenticated, like `/health`: a scraper carries no JWT and the content is aggregate
  counts with no personal data.
- `docs/prometheus-alerts.yml` holds the alert rules. **It does not install itself.** After
  any change, on the Prometheus host:

  ```bash
  sudo cp docs/prometheus-alerts.yml /etc/prometheus/rules/pmoney.yml
  sudo promtool check rules /etc/prometheus/rules/pmoney.yml
  sudo systemctl reload prometheus
  ```

  `prometheus.yml` must load the file and scrape this app. `rule_files` takes file **globs**,
  not a directory, and a file the list doesn't cover is silently ignored, so check:
  `rule_files: [/etc/prometheus/rules/*.yml]` (keep that directory to rules files only, and
  reload after adding one). On the server this glob was added on 2026-11-09; before that
  `rule_files` listed each file individually, so a file dropped into `rules/` was never
  loaded. If a file is both listed explicitly and inside `rules/`, drop the explicit entry.
  Then confirm with
  `curl -sSG localhost:9090/api/v1/rules | python3 -m json.tool | grep -E '"name"|"health"'`:
  a `pmoney-external-apis` group with `PmoneyExternalApiErrors` and
  `PmoneyExternalApiHighErrorRate`, both `"health": "ok"`. The scrape job:

  ```yaml
  scrape_configs:
    - job_name: pmoney
      static_configs:
        - targets: ['127.0.0.1:8001']
  ```

  If it runs elsewhere, scrape `https://pmoney.hups.club/metrics` instead (`scheme: https`,
  target `pmoney.hups.club`), which is also how it is set up on the server today.
- **What is not counted.** The counters live in the web process. The timer jobs (the
  10-minute sheet sync, the weekly allowance, the digest email) run in their own
  processes, which serve no `/metrics`, so calls made there are invisible. A sheet sync
  that fails only from its timer will not trip these alerts. The same limit applies to
  travelCompantion's cron jobs. See the closing section of `docs/plans/obs-2-metrics.md`
  for the options if that matters.
- Alerts that don't fire when you expect them to: check the rules file was actually copied
  and reloaded, and that Prometheus shows the `pmoney` target as up.

## Backups

`pmoney-backup.timer` dumps the database nightly at 02:30 to
`/var/backups/pmoney/pmoney-<weekday>.sql.gz` (7-day rotation); the unit
fails if `pg_dump` fails, and the smoke check warns when the newest dump
is over 36h old.

A separate backup server *pulls* them off-box (below).

## Off-box backups

`/var/backups/pmoney` is on the same disk as the app, so it doesn't survive losing the
server (fleet spec DEP-6). A separate, locked-down **backup server** *pulls* a copy over
rsync/ssh, the same design as recipeFlood's and travelCompantion's.

```
 app server (camelidcastle)                    backup server
 ──────────────────────────                    ─────────────
 02:30 pmoney-backup                           every 6 h (:35)  pmoney-pull-backup.timer
   └ /var/backups/pmoney/pmoney-<1-7>.sql.gz                    └ pmoney-pull-backup.sh
 user pmbackup (read-only key)  ◄──────────── rsync over ssh (key + pinned host key)
 forced: rrsync -ro /var/backups/pmoney               └ verify · file dated copies · freshness · prune
```

**Pull, not push**: the app server holds no credentials for the backup server, so a compromised
app can't reach or delete the copies. The app-side key can only run a read-only rsync inside
`/var/backups/pmoney` (`rrsync -ro`): no shell, no writes, no other paths. That puts `.env`
out of its reach by path, and `add_backup_reader.sh` also checks the user can't read it.

**What it keeps.** The app's dumps are named by weekday and overwritten a week later, so the
pull files every new one under a dated name (`dumps/pmoney-YYYYMMDD-HHMMSS.sql.gz`) and keeps
90 days of them, never fewer than 7. The app writes each dump to a `.tmp` file and renames it,
so a pull never sees a half-written one and a failed dump never replaces the last good one.

**Not copied, on purpose: `.env`.** A restored database works without it, but the server
doesn't: it holds `JWT_SECRET`, the Google OAuth client, the SMTP password and the Sheet
settings. Keep a copy of `.env` (and `google-service-account.json`) in your password manager.

### Setup

**1. Backup server** (as root, from a checkout of this repo):

```bash
sudo deploy/backup-server/install.sh
```

Creates user `pmpull`, an ed25519 key, `/etc/pmoney-pull-backup.conf`, the backup directory
`/lklBackup/sites_apps/pocketMoney`, the service and the timer (enabled). It prints the next
steps with your public key filled in.

**2. App server** (as root): authorise that key. `--from` restricts it to the backup server's IP.

```bash
echo '<the public key install.sh printed>' | sudo scripts/add_backup_reader.sh --from <backup-server-ip> -
```

This creates the login-less `pmbackup` user, installs the key as
`restrict,from="…",command="rrsync -ro /var/backups/pmoney"`, then checks that `pmbackup`
**can** read every dump and **cannot** read `/opt/pocketMoney/.env`. Needs the `rsync` package
(it provides `rrsync`; a full `deploy.sh` installs it), and sshd must allow the user
(`AllowUsers`, if you use it).

**3. Backup server**: check `SRC_HOST=pmbackup@<app-host>` in `/etc/pmoney-pull-backup.conf`
and pin the app server's host key. The script uses `StrictHostKeyChecking=yes`, so an unknown or
changed key fails the run instead of prompting. Compare the fingerprint from
`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` on the app server with what you scan here:

```bash
sudo -u pmpull ssh-keyscan -t ed25519 <app-host> | sudo -u pmpull tee -a /var/lib/pmoney-backup/.ssh/known_hosts
sudo -u pmpull ssh-keygen -lf /var/lib/pmoney-backup/.ssh/known_hosts
```

**4. First run, through systemd** (not only by hand: the unit is sandboxed, and a path that works
by hand can be read-only under it):

```bash
sudo systemctl start pmoney-pull-backup.service
journalctl -u pmoney-pull-backup.service -n 20   # expect "✓ ok: N dump(s), newest Xh old; …"
systemctl list-timers pmoney-pull-backup.timer
```

The copies go to **`/lklBackup/sites_apps/pocketMoney`** on the backup disk. The unit sets that
path once as `Environment=DEST=`, next to the two lines that make it work under the sandbox:
`ReadWritePaths=` (without it `ProtectSystem=strict` makes the disk read-only, so a pull that
works by hand fails under systemd) and `RequiresMountsFor=` (if the disk isn't mounted the pull
fails instead of filling the root filesystem). `install.sh` creates the directory, owned by
`pmpull` with mode 0700, and refuses if `/lklBackup/sites_apps` doesn't exist. To move the
copies, change all three lines together.

### What a failed run means

The unit exits non-zero (and shows in `systemctl --failed`) when:

| Message | Cause |
|---|---|
| `rsync of the backups failed (exit …)` | ssh/key/host-key/permission problem; the line above it says which |
| `not a complete backup: …` | A file failed `gzip -t` or has no `dump complete` marker. It's moved to `quarantine/` and fetched again next run |
| `… differs from the copy already filed …` | A file changed without its timestamp changing. Look before trusting either copy |
| `newest database dump is Nh old` | **The app server's own backup stopped.** Check `systemctl status pmoney-backup` there |
| `… has never run` | The app server has no dump at all |

For an alert, point `OnFailure=` in the service at a unit that mails or pushes you (there is a
commented line for it). Without one, check `systemctl --failed` now and then, or look at
`/lklBackup/sites_apps/pocketMoney/last-success`, which holds the time of the last good pull.

### Restore drill (do this once, then yearly)

A backup you haven't restored is only a hope. On any machine with Postgres client tools:

```bash
B=/lklBackup/sites_apps/pocketMoney
gunzip -c "$B"/dumps/pmoney-<newest>.sql.gz | head -20                # readable?
createuser pocketMoney          # the dump's OWNER TO lines need it; skip if it exists
createdb pm_restore_test
gunzip -c "$B"/dumps/pmoney-<newest>.sql.gz | psql -q -v ON_ERROR_STOP=1 pm_restore_test
psql pm_restore_test -c 'select count(*) from claim'
psql pm_restore_test -c 'select version_num from alembic_version'   # the schema revision
dropdb pm_restore_test
```

Without the `pocketMoney` role, `ON_ERROR_STOP` stops at the first `OWNER TO` line and restores
nothing. Also confirm you can find `.env` in your password manager.

### Rotating the key / removing access

Re-run `add_backup_reader.sh` with the new public key (it replaces the old `pm-offsite-backup`
line), or delete that line from `/var/lib/pmbackup/.ssh/authorized_keys` to cut access at once.

### Tests

`tests/test_pull_backup.py` runs the real script and rsync against a local stand-in for the
backup directory: the pull, the dated history (including a weekday file overwritten at the
source), verification and recovery after a quarantined file, the freshness check, retention,
and the key builder's refusal of injected options. Two tests route the pull through the real
`rrsync -ro` forced command, which allows reads under the root and refuses a path outside it, a
push and a shell. Not covered: ssh itself and running under systemd. The first run in step 4 is
that check.
