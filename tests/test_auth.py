from datetime import datetime, timedelta, timezone

import jwt
from conftest import auth_headers, fake_google, sign_in

from backend.auth import REFRESHED_TOKEN_HEADER, TOKEN_LIFETIME
from backend.config import settings


def token_issued(user_id, ago):
    """A token for user_id as if signed in `ago` before now."""
    exp = datetime.now(timezone.utc) - ago + TOKEN_LIFETIME
    return jwt.encode({"sub": str(user_id), "exp": exp}, settings.jwt_secret, algorithm="HS256")


def test_first_signin_becomes_admin(client, monkeypatch):
    data = sign_in(client, monkeypatch, "parent@example.com", name="Parent")
    assert data["user"]["role"] == "admin"
    assert data["user"]["email"] == "parent@example.com"
    assert data["token"]


def test_unlisted_email_is_rejected(client, monkeypatch):
    fake_google(monkeypatch, "stranger@example.com")
    response = client.post("/auth/google", json={"credential": "fake"})
    assert response.status_code == 403


def test_invalid_google_token_is_401(client, monkeypatch):
    def boom(credential):
        raise ValueError("bad token")

    monkeypatch.setattr("backend.routers.auth_router.verify_google_token", boom)
    response = client.post("/auth/google", json={"credential": "garbage"})
    assert response.status_code == 401


def test_me_roundtrip(client, monkeypatch):
    token = sign_in(client, monkeypatch, "parent@example.com")["token"]
    me = client.get("/auth/me", headers=auth_headers(token))
    assert me.status_code == 200
    assert me.json()["email"] == "parent@example.com"


def test_me_requires_token(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/auth/me", headers=auth_headers("junk")).status_code == 401


def test_token_carries_iat_and_exp(client, monkeypatch):
    token = sign_in(client, monkeypatch, "parent@example.com")["token"]
    claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == TOKEN_LIFETIME.total_seconds()


def test_fresh_token_is_not_refreshed(client, monkeypatch):
    token = sign_in(client, monkeypatch, "parent@example.com")["token"]
    me = client.get("/auth/me", headers=auth_headers(token))
    assert me.status_code == 200
    assert REFRESHED_TOKEN_HEADER not in me.headers


def test_token_past_half_life_is_refreshed(client, monkeypatch):
    user_id = sign_in(client, monkeypatch, "parent@example.com")["user"]["id"]
    old = token_issued(user_id, ago=timedelta(days=20))
    me = client.get("/auth/me", headers=auth_headers(old))
    assert me.status_code == 200
    fresh = me.headers[REFRESHED_TOKEN_HEADER]
    exp = jwt.decode(fresh, settings.jwt_secret, algorithms=["HS256"])["exp"]
    remaining = datetime.fromtimestamp(exp, timezone.utc) - datetime.now(timezone.utc)
    assert remaining > TOKEN_LIFETIME - timedelta(minutes=1)
    # Other endpoints refresh too, alongside their own headers.
    listing = client.get("/claims", headers=auth_headers(old))
    assert listing.status_code == 200
    assert REFRESHED_TOKEN_HEADER in listing.headers


def test_expired_token_is_401(client, monkeypatch):
    user_id = sign_in(client, monkeypatch, "parent@example.com")["user"]["id"]
    expired = token_issued(user_id, ago=TOKEN_LIFETIME + timedelta(minutes=1))
    me = client.get("/auth/me", headers=auth_headers(expired))
    assert me.status_code == 401
    assert REFRESHED_TOKEN_HEADER not in me.headers


def test_invited_user_signs_in_as_user_role(client, monkeypatch):
    admin_token = sign_in(client, monkeypatch, "parent@example.com")["token"]
    invited = client.post(
        "/users/invite",
        json={"email": "kid@example.com", "name": "Kid"},
        headers=auth_headers(admin_token),
    )
    assert invited.status_code == 201

    data = sign_in(client, monkeypatch, "kid@example.com", sub="google-sub-kid")
    assert data["user"]["role"] == "user"
    assert data["user"]["name"] == "Kid"  # invite name wins over Google's


def test_deactivated_user_cannot_sign_in(client, monkeypatch):
    admin = sign_in(client, monkeypatch, "parent@example.com")
    admin_token = admin["token"]
    kid = client.post(
        "/users/invite",
        json={"email": "kid@example.com"},
        headers=auth_headers(admin_token),
    ).json()
    client.patch(
        f"/users/{kid['id']}",
        json={"is_active": False},
        headers=auth_headers(admin_token),
    )
    fake_google(monkeypatch, "kid@example.com", sub="google-sub-kid")
    response = client.post("/auth/google", json={"credential": "fake"})
    assert response.status_code == 403


def test_auth_disabled_returns_dev_admin(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_enabled", False)
    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "admin"
    assert me.json()["email"] == "dev@localhost"


def test_auth_config_is_public(client):
    response = client.get("/auth/config")
    assert response.status_code == 200
    body = response.json()
    assert body["auth_enabled"] is True
    assert "currency_symbol" in body
