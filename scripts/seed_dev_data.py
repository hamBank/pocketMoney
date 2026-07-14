"""Local dev fixtures (idempotent — safe to re-run):

    AUTH_ENABLED=false python scripts/seed_dev_data.py

Creates the dev admin, two kids, chores in all three claim modes, a
pending claim, an approved claim with its payout, and a starting
adjustment — enough to see every screen populated.
"""

import pathlib
import sys
from datetime import timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from backend.database import engine  # noqa: E402
from backend.models import (  # noqa: E402
    Chore,
    Claim,
    ClaimMode,
    ClaimStatus,
    ScheduleKind,
    Transaction,
    TransactionType,
    User,
    UserRole,
    utcnow,
)


def get_or_create(session, model, defaults=None, **lookup):
    row = session.exec(select(model).filter_by(**lookup)).first()
    if row:
        return row, False
    row = model(**lookup, **(defaults or {}))
    session.add(row)
    session.commit()
    session.refresh(row)
    return row, True


def main() -> None:
    with Session(engine) as session:
        admin, _ = get_or_create(
            session,
            User,
            email="dev@localhost",
            defaults=dict(name="Dev Admin", role=UserRole.admin, google_sub="dev"),
        )
        alice, _ = get_or_create(
            session,
            User,
            email="alice@example.com",
            defaults=dict(name="Alice", weekly_allowance=500),
        )
        bob, _ = get_or_create(
            session,
            User,
            email="bob@example.com",
            defaults=dict(name="Bob", weekly_allowance=300),
        )

        dishes, _ = get_or_create(
            session,
            Chore,
            name="Empty the dishwasher",
            defaults=dict(value=150, schedule=ScheduleKind.daily, created_by=admin.id),
        )
        get_or_create(
            session,
            Chore,
            name="Bins out",
            defaults=dict(
                value=200,
                schedule=ScheduleKind.weekly,
                schedule_config={"weekdays": [0]},
                claim_mode=ClaimMode.shared,
                created_by=admin.id,
            ),
        )
        get_or_create(
            session,
            Chore,
            name="Feed the dog",
            defaults=dict(
                value=50,
                claim_mode=ClaimMode.open,
                cooldown_minutes=5,
                created_by=admin.id,
            ),
        )
        get_or_create(
            session,
            Chore,
            name="Vacuum upstairs",
            defaults=dict(
                value=300,
                schedule=ScheduleKind.monthly,
                schedule_config={"day_of_month": 1},
                assignee_ids=[alice.id],
                created_by=admin.id,
            ),
        )

        if not session.exec(select(Claim)).first():
            now = utcnow()
            # Alice has a pending claim from earlier today.
            session.add(
                Claim(
                    chore_id=dishes.id,
                    user_id=alice.id,
                    submitted_by=alice.id,
                    submitted_at=now - timedelta(hours=2),
                    original_value=dishes.value,
                    original_note="before school",
                )
            )
            # Bob got one approved yesterday — with the matching payout.
            approved = Claim(
                chore_id=dishes.id,
                user_id=bob.id,
                submitted_by=bob.id,
                submitted_at=now - timedelta(days=1, hours=3),
                original_value=dishes.value,
                status=ClaimStatus.approved,
                approved_value=dishes.value,
                resolved_by=admin.id,
                resolved_at=now - timedelta(days=1),
            )
            session.add(approved)
            session.flush()
            session.add(
                Transaction(
                    user_id=bob.id,
                    claim_id=approved.id,
                    type=TransactionType.claim_payout,
                    amount=approved.approved_value,
                    created_by=admin.id,
                )
            )
            # Starting balances.
            for kid in (alice, bob):
                session.add(
                    Transaction(
                        user_id=kid.id,
                        type=TransactionType.adjustment,
                        amount=1000,
                        note="starting balance",
                        created_by=admin.id,
                    )
                )
            session.commit()

    print("seeded dev data (users: dev@localhost, Alice, Bob)")


if __name__ == "__main__":
    main()
