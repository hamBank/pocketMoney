import os

# Must be set before any backend import — Settings reads env at import time.
# TEST_DATABASE_URL runs the suite on Postgres (the backend-postgres CI job).
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite:///./test_pmoney.db")
os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["ALLOWED_EMAILS"] = "parent@example.com"

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel

from backend.database import engine
from backend.main import app


@pytest.fixture(autouse=True)
def fresh_db():
    SQLModel.metadata.create_all(engine)
    # Fleet spec DB-6: psycopg3 prepares repeated statements per connection, and a
    # pooled connection's cached plan can outlive the tables it was planned for.
    engine.dispose()
    yield
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def client():
    return TestClient(app)


def fake_google(monkeypatch, email, sub="google-sub-1", name="Test Person"):
    """Make /auth/google accept any credential as the given Google account."""
    monkeypatch.setattr(
        "backend.routers.auth_router.verify_google_token",
        lambda credential: {
            "email": email,
            "sub": sub,
            "name": name,
            "picture": None,
        },
    )


def sign_in(client, monkeypatch, email, **kwargs):
    fake_google(monkeypatch, email, **kwargs)
    response = client.post("/auth/google", json={"credential": "fake"})
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}
