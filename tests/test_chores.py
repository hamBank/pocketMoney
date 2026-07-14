from conftest import auth_headers, sign_in


def setup_family(client, monkeypatch):
    admin_token = sign_in(client, monkeypatch, "parent@example.com")["token"]
    kid = client.post(
        "/users/invite",
        json={"email": "kid@example.com", "name": "Kid"},
        headers=auth_headers(admin_token),
    ).json()
    kid_token = sign_in(client, monkeypatch, "kid@example.com", sub="sub-kid")["token"]
    return admin_token, kid, kid_token


def make_chore(client, token, **overrides):
    body = {"name": "Dishes", "value": 150}
    body.update(overrides)
    response = client.post("/chores", json=body, headers=auth_headers(token))
    assert response.status_code == 201, response.text
    return response.json()


def test_admin_creates_chore_and_kid_sees_it_claimable(client, monkeypatch):
    admin_token, _kid, kid_token = setup_family(client, monkeypatch)
    make_chore(client, admin_token, schedule="daily")
    chores = client.get("/chores", headers=auth_headers(kid_token)).json()
    assert len(chores) == 1
    assert chores[0]["name"] == "Dishes"
    assert chores[0]["claimable"] is True


def test_kid_cannot_create_update_or_delete(client, monkeypatch):
    admin_token, _kid, kid_token = setup_family(client, monkeypatch)
    chore = make_chore(client, admin_token)
    assert (
        client.post("/chores", json={"name": "X", "value": 1}, headers=auth_headers(kid_token)).status_code
        == 403
    )
    assert (
        client.patch(f"/chores/{chore['id']}", json={"value": 5}, headers=auth_headers(kid_token)).status_code
        == 403
    )
    assert client.delete(f"/chores/{chore['id']}", headers=auth_headers(kid_token)).status_code == 403


def test_invalid_weekly_config_is_422(client, monkeypatch):
    admin_token, _kid, _ = setup_family(client, monkeypatch)
    response = client.post(
        "/chores",
        json={"name": "Bins", "value": 100, "schedule": "weekly"},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 422


def test_unknown_assignee_is_422(client, monkeypatch):
    admin_token, _kid, _ = setup_family(client, monkeypatch)
    response = client.post(
        "/chores",
        json={"name": "Bins", "value": 100, "assignee_ids": [999]},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 422


def test_assigned_chore_hidden_from_other_kids(client, monkeypatch):
    admin_token, kid, kid_token = setup_family(client, monkeypatch)
    other = client.post(
        "/users/invite",
        json={"email": "kid2@example.com"},
        headers=auth_headers(admin_token),
    ).json()
    make_chore(client, admin_token, assignee_ids=[other["id"]])
    assert client.get("/chores", headers=auth_headers(kid_token)).json() == []
    # Admin still sees it.
    assert len(client.get("/chores", headers=auth_headers(admin_token)).json()) == 1


def test_soft_delete_hides_from_default_listing(client, monkeypatch):
    admin_token, _kid, kid_token = setup_family(client, monkeypatch)
    chore = make_chore(client, admin_token)
    assert client.delete(f"/chores/{chore['id']}", headers=auth_headers(admin_token)).status_code == 204
    assert client.get("/chores", headers=auth_headers(kid_token)).json() == []
    all_chores = client.get("/chores?all=true", headers=auth_headers(admin_token)).json()
    assert len(all_chores) == 1
    assert all_chores[0]["is_active"] is False
    assert all_chores[0]["claimable"] is False


def test_patch_validates_merged_schedule(client, monkeypatch):
    admin_token, _kid, _ = setup_family(client, monkeypatch)
    chore = make_chore(client, admin_token)
    # Switching to weekly without weekdays must fail...
    response = client.patch(
        f"/chores/{chore['id']}",
        json={"schedule": "weekly"},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 422
    # ...and succeed with config supplied.
    response = client.patch(
        f"/chores/{chore['id']}",
        json={"schedule": "weekly", "schedule_config": {"weekdays": [0, 5]}},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 200
    assert response.json()["schedule_config"] == {"weekdays": [0, 5]}


def test_get_missing_chore_is_404(client, monkeypatch):
    admin_token, _kid, _ = setup_family(client, monkeypatch)
    assert client.get("/chores/42", headers=auth_headers(admin_token)).status_code == 404
