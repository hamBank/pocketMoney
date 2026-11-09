#!/usr/bin/env bash
# Pocket Money provisioning + deploy. Idempotent — safe to re-run.
#
#   sudo ./deploy.sh            # full provision (packages, user, db, units, vhost)
#   sudo ./deploy.sh --update   # code update only (used by the webhook path unit)
#
# The repo is public (since 2026-11-09, for auto-merge) but still cloned over
# SSH with a read-only deploy key, so nothing changes if it goes private again:
#   sudo -u pocketMoney ssh-keygen -t ed25519 -N "" -f /home/pocketMoney/.ssh/id_ed25519
# and add the .pub as a Deploy Key (no write access) on the GitHub repo
# BEFORE the first run.
#
# After first provision:
#   1. Fill in /opt/pocketMoney/.env  (see .env.example)
#   2. certbot --apache -d pmoney.hups.club
#   3. Add the GitHub webhook: POST https://pmoney.hups.club/deploy,
#      content type application/json, secret = DEPLOY_SECRET, push events.
set -Eeuo pipefail

APP_DIR=/opt/pocketMoney
REPO_URL=git@github.com:hamBank/pocketMoney.git
APP_USER=pocketMoney
SERVICE=pmoney
LOG=/var/log/pocketMoney-deploy.log

log() { echo "[$(date -Is)] $*" | tee -a "$LOG"; }
# Fleet spec DEP-1: log where a failure happened. -E makes the trap fire inside
# update_code/provision too.
trap 'rc=$?; log "ERROR: ${BASH_SOURCE[0]}:${LINENO}: \`${BASH_COMMAND}\` exited $rc"; exit $rc' ERR

# Scheduled jobs (fleet spec DEP-5): deploy/pmoney-<job>.{service,timer}.
TIMERS=(pmoney-digest pmoney-allowance pmoney-sheet-sync pmoney-backup)

update_code() {
    log "updating code"
    cd "$APP_DIR"
    sudo -u "$APP_USER" git fetch origin main
    sudo -u "$APP_USER" git reset --hard origin/main

    log "python deps + migrations"
    sudo -u "$APP_USER" .venv/bin/pip install -q -r requirements.txt
    chmod +x deploy.sh scripts/*.sh scripts/*.py  # DEP-7: git may not carry +x

    # Fleet spec CFG-2: the new code refuses some configs (e.g. the default
    # JWT_SECRET). Find out now, while the old process is still serving.
    log "config check"
    sudo -u "$APP_USER" env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/check_config.py .env ||
        { log "config check FAILED - leaving the running service untouched"; exit 1; }
    sudo -u "$APP_USER" bash -c "set -a && source .env 2>/dev/null; .venv/bin/alembic upgrade head"

    log "frontend build"
    (cd frontend && sudo -u "$APP_USER" npm ci --silent && sudo -u "$APP_USER" npm run build)

    log "restarting $SERVICE"
    systemctl restart "$SERVICE"

    # Fleet spec DEP-4: a deploy must not fail semi-silently. Non-zero exit
    # marks pmoney-deploy.service failed.
    log "smoke check"
    # As the app user: git refuses a repo owned by someone else ("dubious
    # ownership") when run as root, which would silently skip the SHA checks.
    DEPLOYED_SHA=$(sudo -u "$APP_USER" git rev-parse --short HEAD)
    # SMOKE_CRON_PATTERN: the jobs the old system cron file ran, now timers.
    # A leftover cron line would run one a second time (fleetSpec lesson 20).
    if SMOKE_UNIT_PREFIX=pmoney SMOKE_BACKUP_GLOB='/var/backups/pmoney/*.sql.gz' \
        SMOKE_APP_USER="$APP_USER" \
        SMOKE_CRON_PATTERN='send_admin_digest\.py|apply_weekly_allowance\.py|sync_sheet\.py|pg_dump pmoney' \
        bash scripts/smoke_check.sh "http://127.0.0.1:8001" "$DEPLOYED_SHA" 2>&1 | tee -a "$LOG"; then
        log "update done"
    else
        log "update done, BUT the smoke check FAILED"
        exit 1
    fi
}

provision() {
    log "=== full provision ==="

    log "packages"
    apt-get update -q
    apt-get install -qy python3-venv python3-pip git nodejs npm rsync \
        postgresql apache2 curl

    log "system user + app dir"
    id -u "$APP_USER" &>/dev/null || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"
    mkdir -p "$APP_DIR" /var/backups/pmoney
    chown "$APP_USER":"$APP_USER" "$APP_DIR"
    chown postgres:postgres /var/backups/pmoney
    touch "$LOG" && chown "$APP_USER" "$LOG"

    log "github ssh access (deploy key)"
    APP_HOME=$(getent passwd "$APP_USER" | cut -d: -f6)
    sudo -u "$APP_USER" mkdir -p "$APP_HOME/.ssh"
    if [ ! -f "$APP_HOME/.ssh/id_ed25519" ]; then
        log "ERROR: no deploy key at $APP_HOME/.ssh/id_ed25519 — see header of deploy.sh"
        exit 1
    fi
    if ! sudo -u "$APP_USER" grep -qs "^github.com" "$APP_HOME/.ssh/known_hosts"; then
        ssh-keyscan -t ed25519,rsa github.com 2>/dev/null |
            sudo -u "$APP_USER" tee -a "$APP_HOME/.ssh/known_hosts" >/dev/null
    fi

    log "clone/update repo"
    if [ ! -d "$APP_DIR/.git" ]; then
        sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
    fi
    # Older checkouts may still have the HTTPS remote — converge on SSH.
    sudo -u "$APP_USER" git -C "$APP_DIR" remote set-url origin "$REPO_URL"

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
    # Never from --update: daemon-reload inside the running deploy unit loops
    # (fleetSpec guides, lesson 7). New units go in from a full provision.
    for unit in "${TIMERS[@]}"; do
        cp "$APP_DIR"/deploy/"$unit".service "$APP_DIR"/deploy/"$unit".timer /etc/systemd/system/
    done
    systemctl daemon-reload
    systemctl enable "$SERVICE" pmoney-deploy.path

    log "apache vhost"
    a2enmod -q proxy proxy_http
    # Fleet spec DEP-8: `certbot --apache` edits the installed vhost (adds the
    # HTTP->HTTPS redirect) and writes $VHOST-le-ssl.conf beside it. Install the
    # repo copy only on a fresh box or when the installed one is still identical
    # to it; never copy over certbot's (or a hand) edit.
    VHOST=pmoney.hups.club
    VHOST_SRC="$APP_DIR/deploy/$VHOST.conf"
    VHOST_DST="/etc/apache2/sites-available/$VHOST.conf"
    if [ -e "/etc/apache2/sites-available/$VHOST-le-ssl.conf" ]; then
        log "vhost: certbot owns $VHOST_DST ($VHOST-le-ssl.conf exists) - left alone"
    elif [ -e "$VHOST_DST" ] && ! cmp -s "$VHOST_SRC" "$VHOST_DST"; then
        log "vhost: $VHOST_DST differs from the repo copy - left alone; merge by hand"
    else
        cp "$VHOST_SRC" "$VHOST_DST"
    fi
    a2ensite -q "$VHOST"
    # Never reload onto a broken config: a failed test trips the ERR trap,
    # which logs it and aborts with Apache still serving the old config.
    apachectl configtest 2>&1 | tee -a "$LOG"
    systemctl reload apache2

    update_code

    # After update_code, so the jobs never run before the venv and the new
    # code are in place.
    log "scheduled jobs (systemd timers)"
    for unit in "${TIMERS[@]}"; do
        systemctl enable --now "$unit".timer
    done
    systemctl start pmoney-deploy.path
    log "=== provision done — see header of deploy.sh for the remaining manual steps ==="
}

if [ "${1:-}" = "--update" ]; then
    update_code
else
    provision
fi
