"""Weekly allowance: one signed `allowance` transaction per user per ISO
week (SPEC.md). Idempotent — the ISO-week tag in the note is the guard, so
re-runs and late catch-up runs can never double-credit."""

from datetime import datetime

from sqlmodel import Session, select

from .models import Transaction, TransactionType, User, utcnow


def week_tag(now: datetime) -> str:
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def apply_weekly_allowance(session: Session, now: datetime | None = None) -> list[Transaction]:
    """Write this week's allowance rows for every eligible user. Returns
    the transactions created (empty when everyone is already paid)."""
    now = now or utcnow()
    tag = week_tag(now)
    users = session.exec(
        select(User).where(User.weekly_allowance != 0, User.is_active == True)  # noqa: E712
    ).all()
    created: list[Transaction] = []
    for user in users:
        already_paid = session.exec(
            select(Transaction).where(
                Transaction.user_id == user.id,
                Transaction.type == TransactionType.allowance,
                Transaction.note == tag,
            )
        ).first()
        if already_paid:
            continue
        tx = Transaction(
            user_id=user.id,
            type=TransactionType.allowance,
            amount=user.weekly_allowance,
            note=tag,
            created_by=None,  # system row
        )
        session.add(tx)
        created.append(tx)
    session.commit()
    return created
