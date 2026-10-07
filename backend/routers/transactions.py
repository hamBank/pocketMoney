from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlmodel import Session, select

from ..database import get_session
from ..models import (
    Transaction,
    TransactionCreate,
    TransactionRead,
    TransactionType,
    User,
    UserRole,
)
from ..permissions import require_admin_role, require_user_role
from ..sheets_sync import run_sheet_sync

router = APIRouter(prefix="/transactions", tags=["transactions"])

# Types an admin may write directly; claim payouts/penalties come from claim
# approval and allowance rows from the Monday job (Phase 4).
ADMIN_TYPES = (TransactionType.withdrawal, TransactionType.adjustment)


def _to_read(session: Session, tx: Transaction) -> TransactionRead:
    def name_of(user_id: int | None) -> str | None:
        if user_id is None:
            return None
        user = session.get(User, user_id)
        return (user.name or user.email) if user else f"user {user_id}"

    data = tx.model_dump()
    data.update(user_name=name_of(tx.user_id), created_by_name=name_of(tx.created_by))
    return TransactionRead.model_validate(data)


@router.get("", response_model=list[TransactionRead])
def list_transactions(
    response: Response,
    user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(require_user_role),
):
    if user.role != UserRole.admin:
        user_id = user.id  # kids only ever see their own ledger
    query = select(Transaction)
    if user_id is not None:
        query = query.where(Transaction.user_id == user_id)
    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    response.headers["X-Total-Count"] = str(total)
    rows = session.exec(
        query.order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(min(limit, 200))
        .offset(offset)
    ).all()
    return [_to_read(session, tx) for tx in rows]


@router.post("", response_model=TransactionRead, status_code=status.HTTP_201_CREATED)
def create_transaction(
    body: TransactionCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    admin: User = Depends(require_admin_role),
):
    if body.type not in ADMIN_TYPES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Only withdrawal and adjustment can be recorded directly",
        )
    if body.amount == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Amount cannot be 0")
    if body.type == TransactionType.withdrawal and body.amount > 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Withdrawals are debits — amount must be negative",
        )
    if body.type == TransactionType.adjustment and not (body.note or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Adjustments require a note"
        )
    if session.get(User, body.user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    tx = Transaction(**body.model_dump(), created_by=admin.id)
    session.add(tx)
    session.commit()
    session.refresh(tx)
    background_tasks.add_task(run_sheet_sync)  # after commit; never blocks the write
    return _to_read(session, tx)
