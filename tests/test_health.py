import json

from fastapi.testclient import TestClient

import backend.version as version_module
from backend.main import app


def test_health_reports_ok_and_backend_version():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # This repo checkout always has .git, so it's a real short SHA, not "unknown".
    assert body["backend_version"]
    assert body["backend_version"] != "unknown"


def test_frontend_version_is_null_when_never_built(client, monkeypatch, tmp_path):
    monkeypatch.setattr(version_module, "VERSION_FILE", tmp_path / "version.json")
    response = client.get("/health")
    body = response.json()
    assert body["frontend_version"] is None
    assert body["frontend_built_at"] is None


def test_frontend_version_reflects_static_version_file(client, monkeypatch, tmp_path):
    version_file = tmp_path / "version.json"
    version_file.write_text(
        json.dumps({"version": "abc1234", "built_at": "2026-01-01T00:00:00Z"})
    )
    monkeypatch.setattr(version_module, "VERSION_FILE", version_file)
    response = client.get("/health")
    body = response.json()
    assert body["frontend_version"] == "abc1234"
    assert body["frontend_built_at"] == "2026-01-01T00:00:00Z"


def test_frontend_version_survives_corrupt_file(client, monkeypatch, tmp_path):
    version_file = tmp_path / "version.json"
    version_file.write_text("not json")
    monkeypatch.setattr(version_module, "VERSION_FILE", version_file)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["frontend_version"] is None
