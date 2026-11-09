"""scripts/install-hooks.sh and the pre-push checks (fleet spec TST-3), run for real
in a throwaway git repo."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = ("install-hooks.sh", "pre-push-checks.sh")
ZERO = "0" * 40

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def run(cmd, cwd, **kwargs):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, **kwargs)


@pytest.fixture
def repo(tmp_path):
    """A fresh git repo holding copies of the two scripts."""
    run(["git", "init", "-q"], tmp_path)
    (tmp_path / "scripts").mkdir()
    for name in SCRIPTS:
        dest = tmp_path / "scripts" / name
        shutil.copy(REPO / "scripts" / name, dest)
        dest.chmod(0o755)
    return tmp_path


def hook(repo):
    return repo / ".git" / "hooks" / "pre-push"


def test_scripts_are_executable_in_the_repo():
    for name in SCRIPTS:
        assert os.access(REPO / "scripts" / name, os.X_OK), f"scripts/{name} lost +x"


def test_install_creates_an_executable_hook(repo):
    result = run(["bash", "scripts/install-hooks.sh"], repo)
    assert result.returncode == 0, result.stderr
    assert os.access(hook(repo), os.X_OK)
    assert "scripts/pre-push-checks.sh" in hook(repo).read_text()


def test_install_is_idempotent(repo):
    run(["bash", "scripts/install-hooks.sh"], repo)
    first = hook(repo).read_text()
    assert run(["bash", "scripts/install-hooks.sh"], repo).returncode == 0
    assert hook(repo).read_text() == first


def test_install_refuses_to_replace_someone_elses_hook(repo):
    hook(repo).parent.mkdir(parents=True, exist_ok=True)
    hook(repo).write_text("#!/bin/sh\necho mine\n")
    result = run(["bash", "scripts/install-hooks.sh"], repo)
    assert result.returncode == 1
    assert "--force" in result.stderr
    assert "echo mine" in hook(repo).read_text()


def test_force_replaces_it(repo):
    hook(repo).parent.mkdir(parents=True, exist_ok=True)
    hook(repo).write_text("#!/bin/sh\necho mine\n")
    assert run(["bash", "scripts/install-hooks.sh", "--force"], repo).returncode == 0
    assert "pre-push-checks.sh" in hook(repo).read_text()


def test_installed_hook_blocks_the_push_when_the_checks_fail(repo):
    run(["bash", "scripts/install-hooks.sh"], repo)
    (repo / "scripts" / "pre-push-checks.sh").write_text("#!/usr/bin/env bash\nexit 3\n")
    assert run([str(hook(repo))], repo, input="").returncode == 3


def test_installed_hook_lets_the_push_through_when_they_pass(repo):
    run(["bash", "scripts/install-hooks.sh"], repo)
    (repo / "scripts" / "pre-push-checks.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    assert run([str(hook(repo))], repo, input="").returncode == 0


SKIP_HEAVY = {"PREPUSH_SKIP": "pytest frontend"}


def checks(repo, stdin="", **env):
    return run(
        ["bash", "scripts/pre-push-checks.sh"],
        repo,
        input=stdin,
        env={**os.environ, **env},
    )


def test_checks_catch_a_syntax_error(repo):
    (repo / "deploy.sh").write_text("if then\n")
    result = checks(repo, **SKIP_HEAVY)
    assert result.returncode == 1
    assert "FAILED: syntax" in result.stdout


def test_checks_pass_on_clean_scripts(repo):
    (repo / "deploy.sh").write_text("#!/usr/bin/env bash\necho ok\n")
    result = checks(repo, **SKIP_HEAVY)
    assert result.returncode == 0, result.stdout
    assert "pre-push: ok" in result.stdout


def test_a_push_that_only_deletes_refs_is_not_checked(repo):
    (repo / "deploy.sh").write_text("if then\n")  # would fail if it were checked
    line = f"(delete) {ZERO} refs/heads/old {'a' * 40}\n"
    assert checks(repo, stdin=line, **SKIP_HEAVY).returncode == 0


def test_a_real_push_is_checked_even_with_other_deletes(repo):
    (repo / "deploy.sh").write_text("if then\n")
    stdin = f"refs/heads/x {'b' * 40} refs/heads/x {ZERO}\n(delete) {ZERO} refs/heads/old {'a' * 40}\n"
    assert checks(repo, stdin=stdin, **SKIP_HEAVY).returncode == 1


def test_skip_prepush_env_bypasses_everything(repo):
    (repo / "deploy.sh").write_text("if then\n")
    assert checks(repo, SKIP_PREPUSH="1").returncode == 0
