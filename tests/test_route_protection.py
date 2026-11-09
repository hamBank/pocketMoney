"""Fleet spec AUTH-6 (per-route model): a new route is protected unless listed here."""
import re

from backend.main import app
from conftest import auth_headers, sign_in  # noqa: F401  (conftest sets AUTH_ENABLED)

# Everything reachable without a token, on purpose. Adding to this list is a
# security decision: say why next to the entry.
PUBLIC = {
    ("GET", "/health"),  # liveness for the smoke check and the update banner
    ("POST", "/deploy"),  # GitHub webhook, authenticated by its HMAC signature
    ("GET", "/auth/config"),  # client bootstrap, before sign-in
    ("POST", "/auth/google"),  # sign-in itself
}


def documented_routes():
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            if method in ("get", "post", "put", "patch", "delete"):
                yield method.upper(), path


def test_every_route_requires_a_token_unless_listed_public(client):
    unprotected = []
    for method, path in documented_routes():
        if (method, path) in PUBLIC:
            continue
        url = re.sub(r"\{[^}]+\}", "1", path)
        response = client.request(method, url, json={} if method != "GET" else None)
        if response.status_code != 401:
            unprotected.append(f"{method} {path} -> {response.status_code}")
    assert not unprotected, "routes answering without a token: " + ", ".join(unprotected)


def test_public_list_has_no_stale_entries():
    assert PUBLIC <= set(documented_routes())
