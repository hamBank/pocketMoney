#!/usr/bin/env bash
# install.sh — run as root on the BACKUP server (idempotent). Installs the pull script,
# its systemd service + timer, a config template and a dedicated key, and enables the
# timer. It does not start a pull: finish the steps it prints first.
set -Eeuo pipefail
cd "$(dirname "$0")"
[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
for c in rsync ssh ssh-keygen flock systemctl gzip cmp; do command -v "$c" >/dev/null || { echo "✗ missing: $c" >&2; exit 1; }; done

STATE=/var/lib/pmoney-backup
if ! id pmpull >/dev/null 2>&1; then
  useradd --system --home-dir "$STATE" --create-home --shell /usr/sbin/nologin pmpull
  echo "✓ created user pmpull"
fi
usermod -p '*' pmpull 2>/dev/null || true
install -d -m 700 -o pmpull -g pmpull "$STATE" "$STATE/.ssh"

# Where the copies go: the unit's Environment=DEST= line, the one place it is set.
DEST="$(sed -n 's/^Environment=DEST=//p' pmoney-pull-backup.service)"
[[ -n "$DEST" ]] || { echo "✗ no Environment=DEST= in pmoney-pull-backup.service" >&2; exit 1; }
# The parent must already exist: creating it here would put the backups on the root
# filesystem if the backup disk isn't mounted.
[[ -d "$(dirname "$DEST")" ]] || { echo "✗ $(dirname "$DEST") does not exist: is the backup disk mounted?" >&2; exit 1; }
install -d -m 700 -o pmpull -g pmpull "$DEST"
runuser -u pmpull -- test -w "$DEST" || { echo "✗ pmpull cannot write $DEST: a parent directory blocks it (it needs o+x on each)" >&2; exit 1; }
echo "✓ backups go to $DEST"

install -m 755 pmoney-pull-backup.sh /usr/local/sbin/pmoney-pull-backup.sh
install -m 644 pmoney-pull-backup.service /etc/systemd/system/pmoney-pull-backup.service
install -m 644 pmoney-pull-backup.timer   /etc/systemd/system/pmoney-pull-backup.timer
if [[ ! -e /etc/pmoney-pull-backup.conf ]]; then
  install -m 640 -o root -g pmpull pmoney-pull-backup.conf.example /etc/pmoney-pull-backup.conf
  echo "✓ wrote /etc/pmoney-pull-backup.conf: check SRC_HOST"
fi

KEY="$STATE/.ssh/id_ed25519"
if [[ ! -e "$KEY" ]]; then
  runuser -u pmpull -- ssh-keygen -q -t ed25519 -N '' -C "pm-pull@$(hostname)" -f "$KEY"
  echo "✓ generated $KEY"
fi
touch "$STATE/.ssh/known_hosts"; chown pmpull:pmpull "$STATE/.ssh/known_hosts"

systemctl daemon-reload
systemctl enable pmoney-pull-backup.timer >/dev/null
systemctl start pmoney-pull-backup.timer

cat <<MSG

Installed. Remaining steps:

 1. On the APP server, authorise this key (read-only rsync of /var/backups/pmoney, nothing else):
        echo '$(cat "$KEY.pub")' | sudo scripts/add_backup_reader.sh --from <this server's IP> -

 2. Check SRC_HOST in /etc/pmoney-pull-backup.conf (pmbackup@<app host>).

 3. Pin the app server's host key: check its fingerprint on the app server
    (ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub) then here:
        sudo -u pmpull ssh-keyscan -t ed25519 <host> | sudo -u pmpull tee -a $STATE/.ssh/known_hosts
        sudo -u pmpull ssh-keygen -lf $STATE/.ssh/known_hosts      # compare with the fingerprint

 4. Run one pull and read the result:
        sudo systemctl start pmoney-pull-backup.service
        journalctl -u pmoney-pull-backup.service -n 20
    Then see the next scheduled run with: systemctl list-timers pmoney-pull-backup.timer
MSG
