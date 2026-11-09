"""The SPA catch-all serves the built frontend and nothing outside it."""
import pytest
from fastapi.testclient import TestClient

import backend.main as main

SHELL = "<html>SPA SHELL</html>"
SECRET = "SECRET-OUTSIDE-THE-STATIC-DIR"


@pytest.fixture
def spa(tmp_path, monkeypatch):
    static = tmp_path / "backend" / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(SHELL)
    (static / "assets" / "app.js").write_text("console.log('app')")
    # Siblings and ancestors of the static dir, as .env is in a real checkout.
    (tmp_path / ".env").write_text(SECRET)
    (tmp_path / "backend" / "secret.txt").write_text(SECRET)
    monkeypatch.setattr(main, "STATIC_DIR", static)
    return TestClient(main.create_app())


def test_serves_the_shell_and_assets(spa):
    assert spa.get("/").text == SHELL
    assert spa.get("/assets/app.js").text == "console.log('app')"


def test_unknown_paths_fall_back_to_the_shell(spa):
    assert spa.get("/chores/42/anything").text == SHELL


@pytest.mark.parametrize(
    "path",
    [
        "/../../.env",
        "/../secret.txt",
        "/%2e%2e/%2e%2e/.env",
        "/%2e%2e/secret.txt",
        "/..%2f..%2f.env",
        "/..%2fsecret.txt",
        "/assets/../../secret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/%2e%2e%2f%2e%2e%2f.env",
        "/..%5c..%5c.env",
        "/%00/../../.env",
    ],
)
def test_never_serves_files_outside_the_static_dir(spa, path):
    response = spa.get(path)
    assert SECRET not in response.text
    # Whatever it answers, it is the shell or an error, never the other file.
    assert response.status_code in (200, 400, 404, 422)
    if response.status_code == 200:
        assert response.text == SHELL
