import json

from fastapi.testclient import TestClient

import backend.version as version_module
from backend.main import app

CONTRACT = {"status", "backend_sha", "frontend_sha", "build_sha", "built_at", "started_at"}


def test_health_reports_the_fleet_contract():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTRACT
    assert body["status"] == "ok"
    # This repo checkout always has .git, so it's a real short SHA, not "unknown".
    assert body["backend_sha"]
    assert body["backend_sha"] != "unknown"
    assert body["started_at"]


def test_frontend_fields_are_null_when_never_built(client, monkeypatch, tmp_path):
    monkeypatch.setattr(version_module, "VERSION_FILE", tmp_path / "version.json")
    body = client.get("/health").json()
    assert body["build_sha"] is None
    assert body["frontend_sha"] is None
    assert body["built_at"] is None


def test_frontend_fields_reflect_static_version_file(client, monkeypatch, tmp_path):
    version_file = tmp_path / "version.json"
    version_file.write_text(
        json.dumps(
            {"build_sha": "abc1234", "frontend_sha": "9f8e7d6", "built_at": "2026-01-01T00:00:00Z"}
        )
    )
    monkeypatch.setattr(version_module, "VERSION_FILE", version_file)
    body = client.get("/health").json()
    assert body["build_sha"] == "abc1234"
    assert body["frontend_sha"] == "9f8e7d6"
    assert body["built_at"] == "2026-01-01T00:00:00Z"


def test_version_file_is_read_per_request(client, monkeypatch, tmp_path):
    version_file = tmp_path / "version.json"
    monkeypatch.setattr(version_module, "VERSION_FILE", version_file)
    version_file.write_text(json.dumps({"build_sha": "old1111"}))
    assert client.get("/health").json()["build_sha"] == "old1111"
    version_file.write_text(json.dumps({"build_sha": "new2222"}))
    assert client.get("/health").json()["build_sha"] == "new2222"


def test_frontend_fields_survive_corrupt_file(client, monkeypatch, tmp_path):
    version_file = tmp_path / "version.json"
    version_file.write_text("not json")
    monkeypatch.setattr(version_module, "VERSION_FILE", version_file)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["build_sha"] is None
