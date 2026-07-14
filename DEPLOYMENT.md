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
- **Cron:** `scripts/send_admin_digest.py` (daily — admin email digest of
  pending claims) and `scripts/apply_weekly_allowance.py` (Mondays —
  idempotent allowance transactions).

## Repo access (deploy key)

The repo is **private**; the server clones it over SSH with a read-only
deploy key belonging to the `pocketMoney` system user:

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
5. Runs `alembic upgrade head`
6. Installs/refreshes the systemd service, path unit, and Apache vhost
7. Restarts the service

`deploy.sh --update` runs only steps 3–7 (used by the webhook path below).

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

## Configuration

Environment for the service lives in `/opt/pocketMoney/.env` (loaded by the
systemd unit; not in the repo): `DATABASE_URL`, `GOOGLE_CLIENT_ID`,
`JWT_SECRET`, `ALLOWED_EMAILS`, `DEPLOY_SECRET`, `CURRENCY_SYMBOL`, plus
SMTP settings for the admin digest (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASSWORD`, `SMTP_FROM`).

## Logs & operations

```bash
journalctl -u pmoney -f                      # app logs
tail -f /var/log/pocketMoney-deploy.log      # deploy runs (timestamped headers)
systemctl restart pmoney                     # manual restart
sudo -u postgres pg_dump pmoney > backup.sql # DB backup
```

## Verifying a deploy

```bash
curl -s https://pmoney.hups.club/health
# {"status":"ok","backend_version":"6420c36","frontend_version":"6420c36","frontend_built_at":"..."}
```

`backend_version` and `frontend_version` are both git short SHAs — `backend_version`
from the checkout the running process started from, `frontend_version` from
`static/version.json` (written by `npm run build`, read fresh on every
request). They should always match after a full `deploy.sh --update` run.
If they diverge, the frontend build step failed or was skipped on the last
deploy — check `/var/log/pocketMoney-deploy.log` and rerun
`sudo ./deploy.sh --update`.

## Backups

The ledger is the family's money record — schedule a nightly `pg_dump` to
off-server storage before go-live. (TODO: add to `deploy.sh` provisioning.)
