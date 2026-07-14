"""SQLModel tables + API schemas.

Tables land here phase by phase (see DATA_MODEL.md / IMPLEMENTATION_PLAN.md).
Alembic autogenerate reads SQLModel.metadata via this module.
"""

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import JSON, Column
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


class ClaimMode(str, Enum):
    per_user = "per_user"  # each user has their own instance per period
    shared = "shared"  # first user to claim wins the period
    open = "open"  # re-claimable by anyone after cooldown_minutes


class ScheduleKind(str, Enum):
    none = "none"  # always available / ad-hoc
    daily = "daily"
    weekly = "weekly"  # schedule_config: {"weekdays": [0..6]} (Mon=0)
    monthly = "monthly"  # schedule_config: {"day_of_month": 1..31}


class Chore(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    description: str | None = None
    value: int  # cents credited when an approved claim resolves
    schedule: ScheduleKind = Field(default=ScheduleKind.none)
    schedule_config: dict | None = Field(default=None, sa_column=Column(JSON))
    claim_mode: ClaimMode = Field(default=ClaimMode.per_user)
    cooldown_minutes: int = 5  # open mode only
    assignee_ids: list[int] | None = Field(default=None, sa_column=Column(JSON))
    is_active: bool = True
    created_by: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ChoreCreate(SQLModel):
    name: str
    description: str | None = None
    value: int = Field(ge=0)
    schedule: ScheduleKind = ScheduleKind.none
    schedule_config: dict | None = None
    claim_mode: ClaimMode = ClaimMode.per_user
    cooldown_minutes: int = Field(default=5, ge=0)
    assignee_ids: list[int] | None = None


class ChoreUpdate(SQLModel):
    name: str | None = None
    description: str | None = None
    value: int | None = Field(default=None, ge=0)
    schedule: ScheduleKind | None = None
    schedule_config: dict | None = None
    claim_mode: ClaimMode | None = None
    cooldown_minutes: int | None = Field(default=None, ge=0)
    assignee_ids: list[int] | None = None
    is_active: bool | None = None


class ChoreRead(SQLModel):
    id: int
    name: str
    description: str | None
    value: int
    schedule: ScheduleKind
    schedule_config: dict | None
    claim_mode: ClaimMode
    cooldown_minutes: int
    assignee_ids: list[int] | None
    is_active: bool
    created_by: int
    created_at: datetime
    updated_at: datetime
    claimable: bool = False  # computed per requesting user


class ClaimKind(str, Enum):
    chore = "chore"
    adhoc = "adhoc"
    penalty = "penalty"


class ClaimStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class Claim(SQLModel, table=True):
    """Immutable after resolution — corrections are new adjustment
    transactions, never edits (SPEC.md)."""

    id: int | None = Field(default=None, primary_key=True)
    chore_id: int | None = Field(default=None, foreign_key="chore.id")
    user_id: int = Field(foreign_key="user.id", index=True)  # who it applies to
    submitted_by: int = Field(foreign_key="user.id")
    submitted_at: datetime = Field(default_factory=utcnow)
    kind: ClaimKind = Field(default=ClaimKind.chore)
    adhoc_name: str | None = None  # label for adhoc/penalty claims
    original_value: int
    original_note: str | None = None
    status: ClaimStatus = Field(default=ClaimStatus.pending, index=True)
    approved_value: int | None = None
    resolution_note: str | None = None
    resolved_by: int | None = Field(default=None, foreign_key="user.id")
    resolved_at: datetime | None = None


class ClaimCreate(SQLModel):
    chore_id: int | None = None
    note: str | None = None
    # Admin-only extras:
    user_id: int | None = None  # lodge on behalf of another user
    kind: ClaimKind = ClaimKind.chore
    name: str | None = None  # required for adhoc/penalty
    value: int | None = None  # cents; >0 for adhoc, <0 for penalty
    auto_approve: bool = False
    create_chore: bool = False  # promote an adhoc into a recurring chore


class ClaimResolve(SQLModel):
    approved_value: int | None = None  # defaults to original_value
    note: str | None = None


class ClaimRead(SQLModel):
    id: int
    chore_id: int | None
    chore_name: str  # chore name or adhoc label
    user_id: int
    user_name: str
    submitted_by: int
    submitted_by_name: str
    submitted_at: datetime
    kind: ClaimKind
    original_value: int
    original_note: str | None
    status: ClaimStatus
    approved_value: int | None
    resolution_note: str | None
    resolved_by: int | None
    resolved_by_name: str | None
    resolved_at: datetime | None


class TransactionType(str, Enum):
    claim_payout = "claim_payout"
    penalty = "penalty"
    withdrawal = "withdrawal"
    adjustment = "adjustment"
    allowance = "allowance"


class Transaction(SQLModel, table=True):
    """Append-only ledger; balance = SUM(amount). Never updated or deleted."""

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    claim_id: int | None = Field(default=None, foreign_key="claim.id")
    type: TransactionType
    amount: int  # cents, signed (+ credit / − debit)
    note: str | None = None  # required for adjustment; ISO week for allowance
    created_by: int | None = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=utcnow)


class TransactionCreate(SQLModel):
    user_id: int
    type: TransactionType  # withdrawal or adjustment only via API
    amount: int
    note: str | None = None


class TransactionRead(SQLModel):
    id: int
    user_id: int
    user_name: str
    claim_id: int | None
    type: TransactionType
    amount: int
    note: str | None
    created_by: int | None
    created_by_name: str | None
    created_at: datetime
