"""SQLModel tables + API schemas.

Tables land here phase by phase (see DATA_MODEL.md / IMPLEMENTATION_PLAN.md).
Alembic autogenerate reads SQLModel.metadata via this module.
"""

from datetime import datetime, timezone
from enum import Enum

from sqlmodel import Field, SQLModel  # noqa: F401


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, Enum):
    admin = "admin"
    user = "user"


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    google_sub: str | None = Field(default=None, unique=True, index=True)
    email: str = Field(unique=True, index=True)
    name: str = ""
    avatar_url: str | None = None
    role: UserRole = Field(default=UserRole.user)
    weekly_allowance: int = 0  # cents, signed; applied Mondays (Phase 4)
    is_active: bool = True
    created_at: datetime = Field(default_factory=utcnow)


class UserRead(SQLModel):
    id: int
    email: str
    name: str
    avatar_url: str | None
    role: UserRole
    weekly_allowance: int
    is_active: bool
    balance: int = 0  # ledger sum once transactions land (Phase 3)


class UserUpdate(SQLModel):
    name: str | None = None
    role: UserRole | None = None
    weekly_allowance: int | None = None
    is_active: bool | None = None


class UserInvite(SQLModel):
    email: str
    name: str = ""
    role: UserRole = UserRole.user
