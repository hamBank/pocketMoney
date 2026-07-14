"""Ledger helpers. The transaction table is append-only: balances are
always computed as SUM(amount), never stored (SPEC.md)."""

from sqlalchemy import func
from sqlmodel import Session, select

from .models import Transaction, User, UserRead


def balance_for_user(session: Session, user_id: int) -> int:
    return session.exec(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user_id
        )
    ).one()


def user_read(session: Session, user: User) -> UserRead:
    read = UserRead.model_validate(user)
    read.balance = balance_for_user(session, user.id)
    return read
