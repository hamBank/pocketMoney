"""deploy/backup-server/pmoney-pull-backup.sh: the off-box copy (fleet spec DEP-6).

Ported from recipeFlood's tests for the same design. Runs the real script and a real
rsync against a local directory standing in for the app server's /var/backups/pmoney,
so the pull, the verification, the dated history, the freshness check and the
retention rules are exercised end to end. The remote-path tests go one step further:
a stand-in for ssh runs the app server's forced command, the real `rrsync -ro`, so the
pull meets the same confinement it will in production. Only ssh itself (the key, the
host key, sshd) is not covered here.
"""
import gzip
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "deploy" / "backup-server" / "pmoney-pull-backup.sh"
ADD_READER = ROOT / "scripts" / "add_backup_reader.sh"
HOUR = 3600
DAY = 86400

pytestmark = pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
needs_rrsync = pytest.mark.skipif(shutil.which("rrsync") is None, reason="rrsync not installed")


def _age(path: Path, seconds: float):
    t = time.time() - seconds
    os.utime(path, (t, t))


def _dump(path: Path, age=2 * HOUR, complete=True, raw: bytes | None = None):
    """A gzipped plain pg_dump, as pmoney-backup writes it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is None:
        tail = "\n--\n-- PostgreSQL database dump complete\n--\n" if complete else "\nCOPY claim (id"
        raw = gzip.compress(("-- PostgreSQL database dump\n" + "x" * 500 + tail).encode())
    path.write_bytes(raw)
    _age(path, age)
    return path


@pytest.fixture
def world(tmp_path):
    """The app server's backup dir, its app dir (with secrets), and an empty destination."""
    src = tmp_path / "var-backups-pmoney"
    src.mkdir()
    app = tmp_path / "opt-pocketMoney"
    app.mkdir()
    (app / ".env").write_text("JWT_SECRET=secret\nSMTP_PASSWORD=secret\n")
    return {"src": src, "app": app, "dest": tmp_path / "dest", "tmp": tmp_path}


def run(world, **env):
    base = {
        "PATH": os.environ["PATH"], "HOME": str(world["tmp"]),
        "PM_PULL_CONF": "/nonexistent", "SRC_ROOT": str(world["src"]), "SRC_HOST": "",
        "DEST": str(world["dest"]),
    }
    return subprocess.run(["bash", str(SCRIPT)], env={**base, **{k: str(v) for k, v in env.items()}},
                          capture_output=True, text=True, timeout=60)


def names(d: Path):
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def stamp(path: Path) -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime(path.stat().st_mtime))


# ── the pull and the dated history ────────────────────────────────────────────

def test_pulls_dumps_under_dated_names_and_leaves_the_source_alone(world):
    db = _dump(world["src"] / "pmoney-1.sql.gz")
    r = run(world)
    assert r.returncode == 0, r.stdout + r.stderr
    assert names(world["dest"] / "dumps") == [f"pmoney-{stamp(db)}.sql.gz"]
    assert db.exists()                                                  # source untouched
    assert (world["dest"] / "last-success").exists()
    assert "✓ ok: 1 dump(s)" in r.stdout


def test_a_weekday_file_overwritten_at_the_source_keeps_its_old_copy_here(world):
    # The app's names repeat weekly: Monday's dump replaces last Monday's. A plain
    # mirror would hold seven days; the dated history holds every one.
    _dump(world["src"] / "pmoney-1.sql.gz", age=7 * DAY + HOUR)
    run(world, MAX_AGE_HOURS=9999)
    _dump(world["src"] / "pmoney-1.sql.gz")                             # a week later
    r = run(world)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(names(world["dest"] / "dumps")) == 2


def test_a_second_run_with_nothing_new_adds_nothing(world):
    _dump(world["src"] / "pmoney-1.sql.gz")
    run(world)
    r = run(world)
    assert r.returncode == 0 and "0 new" in r.stdout
    assert len(names(world["dest"] / "dumps")) == 1


def test_only_dumps_are_pulled_never_temporaries_or_secrets(world):
    _dump(world["src"] / "pmoney-1.sql.gz")
    (world["src"] / "pmoney-2.sql.gz.tmp").write_bytes(b"half-written")
    (world["src"] / ".env").write_text("secret")
    (world["src"] / "notes.txt").write_text("x")
    assert run(world).returncode == 0
    assert names(world["dest"] / "incoming") == ["pmoney-1.sql.gz"]
    assert not list(world["dest"].rglob(".env")) and not list(world["dest"].rglob("*.tmp"))


def test_local_copies_are_private(world):
    _dump(world["src"] / "pmoney-1.sql.gz").chmod(0o644)
    run(world)
    for f in world["dest"].rglob("*.gz"):
        assert f.stat().st_mode & 0o077 == 0, f
    assert world["dest"].stat().st_mode & 0o077 == 0


def test_a_file_deleted_at_the_source_is_kept_here(world):
    db = _dump(world["src"] / "pmoney-1.sql.gz")
    run(world)
    _dump(world["src"] / "pmoney-2.sql.gz", age=HOUR)
    db.unlink()
    assert run(world).returncode == 0
    assert len(names(world["dest"] / "dumps")) == 2


# ── verification ──────────────────────────────────────────────────────────────

def test_a_truncated_dump_fails_the_run_and_is_quarantined_then_recovers(world):
    _dump(world["src"] / "pmoney-1.sql.gz")
    good = _dump(world["src"] / "pmoney-2.sql.gz", age=HOUR)
    bad = _dump(world["src"] / "pmoney-3.sql.gz", age=HOUR / 2, raw=good.read_bytes()[:20])
    r = run(world)
    assert r.returncode == 1 and "not a complete backup: pmoney-3.sql.gz" in r.stdout + r.stderr
    assert "pmoney-3.sql.gz" in names(world["dest"] / "quarantine")
    assert len(names(world["dest"] / "dumps")) == 2                     # the good ones were filed
    assert not (world["dest"] / "last-success").exists()
    # The source is fixed (e.g. the transfer had been cut off): the next run fetches it again.
    _dump(bad, age=HOUR / 4)
    r = run(world)
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(names(world["dest"] / "dumps")) == 3


def test_a_dump_without_the_completion_marker_is_rejected(world):
    _dump(world["src"] / "pmoney-1.sql.gz")
    _dump(world["src"] / "pmoney-2.sql.gz", age=HOUR, complete=False)
    r = run(world)
    assert r.returncode == 1 and "not a complete backup: pmoney-2.sql.gz" in r.stdout + r.stderr


def test_a_different_file_with_an_already_filed_timestamp_fails_instead_of_being_skipped(world):
    db = _dump(world["src"] / "pmoney-1.sql.gz")
    assert run(world).returncode == 0
    # Same mtime, different (and unverified) content: it must not pass as "already filed".
    t = db.stat().st_mtime
    db.write_bytes(b"garbage")
    os.utime(db, (t, t))
    r = run(world)
    assert r.returncode == 1 and "differs from the copy already filed" in r.stdout + r.stderr


# ── freshness ─────────────────────────────────────────────────────────────────

def test_a_stale_dump_fails_with_a_clear_reason(world):
    _dump(world["src"] / "pmoney-1.sql.gz", age=50 * HOUR)
    r = run(world)
    assert r.returncode == 1
    out = r.stdout + r.stderr
    assert "database dump is 50h old" in out and "pmoney-backup" in out
    assert not (world["dest"] / "last-success").exists()


def test_the_age_limit_is_configurable(world):
    _dump(world["src"] / "pmoney-1.sql.gz", age=50 * HOUR)
    assert run(world, MAX_AGE_HOURS=72).returncode == 0


def test_no_dump_at_all_fails(world):
    r = run(world)
    assert r.returncode == 1 and "database backup has never run" in r.stdout + r.stderr


def test_a_missing_source_directory_fails_instead_of_passing_silently(world):
    shutil.rmtree(world["src"])
    r = run(world)
    assert r.returncode == 1 and "rsync of the backups failed" in r.stdout + r.stderr


# ── our own retention ─────────────────────────────────────────────────────────

def _history(world, n, days_ago):
    """n filed dumps dated days_ago, days_ago+1, …"""
    d = world["dest"] / "dumps"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        day = time.strftime("%Y%m%d", time.gmtime(time.time() - (days_ago + i) * DAY))
        (d / f"pmoney-{day}-023000.sql.gz").write_bytes(b"old")


def test_old_history_is_pruned_but_never_below_the_minimum(world):
    _history(world, 10, days_ago=120)
    _dump(world["src"] / "pmoney-1.sql.gz")
    # 11 dumps, 10 older than KEEP_DAYS: pruning to 1 would leave fewer than MIN_KEEP.
    r = run(world, KEEP_DAYS=90, MIN_KEEP=7)
    assert r.returncode == 0 and "kept 10 old dump(s)" in r.stdout
    assert len(names(world["dest"] / "dumps")) == 11
    r = run(world, KEEP_DAYS=90, MIN_KEEP=1)
    assert "pruned 10 dump(s)" in r.stdout
    assert len(names(world["dest"] / "dumps")) == 1


def test_retention_goes_by_the_date_in_the_name_not_the_mtime(world):
    _history(world, 3, days_ago=10)
    for f in (world["dest"] / "dumps").iterdir():
        _age(f, 400 * DAY)
    _dump(world["src"] / "pmoney-1.sql.gz")
    run(world, KEEP_DAYS=90, MIN_KEEP=1)
    assert len(names(world["dest"] / "dumps")) == 4


def test_a_failed_run_prunes_nothing(world):
    _history(world, 10, days_ago=120)
    _dump(world["src"] / "pmoney-1.sql.gz", age=50 * HOUR)
    assert run(world, KEEP_DAYS=90, MIN_KEEP=1).returncode == 1
    assert len(names(world["dest"] / "dumps")) == 11


# ── through the app server's real forced command (rrsync -ro) ────────────────

def _fake_ssh(world, root: Path) -> Path:
    """Stands in for `ssh pmbackup@app <rsync --server …>` arriving at a key whose forced
    command is `rrsync -ro <root>`: sshd puts the client's command in
    SSH_ORIGINAL_COMMAND and runs the forced command instead."""
    p = world["tmp"] / "fake-ssh"
    p.write_text(
        "#!/bin/bash\n"
        'while [[ $# -gt 0 && "$1" != rsync ]]; do shift; done\n'
        'export SSH_ORIGINAL_COMMAND="$*"\n'
        f'exec rrsync -ro "{root}"\n')
    p.chmod(0o755)
    return p


def _remote(world, **env):
    key = world["tmp"] / "key"; key.write_text("k")
    hosts = world["tmp"] / "known_hosts"; hosts.write_text("")
    return run(world, SRC_HOST="pmbackup@app.example", SSH_KEY=key, KNOWN_HOSTS=hosts,
               PM_PULL_TEST_RSH=_fake_ssh(world, world["src"]), **env)


@needs_rrsync
def test_the_pull_works_through_rrsync_read_only(world):
    db = _dump(world["src"] / "pmoney-1.sql.gz")
    r = _remote(world)
    assert r.returncode == 0, r.stdout + r.stderr
    assert names(world["dest"] / "dumps") == [f"pmoney-{stamp(db)}.sql.gz"]


@needs_rrsync
def test_rrsync_confines_the_key_to_reading_the_backup_dir(world):
    _dump(world["src"] / "pmoney-1.sql.gz")
    ssh = _fake_ssh(world, world["src"])
    out = world["tmp"] / "out"; out.mkdir()

    def rsync(*args):
        return subprocess.run(["rsync", "-a", "-e", str(ssh), *args], capture_output=True, text=True, timeout=30)

    # A path outside the root (the app's .env) copies nothing.
    rsync(f"h:../{world['app'].name}/.env", f"{out}/")
    rsync("h:/etc/passwd", f"{out}/")
    assert not (out / ".env").exists() and not (out / "passwd").exists()
    # A push is refused, and nothing lands at the source.
    (out / "evil.sql.gz").write_text("x")
    r = rsync(f"{out}/evil.sql.gz", "h:./")
    assert r.returncode != 0 and not (world["src"] / "evil.sql.gz").exists()
    # A shell is refused: the forced command only runs rsync.
    r = subprocess.run([str(ssh), "h", "rsync;", "sh", "-c", "touch pwned"], capture_output=True,
                       text=True, timeout=30, cwd=world["tmp"])
    assert r.returncode != 0 and not (world["tmp"] / "pwned").exists()


def test_a_remote_pull_without_a_key_or_pinned_host_key_refuses_to_start(world):
    _dump(world["src"] / "pmoney-1.sql.gz")
    r = run(world, SRC_HOST="pmbackup@app.example", SSH_KEY=world["tmp"] / "nokey")
    assert r.returncode == 1 and "ssh key" in r.stdout + r.stderr
    key = world["tmp"] / "key"
    key.write_text("k")
    r = run(world, SRC_HOST="pmbackup@app.example", SSH_KEY=key, KNOWN_HOSTS=world["tmp"] / "nohosts")
    assert r.returncode == 1 and "accept the app server's host key" in r.stdout + r.stderr


def test_two_runs_at_once_do_not_overlap(world):
    _dump(world["src"] / "pmoney-1.sql.gz")
    world["dest"].mkdir()
    holder = subprocess.Popen(["bash", "-c", f"exec 9>{world['dest']}/.lock; flock 9; sleep 5"])
    time.sleep(0.5)
    try:
        r = run(world)
        assert r.returncode == 1 and "already running" in r.stdout + r.stderr
    finally:
        holder.kill()


# ── scripts/add_backup_reader.sh (the app-server side) ───────────────────────

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UVd1G1ZS+8YHvVE9KlUE2HQkvZ5G backup@vault"


def reader(*args, stdin=KEY):
    return subprocess.run(["bash", str(ADD_READER), "--print-line", *args, "-"], input=stdin,
                          capture_output=True, text=True, timeout=30)


def test_the_authorized_key_is_read_only_and_confined_to_the_backup_dir():
    r = reader("--from", "203.0.113.7")
    assert r.returncode == 0, r.stderr
    line = r.stdout.strip()
    assert line.startswith('restrict,from="203.0.113.7",command="')
    assert ' -ro /var/backups/pmoney"' in line
    assert "/opt/pocketMoney" not in line
    assert line.endswith("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UVd1G1ZS+8YHvVE9KlUE2HQkvZ5G pm-offsite-backup")
    assert "backup@vault" not in line                      # the caller's comment is replaced by our marker


def test_a_key_that_brings_its_own_options_is_refused():
    # An options prefix could smuggle in a different command=.
    r = reader(stdin='command="sh" ' + KEY)
    assert r.returncode == 1 and "not a bare ssh public key" in r.stderr


@pytest.mark.parametrize("value", ['1.2.3.4" ,command="sh', "1.2.3.4 5.6.7.8", "$(id)"])
def test_from_cannot_be_used_to_inject_options(value):
    r = reader("--from", value)
    assert r.returncode == 1 and "unexpected characters" in r.stderr


@pytest.mark.parametrize("flag", ["--backup-dir", "--app-dir"])
def test_the_directories_must_be_plain_paths(flag):
    r = reader(flag, '/var/x" -rw /')
    assert r.returncode == 1 and "plain absolute path" in r.stderr


# ── the files install.sh installs exist and agree with each other ────────────

def test_the_installer_and_units_agree():
    d = SCRIPT.parent
    installer = (d / "install.sh").read_text()
    for name in ("pmoney-pull-backup.sh", "pmoney-pull-backup.service",
                 "pmoney-pull-backup.timer", "pmoney-pull-backup.conf.example"):
        assert (d / name).exists() and name in installer
    service = (d / "pmoney-pull-backup.service").read_text()
    assert "ExecStart=/usr/local/sbin/pmoney-pull-backup.sh" in service
    assert "Type=oneshot" in service and "User=pmpull" in service
    assert "StateDirectory=pmoney-backup" in service and "/var/lib/pmoney-backup" in installer
    # The destination is opened in the sandbox and tied to its disk, at the same path.
    dest = [l.split("=", 2)[2] for l in service.splitlines() if l.startswith("Environment=DEST=")]
    assert dest == ["/lklBackup/sites_apps/pocketMoney"]
    assert f"ReadWritePaths={dest[0]}" in service.splitlines()
    assert f"RequiresMountsFor={dest[0]}" in service.splitlines()
    assert "Environment=DEST=" in installer                  # install.sh reads it from the unit
    timer = (d / "pmoney-pull-backup.timer").read_text()
    assert "Persistent=true" in timer and "OnCalendar=" in timer
    for script in (SCRIPT, d / "install.sh", ADD_READER):
        assert subprocess.run(["bash", "-n", str(script)]).returncode == 0


def test_the_app_side_dump_is_written_atomically():
    # A half-written dump must never replace the last good one, or be pulled.
    unit = (ROOT / "deploy" / "pmoney-backup.service").read_text()
    exec_line = next(l for l in unit.splitlines() if l.startswith("ExecStart="))
    assert "-o pipefail" in exec_line and '.tmp"' in exec_line and "mv " in exec_line
    assert "$$(date +%%u)" in exec_line                      # systemd's escapes for $ and %
