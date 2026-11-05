from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlmodel import Session, select

from .config import settings
from .database import get_session
from .models import User, UserRole, utcnow

TOKEN_LIFETIME = timedelta(days=30)
# Sliding session: a token past half its life is swapped for a fresh one on
# the next authenticated request, so only 30 days of inactivity signs you out.
REFRESH_AFTER = TOKEN_LIFETIME / 2
REFRESHED_TOKEN_HEADER = "X-Refreshed-Token"
DEV_USER_EMAIL = "dev@localhost"

bearer_scheme = HTTPBearer(auto_error=False)


def verify_google_token(credential: str) -> dict:
    """Verify a Google ID token and return its claims. Raises ValueError."""
    return google_id_token.verify_oauth2_token(
        credential, google_requests.Request(), settings.google_client_id
    )


def allowed_emails() -> set[str]:
    return {
        email.strip().lower()
        for email in settings.allowed_emails.split(",")
        if email.strip()
    }


def create_access_token(user: User) -> str:
    now = utcnow()
    payload = {"sub": str(user.id), "iat": now, "exp": now + TOKEN_LIFETIME}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _dev_user(session: Session) -> User:
    """AUTH_ENABLED=false: everyone is a persisted local admin (dev only)."""
    user = session.exec(select(User).where(User.email == DEV_USER_EMAIL)).first()
    if user is None:
        user = User(
            email=DEV_USER_EMAIL,
            name="Dev Admin",
            role=UserRole.admin,
            google_sub="dev",
        )
        session.add(user)
        session.commit()
        session.refresh(user)
    return user


def get_current_user(
    response: Response,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: Session = Depends(get_session),
) -> User:
    if not settings.auth_enabled:
        return _dev_user(session)
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    try:
        payload = jwt.decode(
            creds.credentials, settings.jwt_secret, algorithms=["HS256"]
        )
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = session.get(User, int(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown or inactive user")
    expires = datetime.fromtimestamp(payload["exp"], timezone.utc)
    if expires - utcnow() < TOKEN_LIFETIME - REFRESH_AFTER:
        response.headers[REFRESHED_TOKEN_HEADER] = create_access_token(user)
    return user
