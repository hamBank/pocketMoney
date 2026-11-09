#!/usr/bin/env bash
# pmoney-pull-backup.sh — runs on the BACKUP server. Pulls Pocket Money's nightly
# database dumps from the app server over rsync/ssh, checks they are sound and fresh,
# keeps a dated history of them, and prunes that history (fleet spec DEP-6: an off-box
# copy). Same design as recipeFlood's deploy/backup-server/.
#
# Pull, not push: the app server holds no credentials for the backup server, so
# compromising the app cannot reach the backups. The app server lets this key do one
# thing: read-only rsync of /var/backups/pmoney (see scripts/add_backup_reader.sh).
#
# What is pulled (the whole of the directory rrsync confines us to):
#   pmoney-<1-7>.sql.gz   the nightly pg_dump (02:30): users, chores, claims, the ledger.
# The app names them by weekday, so each one is overwritten a week later. This script
# therefore files every new one it sees under a dated name (from the file's mtime, UTC):
#   data/dumps/pmoney-YYYYMMDD-HHMMSS.sql.gz
# and keeps KEEP_DAYS of those.
# NOT pulled, and unreachable to the key: the app's .env (secrets). Keep a copy of it
# in your password manager (DEPLOYMENT.md, "Off-box backups").
#
# Fails (non-zero, so the systemd unit's Result shows it) if: the pull fails, a pulled
# file is not a sound backup, or the newest dump is older than MAX_AGE_HOURS (which
# means the app server's own backup job has stopped).
#
# Config: /etc/pmoney-pull-backup.conf (shell KEY=VALUE; override path with PM_PULL_CONF).
set -Eeuo pipefail
umask 077

CONF="${PM_PULL_CONF:-/etc/pmoney-pull-backup.conf}"
if [[ -r "$CONF" ]]; then set -a; source "$CONF"; set +a; fi

SRC_HOST="${SRC_HOST:-}"                          # user@host of the app server; empty = local path (tests)
SRC_ROOT="${SRC_ROOT:-/var/backups/pmoney}"       # used only when SRC_HOST is empty
DEST="${DEST:-${STATE_DIRECTORY:-/var/lib/pmoney-backup}/data}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
KNOWN_HOSTS="${KNOWN_HOSTS:-$HOME/.ssh/known_hosts}"
KEEP_DAYS="${KEEP_DAYS:-90}"                      # our history (the app keeps 7 days)
MIN_KEEP="${MIN_KEEP:-7}"                         # never prune below this many
MAX_AGE_HOURS="${MAX_AGE_HOURS:-30}"              # newest dump must be younger than this
RSYNC_TIMEOUT="${RSYNC_TIMEOUT:-120}"

log()  { echo "$(date '+%F %T') $*"; }
die()  { log "✗ $*" >&2; exit 1; }
trap 'log "✗ failed at line $LINENO: $BASH_COMMAND" >&2' ERR

command -v rsync >/dev/null || die "rsync is not installed"
[[ "$KEEP_DAYS" =~ ^[0-9]+$ && "$MIN_KEEP" =~ ^[0-9]+$ && "$MAX_AGE_HOURS" =~ ^[0-9]+$ ]] \
  || die "KEEP_DAYS, MIN_KEEP and MAX_AGE_HOURS must be whole numbers"

mkdir -p "$DEST/incoming" "$DEST/dumps" "$DEST/quarantine"
chmod 700 "$DEST"
exec 9>"$DEST/.lock"
flock -n 9 || die "another pull is already running"

if [[ -n "$SRC_HOST" ]]; then
  [[ -r "$SSH_KEY" ]]     || die "ssh key $SSH_KEY is missing or unreadable"
  [[ -r "$KNOWN_HOSTS" ]] || die "$KNOWN_HOSTS is missing: connect once by hand to accept the app server's host key"
  RSH="ssh -i $SSH_KEY -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN_HOSTS -o ConnectTimeout=20"
  # Tests only: a stand-in for ssh that runs the app server's forced command
  # (rrsync -ro) locally, so the pull meets the real confinement.
  RSH="${PM_PULL_TEST_RSH:-$RSH}"
  SRC="${SRC_HOST}:./"                            # rrsync resolves this to its root
else
  RSH="ssh"
  SRC="${SRC_ROOT}/"
fi

# ── pull ─────────────────────────────────────────────────────────────────────
# incoming/ mirrors the app's seven rotating dumps. --chmod: our copies are private
# whatever the source modes were. No --delete, ever: our history is ours. The *.tmp
# files the app writes before its atomic mv are never matched.
log "pulling ${SRC_HOST:-$SRC_ROOT}"
rc=0
rsync -a --partial --timeout="$RSYNC_TIMEOUT" -e "$RSH" \
      --chmod=Fu=rw,Fg=,Fo=,Du=rwx,Dg=,Do= \
      --include='pmoney-*.sql.gz' --exclude='*' \
      "$SRC" "$DEST/incoming/" || rc=$?
# 24 = a source file vanished mid-transfer: harmless.
if (( rc != 0 && rc != 24 )); then die "rsync of the backups failed (exit $rc)"; fi

# ── verify, then file each new dump under a dated name ───────────────────────
sound() {                                         # sound <file>: is this a complete pg_dump?
  local f="$1" tail
  gzip -t "$f" 2>/dev/null || return 1
  tail="$(gzip -dc "$f" | tail -c 400)" || return 1
  [[ "$tail" == *"PostgreSQL database dump complete"* ]]
}

bad=0; added=0
shopt -s nullglob
for f in "$DEST"/incoming/pmoney-*.sql.gz; do
  base="$(basename "$f")"
  target="$DEST/dumps/pmoney-$(date -u -r "$f" +%Y%m%d-%H%M%S).sql.gz"
  if [[ -e "$target" ]]; then
    cmp -s "$target" "$f" && continue             # filed (and verified) on an earlier run
    # Same timestamp, different content: never skip a file we have not verified.
    log "✗ $base differs from the copy already filed as $(basename "$target")"; bad=$((bad+1)); continue
  fi
  if ! sound "$f"; then
    # Moving it out of incoming/ makes the next run fetch it again.
    log "✗ not a complete backup: $base"; mv -f "$f" "$DEST/quarantine/$base"; bad=$((bad+1)); continue
  fi
  # A hard link to incoming/ costs no space; rsync replaces an incoming file by
  # writing a new one and renaming it, so this copy is never changed under us.
  ln "$f" "$target" 2>/dev/null || cp -p "$f" "$target"
  added=$((added+1))
done
(( bad == 0 )) || die "$bad pulled file(s) failed verification (moved to $DEST/quarantine)"

# ── freshness: has the app server's backup job kept running? ──────────────────
t="$(find "$DEST/incoming" -maxdepth 1 -name 'pmoney-*.sql.gz' -printf '%T@\n' | sort -nr | head -1)"
[[ -n "$t" ]] || die "no pmoney-*.sql.gz on the app server: its database backup has never run"
db_age=$(( ( $(date +%s) - ${t%%.*} ) / 3600 ))
(( db_age < MAX_AGE_HOURS )) || die "newest database dump is ${db_age}h old (limit ${MAX_AGE_HOURS}h): the app server's backup job may have stopped (pmoney-backup)"

# ── retention (only reached when everything above passed) ─────────────────────
# By the date in the name, not the mtime.
cutoff="$(date -u -d "-$KEEP_DAYS days" +%Y%m%d)"
total=0; old=()
for f in "$DEST"/dumps/pmoney-*.sql.gz; do
  total=$((total+1))
  stamp="${f##*/pmoney-}"; stamp="${stamp%%-*}"
  [[ "$stamp" < "$cutoff" ]] && old+=("$f")
done
if (( ${#old[@]} )); then
  if (( total - ${#old[@]} >= MIN_KEEP )); then
    rm -f -- "${old[@]}"; log "pruned ${#old[@]} dump(s) older than ${KEEP_DAYS} days"
  else
    log "kept ${#old[@]} old dump(s): pruning would leave fewer than $MIN_KEEP"
  fi
fi

date -u +%FT%TZ > "$DEST/last-success"
n_db=$(find "$DEST/dumps" -maxdepth 1 -name 'pmoney-*.sql.gz' | wc -l)
log "✓ ok: $n_db dump(s), newest ${db_age}h old; $added new; $(du -sh "$DEST" | cut -f1) total"
