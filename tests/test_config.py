import pytest
from pydantic import ValidationError

from backend.config import DEFAULT_JWT_SECRET, Settings


@pytest.mark.parametrize("secret", [DEFAULT_JWT_SECRET, ""])
def test_auth_refuses_a_public_or_empty_secret(secret):
    with pytest.raises(ValidationError, match="JWT_SECRET"):
        Settings(auth_enabled=True, jwt_secret=secret)


def test_auth_accepts_a_private_secret():
    assert Settings(auth_enabled=True, jwt_secret="x").jwt_secret == "x"


def test_auth_disabled_allows_the_default_secret():
    assert Settings(auth_enabled=False, jwt_secret=DEFAULT_JWT_SECRET).auth_enabled is False
