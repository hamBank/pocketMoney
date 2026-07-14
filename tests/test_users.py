from conftest import auth_headers, sign_in


def admin_and_kid(client, monkeypatch):
    admin_token = sign_in(client, monkeypatch, "parent@example.com")["token"]
    kid = client.post(
        "/users/invite",
        json={"email": "kid@example.com", "name": "Kid"},
        headers=auth_headers(admin_token),
    ).json()
    kid_token = sign_in(client, monkeypatch, "kid@example.com", sub="sub-kid")["token"]
    return admin_token, kid, kid_token


def test_list_users_requires_admin(client, monkeypatch):
    admin_token, _kid, kid_token = admin_and_kid(client, monkeypatch)
    assert client.get("/users", headers=auth_headers(kid_token)).status_code == 403
    response = client.get("/users", headers=auth_headers(admin_token))
    assert response.status_code == 200
    assert [u["email"] for u in response.json()] == [
        "parent@example.com",
        "kid@example.com",
    ]


def test_invite_duplicate_email_conflicts(client, monkeypatch):
    admin_token, _kid, _ = admin_and_kid(client, monkeypatch)
    response = client.post(
        "/users/invite",
        json={"email": "kid@example.com"},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 409


def test_admin_updates_role_and_allowance(client, monkeypatch):
    admin_token, kid, _ = admin_and_kid(client, monkeypatch)
    response = client.patch(
        f"/users/{kid['id']}",
        json={"weekly_allowance": 500, "role": "admin"},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200
    assert response.json()["weekly_allowance"] == 500
    assert response.json()["role"] == "admin"


def test_non_admin_cannot_update_users(client, monkeypatch):
    _admin_token, kid, kid_token = admin_and_kid(client, monkeypatch)
    response = client.patch(
        f"/users/{kid['id']}",
        json={"weekly_allowance": 99999},
        headers=auth_headers(kid_token),
    )
    assert response.status_code == 403


def test_admin_cannot_demote_or_deactivate_self(client, monkeypatch):
    admin_token = sign_in(client, monkeypatch, "parent@example.com")["token"]
    admin_id = sign_in(client, monkeypatch, "parent@example.com")["user"]["id"]
    for payload in ({"role": "user"}, {"is_active": False}):
        response = client.patch(
            f"/users/{admin_id}", json=payload, headers=auth_headers(admin_token)
        )
        assert response.status_code == 409


def test_update_missing_user_is_404(client, monkeypatch):
    admin_token = sign_in(client, monkeypatch, "parent@example.com")["token"]
    response = client.patch(
        "/users/999", json={"name": "x"}, headers=auth_headers(admin_token)
    )
    assert response.status_code == 404
