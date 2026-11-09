"""deploy.sh's trigger handling and lock (fleet spec DEP-3), run for real: the
functions are sourced from deploy.sh and use a real flock on temp files."""
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DEPLOY_SH = REPO / "deploy.sh"

pytestmark = pytest.mark.skipif(shutil.which("flock") is None, reason="flock not installed")


@pytest.fixture
def paths(tmp_path):
    return {
        "log": tmp_path / "deploy.log",
        "lock": tmp_path / "deploy.lock",
        "trigger": tmp_path / ".deploy-trigger",
    }


def run_deploy_functions(script, paths, wait="5"):
    """Source deploy.sh (its dispatch is skipped when sourced) and run `script`."""
    env = {
        **os.environ,
        "DEPLOY_LOG": str(paths["log"]),
        "DEPLOY_LOCK_FILE": str(paths["lock"]),
        "DEPLOY_TRIGGER_FILE": str(paths["trigger"]),
        "DEPLOY_LOCK_WAIT": wait,
    }
    return subprocess.run(
        ["bash", "-c", f"source {DEPLOY_SH}; {script}"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def log_text(paths):
    return paths["log"].read_text() if paths["log"].exists() else ""


def hold_lock(paths, seconds):
    """Another process holding the deploy lock for `seconds`."""
    holder = subprocess.Popen(
        ["bash", "-c", f'exec 9>"{paths["lock"]}"; flock 9; echo held; sleep {seconds}'],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert holder.stdout.readline().strip() == "held"  # lock is really taken
    return holder


def test_consume_trigger_deletes_the_file(paths):
    paths["trigger"].write_text("")
    result = run_deploy_functions("consume_trigger", paths)
    assert result.returncode == 0, result.stderr
    assert not paths["trigger"].exists()
    assert "consumed" in log_text(paths)


def test_consume_trigger_with_no_file_does_nothing(paths):
    result = run_deploy_functions("consume_trigger", paths)
    assert result.returncode == 0, result.stderr
    assert "consumed" not in log_text(paths)


def test_a_free_lock_is_taken_at_once(paths):
    result = run_deploy_functions("acquire_deploy_lock; echo got", paths)
    assert result.returncode == 0, result.stderr
    assert "got" in result.stdout
    assert "waiting" not in log_text(paths)


def test_a_second_deploy_waits_for_the_first_and_then_runs(paths):
    holder = hold_lock(paths, seconds=2)
    try:
        start = time.monotonic()
        result = run_deploy_functions("acquire_deploy_lock; echo got", paths, wait="20")
        waited = time.monotonic() - start
    finally:
        holder.wait(timeout=10)
    assert result.returncode == 0, result.stderr
    assert "got" in result.stdout
    assert waited >= 1, "it did not wait for the lock"
    assert "waiting" in log_text(paths) and "lock acquired" in log_text(paths)


def test_it_gives_up_loudly_if_the_lock_never_frees(paths):
    holder = hold_lock(paths, seconds=30)
    try:
        result = run_deploy_functions("acquire_deploy_lock; echo got", paths, wait="1")
    finally:
        holder.kill()
        holder.wait()
    assert result.returncode == 1
    assert "got" not in result.stdout
    assert "giving up" in log_text(paths)


def test_update_consumes_the_trigger_first_and_holds_the_lock_while_it_runs(paths):
    paths["trigger"].write_text("")
    script = """
        update_code() {
            [ -e "$TRIGGER_FILE" ] && echo STEP:trigger-still-there || echo STEP:trigger-gone
            ( flock -n 8 ) 8>"$LOCK_FILE" && echo STEP:lock-free || echo STEP:lock-held
            echo STEP:updated
        }
        run_update
    """
    result = run_deploy_functions(script, paths)
    assert result.returncode == 0, result.stderr
    steps = [line for line in result.stdout.splitlines() if line.startswith("STEP:")]
    assert steps == ["STEP:trigger-gone", "STEP:lock-held", "STEP:updated"]


def test_a_failed_update_does_not_leave_the_trigger_to_refire(paths):
    """The reason DEP-3 exists: with the path unit firing while the file exists,
    a deploy that fails must already have deleted it."""
    paths["trigger"].write_text("")
    result = run_deploy_functions("update_code() { return 1; }; run_update", paths)
    assert result.returncode == 1
    assert not paths["trigger"].exists()
    assert "ERROR" in log_text(paths)


def test_the_path_unit_fires_while_the_trigger_exists():
    """PathChanged only fires on a change, so a push during a deploy was missed;
    the delete-at-start in deploy.sh is only safe with PathExists."""
    unit = (REPO / "deploy" / "pmoney-deploy.path").read_text()
    directives = [line.strip() for line in unit.splitlines() if not line.lstrip().startswith("#")]
    assert any(re.fullmatch(r"PathExists=\S*\.deploy-trigger", line) for line in directives)
    assert not any(line.startswith("PathChanged=") for line in directives)


def test_provision_clears_the_trigger_and_restarts_the_path_unit():
    text = DEPLOY_SH.read_text()
    assert 'rm -f "$TRIGGER_FILE"' in text
    assert "systemctl try-restart pmoney-deploy.path" in text
    # Creating the file at provision would start a pointless deploy under PathExists.
    assert not re.search(r"touch .*deploy-trigger", text)
