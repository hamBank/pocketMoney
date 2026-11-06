"""scripts/check_config.py, the deploy preflight (fleet spec CFG-2, STK-6)."""
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_config.py"
GOOD_SECRET = "a" * 64


def run(tmp_path, env_text):
    env_file = tmp_path / ".env"
    env_file.write_text(env_text)
    # A clean environment, like the deploy's: conftest's test settings must not leak in.
    env = {"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(env_file)],
        capture_output=True, text=True, env=env, timeout=60,
    )


def test_good_config_passes(tmp_path):
    result = run(tmp_path, f'AUTH_ENABLED=true\nJWT_SECRET="{GOOD_SECRET}"\n'
                           "DATABASE_URL=postgresql+psycopg://u@/db?host=/nonexistent\n")
    assert result.returncode == 0, result.stderr
    assert "configuration OK" in result.stdout


def test_default_secret_fails_without_printing_any_values(tmp_path):
    result = run(tmp_path, "AUTH_ENABLED=true\nJWT_SECRET=dev-secret-change-me\n"
                           'SMTP_PASSWORD="hunter2 app password"\n')
    assert result.returncode == 1
    assert "JWT_SECRET" in result.stderr
    # The deploy log gets this output: no value from .env may appear in it.
    assert "hunter2" not in result.stderr + result.stdout
    assert "dev-secret-change-me" not in result.stderr + result.stdout


def test_url_naming_a_missing_driver_fails(tmp_path):
    # The +psycopg2 left in .env after the driver change, once a fresh venv lacks it.
    result = run(tmp_path, f'AUTH_ENABLED=true\nJWT_SECRET="{GOOD_SECRET}"\n'
                           "DATABASE_URL=postgresql+nosuchdriver://u@/db\n")
    assert result.returncode == 1
    assert "database driver cannot be loaded" in result.stderr
