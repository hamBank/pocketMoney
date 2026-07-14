#!/usr/bin/env bash
# Pocket Money provisioning + deploy. Idempotent — safe to re-run.
#
#   sudo ./deploy.sh            # full provision (packages, user, db, units, vhost)
#   sudo ./deploy.sh --update   # code update only (used by the webhook path unit)
#
# After first provision:
#   1. Fill in /opt/pocketMoney/.env  (see .env.example)
#   2. certbot --apache -d pmoney.hups.club
#   3. Add the GitHub webhook: POST https://pmoney.hups.club/deploy,
#      content type application/json, secret = DEPLOY_SECRET, push events.
set -euo pipefail

APP_DIR=/opt/pocketMoney
REPO_URL=https://github.com/hamBank/pocketMoney.git
APP_USER=pocketMoney
SERVICE=pmoney
LOG=/var/log/pocketMoney-deploy.log

log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }

update_code() {
    log "updating code"
    cd "$APP_DIR"
    sudo -u "$APP_USER" git fetch origin main
    sudo -u "$APP_USER" git reset --hard origin/main

    log "python deps + migrations"
    sudo -u "$APP_USER" .venv/bin/pip install -q -r requirements.txt
    sudo -u "$APP_USER" bash -c "set -a && source .env 2>/dev/null; .venv/bin/alembic upgrade head"

    log "frontend build"
    (cd frontend && sudo -u "$APP_USER" npm ci --silent && sudo -u "$APP_USER" npm run build)

    log "restarting $SERVICE"
    systemctl restart "$SERVICE"
    log "update done"
}

provision() {
    log "=== full provision ==="

    log "packages"
    apt-get update -q
    apt-get install -qy python3-venv python3-pip git nodejs npm \
        postgresql apache2 curl

    log "system user + app dir"
    id -u "$APP_USER" &>/dev/null || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
    mkdir -p "$APP_DIR" /var/backups/pmoney
    chown "$APP_USER":"$APP_USER" "$APP_DIR"
    chown postgres:postgres /var/backups/pmoney
    touch "$LOG" && chown "$APP_USER" "$LOG"

    log "clone/update repo"
    if [ ! -d "$APP_DIR/.git" ]; then
        sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
    fi

    log "venv"
    [ -d "$APP_DIR/.venv" ] || sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"

    log "postgres role + database"
    sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$APP_USER'" | grep -q 1 ||
        sudo -u postgres psql -c "CREATE ROLE \"$APP_USER\" LOGIN"
    sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='pmoney'" | grep -q 1 ||
        sudo -u postgres createdb -O "$APP_USER" pmoney

    log "env file"
    if [ ! -f "$APP_DIR/.env" ]; then
        sudo -u "$APP_USER" cp "$APP_DIR/.env.example" "$APP_DIR/.env"
        chmod 600 "$APP_DIR/.env"
        log "NOTE: fill in $APP_DIR/.env before the app will fully work"
    fi

    log "deploy trigger + systemd units"
    sudo -u "$APP_USER" touch "$APP_DIR/.deploy-trigger"
    cp "$APP_DIR"/deploy/pmoney.service /etc/systemd/system/"$SERVICE".service
    cp "$APP_DIR"/deploy/pmoney-deploy.service /etc/systemd/system/pmoney-deploy.service
    cp "$APP_DIR"/deploy/pmoney-deploy.path /etc/systemd/system/pmoney-deploy.path
    systemctl daemon-reload
    systemctl enable "$SERVICE" pmoney-deploy.path

    log "apache vhost"
    a2enmod -q proxy proxy_http
    cp "$APP_DIR"/deploy/pmoney.hups.club.conf /etc/apache2/sites-available/
    a2ensite -q pmoney.hups.club
    systemctl reload apache2

    log "cron jobs"
    cp "$APP_DIR"/deploy/pocketmoney.cron /etc/cron.d/pocketmoney
    chmod 644 /etc/cron.d/pocketmoney

    update_code
    systemctl start pmoney-deploy.path
    log "=== provision done — see header of deploy.sh for the remaining manual steps ==="
}

if [ "${1:-}" = "--update" ]; then
    update_code
else
    provision
fi
