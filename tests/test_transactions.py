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


def test_withdrawal_and_adjustment_flow(client, monkeypatch):
    admin_token, kid, kid_token = setup_family(client, monkeypatch)
    client.post(
        "/transactions",
        json={"user_id": kid["id"], "type": "adjustment", "amount": 1000, "note": "starting balance"},
        headers=auth_headers(admin_token),
    )
    withdrawal = client.post(
        "/transactions",
        json={"user_id": kid["id"], "type": "withdrawal", "amount": -300, "note": "spent at shop"},
        headers=auth_headers(admin_token),
    )
    assert withdrawal.status_code == 201
    me = client.get("/auth/me", headers=auth_headers(kid_token)).json()
    assert me["balance"] == 700
    # Admin user list shows the same computed balance.
    users = client.get("/users", headers=auth_headers(admin_token)).json()
    assert next(u for u in users if u["id"] == kid["id"])["balance"] == 700


def test_validation_rules(client, monkeypatch):
    admin_token, kid, _ = setup_family(client, monkeypatch)
    cases = [
        {"user_id": kid["id"], "type": "withdrawal", "amount": 300},  # positive withdrawal
        {"user_id": kid["id"], "type": "adjustment", "amount": 100},  # missing note
        {"user_id": kid["id"], "type": "adjustment", "amount": 0, "note": "x"},  # zero
        {"user_id": kid["id"], "type": "claim_payout", "amount": 100},  # reserved type
        {"user_id": kid["id"], "type": "allowance", "amount": 100},  # reserved type
    ]
    for body in cases:
        response = client.post(
            "/transactions", json=body, headers=auth_headers(admin_token)
        )
        assert response.status_code == 422, body
    missing_user = client.post(
        "/transactions",
        json={"user_id": 999, "type": "withdrawal", "amount": -100},
        headers=auth_headers(admin_token),
    )
    assert missing_user.status_code == 404


def test_kid_cannot_write_and_only_sees_own(client, monkeypatch):
    admin_token, kid, kid_token = setup_family(client, monkeypatch)
    forbidden = client.post(
        "/transactions",
        json={"user_id": kid["id"], "type": "adjustment", "amount": 100, "note": "x"},
        headers=auth_headers(kid_token),
    )
    assert forbidden.status_code == 403

    # Admin writes one row for the kid and one for themselves.
    admin_id = client.get("/auth/me", headers=auth_headers(admin_token)).json()["id"]
    for target in (kid["id"], admin_id):
        client.post(
            "/transactions",
            json={"user_id": target, "type": "adjustment", "amount": 100, "note": "x"},
            headers=auth_headers(admin_token),
        )
    # Kid ignores user_id filters — always own ledger.
    rows = client.get(
        f"/transactions?user_id={admin_id}", headers=auth_headers(kid_token)
    )
    assert rows.headers["X-Total-Count"] == "1"
    assert all(r["user_id"] == kid["id"] for r in rows.json())
    # Admin can filter to anyone.
    rows = client.get("/transactions", headers=auth_headers(admin_token))
    assert rows.headers["X-Total-Count"] == "2"
