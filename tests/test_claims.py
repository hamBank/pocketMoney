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
    body = {"name": "Dishes", "value": 150, "schedule": "daily"}
    body.update(overrides)
    return client.post("/chores", json=body, headers=auth_headers(token)).json()


def balance(client, token):
    return client.get("/auth/me", headers=auth_headers(token)).json()["balance"]


def test_full_lifecycle_claim_approve_credits_balance(client, monkeypatch):
    admin_token, kid, kid_token = setup_family(client, monkeypatch)
    chore = make_chore(client, admin_token)

    claim = client.post(
        "/claims",
        json={"chore_id": chore["id"], "note": "done before school"},
        headers=auth_headers(kid_token),
    )
    assert claim.status_code == 201, claim.text
    claim = claim.json()
    assert claim["status"] == "pending"
    assert claim["original_value"] == 150
    assert claim["chore_name"] == "Dishes"
    assert claim["user_id"] == kid["id"]

    # Chore is consumed for today...
    chores = client.get("/chores", headers=auth_headers(kid_token)).json()
    assert chores[0]["claimable"] is False
    # ...and can't be double-claimed.
    dup = client.post(
        "/claims", json={"chore_id": chore["id"]}, headers=auth_headers(kid_token)
    )
    assert dup.status_code == 409

    approved = client.post(
        f"/claims/{claim['id']}/approve", json={}, headers=auth_headers(admin_token)
    )
    assert approved.status_code == 200
    assert approved.json()["approved_value"] == 150
    assert balance(client, kid_token) == 150

    # Ledger row is linked to the claim.
    txs = client.get("/transactions", headers=auth_headers(kid_token)).json()
    assert len(txs) == 1
    assert txs[0]["type"] == "claim_payout"
    assert txs[0]["claim_id"] == claim["id"]


def test_resolved_claims_are_immutable(client, monkeypatch):
    admin_token, _kid, kid_token = setup_family(client, monkeypatch)
    chore = make_chore(client, admin_token)
    claim = client.post(
        "/claims", json={"chore_id": chore["id"]}, headers=auth_headers(kid_token)
    ).json()
    client.post(f"/claims/{claim['id']}/approve", json={}, headers=auth_headers(admin_token))
    for action in ("approve", "reject", "cancel"):
        response = client.post(
            f"/claims/{claim['id']}/{action}", json={}, headers=auth_headers(admin_token)
        )
        assert response.status_code == 409


def test_approve_with_edited_value_keeps_original(client, monkeypatch):
    admin_token, _kid, kid_token = setup_family(client, monkeypatch)
    chore = make_chore(client, admin_token)
    claim = client.post(
        "/claims", json={"chore_id": chore["id"]}, headers=auth_headers(kid_token)
    ).json()
    approved = client.post(
        f"/claims/{claim['id']}/approve",
        json={"approved_value": 100, "note": "half done"},
        headers=auth_headers(admin_token),
    ).json()
    assert approved["original_value"] == 150
    assert approved["approved_value"] == 100
    assert approved["resolution_note"] == "half done"
    assert balance(client, kid_token) == 100


def test_reject_frees_slot_and_pays_nothing(client, monkeypatch):
    admin_token, _kid, kid_token = setup_family(client, monkeypatch)
    chore = make_chore(client, admin_token)
    claim = client.post(
        "/claims", json={"chore_id": chore["id"]}, headers=auth_headers(kid_token)
    ).json()
    client.post(
        f"/claims/{claim['id']}/reject",
        json={"note": "not actually done"},
        headers=auth_headers(admin_token),
    )
    assert balance(client, kid_token) == 0
    chores = client.get("/chores", headers=auth_headers(kid_token)).json()
    assert chores[0]["claimable"] is True  # can try again


def test_kid_cancels_own_pending_claim(client, monkeypatch):
    admin_token, _kid, kid_token = setup_family(client, monkeypatch)
    chore = make_chore(client, admin_token)
    claim = client.post(
        "/claims", json={"chore_id": chore["id"]}, headers=auth_headers(kid_token)
    ).json()
    response = client.post(
        f"/claims/{claim['id']}/cancel", headers=auth_headers(kid_token)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_kid_cannot_use_admin_claim_features(client, monkeypatch):
    admin_token, kid, kid_token = setup_family(client, monkeypatch)
    chore = make_chore(client, admin_token)
    for body in (
        {"chore_id": chore["id"], "user_id": 1},  # on behalf of someone else
        {"kind": "adhoc", "name": "Extra", "value": 100},
        {"kind": "penalty", "name": "Broke window", "value": -500},
        {"chore_id": chore["id"], "auto_approve": True},
    ):
        response = client.post("/claims", json=body, headers=auth_headers(kid_token))
        assert response.status_code == 403, body


def test_kid_cannot_resolve_claims(client, monkeypatch):
    admin_token, _kid, kid_token = setup_family(client, monkeypatch)
    chore = make_chore(client, admin_token)
    claim = client.post(
        "/claims", json={"chore_id": chore["id"]}, headers=auth_headers(kid_token)
    ).json()
    for action in ("approve", "reject"):
        response = client.post(
            f"/claims/{claim['id']}/{action}", json={}, headers=auth_headers(kid_token)
        )
        assert response.status_code == 403


def test_admin_lodges_on_behalf_with_auto_approve(client, monkeypatch):
    admin_token, kid, kid_token = setup_family(client, monkeypatch)
    chore = make_chore(client, admin_token)
    response = client.post(
        "/claims",
        json={"chore_id": chore["id"], "user_id": kid["id"], "auto_approve": True},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "approved"
    assert body["user_id"] == kid["id"]
    assert body["submitted_by"] != kid["id"]
    assert balance(client, kid_token) == 150


def test_penalty_debits_balance(client, monkeypatch):
    admin_token, kid, kid_token = setup_family(client, monkeypatch)
    response = client.post(
        "/claims",
        json={
            "kind": "penalty",
            "name": "Broke window",
            "value": -500,
            "user_id": kid["id"],
            "auto_approve": True,
        },
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 201
    assert balance(client, kid_token) == -500
    txs = client.get("/transactions", headers=auth_headers(kid_token)).json()
    assert txs[0]["type"] == "penalty"


def test_penalty_must_be_negative_and_adhoc_positive(client, monkeypatch):
    admin_token, kid, _ = setup_family(client, monkeypatch)
    bad_penalty = client.post(
        "/claims",
        json={"kind": "penalty", "name": "x", "value": 500, "user_id": kid["id"]},
        headers=auth_headers(admin_token),
    )
    assert bad_penalty.status_code == 422
    bad_adhoc = client.post(
        "/claims",
        json={"kind": "adhoc", "name": "x", "value": -500, "user_id": kid["id"]},
        headers=auth_headers(admin_token),
    )
    assert bad_adhoc.status_code == 422


def test_adhoc_promoted_to_chore(client, monkeypatch):
    admin_token, kid, kid_token = setup_family(client, monkeypatch)
    response = client.post(
        "/claims",
        json={
            "kind": "adhoc",
            "name": "Wash car",
            "value": 300,
            "user_id": kid["id"],
            "create_chore": True,
            "auto_approve": True,
        },
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["chore_id"] is not None
    assert body["chore_name"] == "Wash car"
    chores = client.get("/chores", headers=auth_headers(kid_token)).json()
    assert any(c["name"] == "Wash car" and c["value"] == 300 for c in chores)
    assert balance(client, kid_token) == 300


def test_kid_sees_only_own_claims(client, monkeypatch):
    admin_token, kid, kid_token = setup_family(client, monkeypatch)
    chore = make_chore(client, admin_token)
    client.post("/claims", json={"chore_id": chore["id"]}, headers=auth_headers(kid_token))
    client.post(
        "/claims", json={"chore_id": chore["id"]}, headers=auth_headers(admin_token)
    )  # admin claims for themselves
    kid_claims = client.get("/claims", headers=auth_headers(kid_token))
    assert kid_claims.headers["X-Total-Count"] == "1"
    assert all(c["user_id"] == kid["id"] for c in kid_claims.json())
    admin_claims = client.get("/claims", headers=auth_headers(admin_token))
    assert admin_claims.headers["X-Total-Count"] == "2"


def test_pending_filter(client, monkeypatch):
    admin_token, _kid, kid_token = setup_family(client, monkeypatch)
    chore = make_chore(client, admin_token)
    claim = client.post(
        "/claims", json={"chore_id": chore["id"]}, headers=auth_headers(kid_token)
    ).json()
    client.post(f"/claims/{claim['id']}/approve", json={}, headers=auth_headers(admin_token))
    pending = client.get(
        "/claims?status_filter=pending", headers=auth_headers(admin_token)
    ).json()
    assert pending == []


def test_shared_chore_blocks_second_kid_after_claim(client, monkeypatch):
    admin_token, kid, kid_token = setup_family(client, monkeypatch)
    kid2 = client.post(
        "/users/invite",
        json={"email": "kid2@example.com", "name": "Kid2"},
        headers=auth_headers(admin_token),
    ).json()
    kid2_token = sign_in(client, monkeypatch, "kid2@example.com", sub="sub-kid2")["token"]
    chore = make_chore(client, admin_token, claim_mode="shared")
    first = client.post(
        "/claims", json={"chore_id": chore["id"]}, headers=auth_headers(kid_token)
    )
    assert first.status_code == 201
    second = client.post(
        "/claims", json={"chore_id": chore["id"]}, headers=auth_headers(kid2_token)
    )
    assert second.status_code == 409
