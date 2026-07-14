import hashlib
import hmac
import json

from backend.config import settings

SECRET = "test-deploy-secret"


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def post(client, body: bytes, signature: str | None = None):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    return client.post("/deploy", content=body, headers=headers)


def test_unconfigured_secret_is_503(client):
    assert post(client, b"{}").status_code == 503


def test_bad_signature_is_403(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "deploy_secret", SECRET)
    monkeypatch.setattr(settings, "deploy_trigger_path", str(tmp_path / "trigger"))
    assert post(client, b"{}", "sha256=wrong").status_code == 403
    assert post(client, b"{}").status_code == 403  # missing header
    assert not (tmp_path / "trigger").exists()


def test_main_push_touches_trigger(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "deploy_secret", SECRET)
    trigger = tmp_path / "trigger"
    monkeypatch.setattr(settings, "deploy_trigger_path", str(trigger))
    body = json.dumps({"ref": "refs/heads/main"}).encode()
    response = post(client, body, sign(body))
    assert response.status_code == 200
    assert response.json()["status"] == "triggered"
    assert trigger.exists()


def test_other_branch_push_is_ignored(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "deploy_secret", SECRET)
    trigger = tmp_path / "trigger"
    monkeypatch.setattr(settings, "deploy_trigger_path", str(trigger))
    body = json.dumps({"ref": "refs/heads/feature"}).encode()
    response = post(client, body, sign(body))
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert not trigger.exists()


def test_non_github_payload_still_triggers(client, monkeypatch, tmp_path):
    # Manual `curl` deploys without a JSON ref should work too.
    monkeypatch.setattr(settings, "deploy_secret", SECRET)
    trigger = tmp_path / "trigger"
    monkeypatch.setattr(settings, "deploy_trigger_path", str(trigger))
    body = b"deploy please"
    response = post(client, body, sign(body))
    assert response.status_code == 200
    assert trigger.exists()
