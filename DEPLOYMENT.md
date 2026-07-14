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

## Backups

The ledger is the family's money record — schedule a nightly `pg_dump` to
off-server storage before go-live. (TODO: add to `deploy.sh` provisioning.)
