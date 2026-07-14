import re
from datetime import datetime

from sqlmodel import Session

from backend.allowance import apply_weekly_allowance, week_tag
from backend.database import engine
from backend.ledger import balance_for_user
from backend.models import User

MONDAY = datetime(2026, 7, 13, 6, 0)  # Monday morning
NEXT_MONDAY = datetime(2026, 7, 20, 6, 0)


def make_user(session, email, allowance=0, active=True):
    user = User(email=email, weekly_allowance=allowance, is_active=active)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def test_week_tag_format():
    assert re.fullmatch(r"2026-W\d{2}", week_tag(MONDAY))
    assert week_tag(MONDAY) == week_tag(datetime(2026, 7, 16))  # same ISO week
    assert week_tag(MONDAY) != week_tag(NEXT_MONDAY)


def test_allowance_applies_once_per_week_and_supports_deductions():
    with Session(engine) as session:
        kid = make_user(session, "kid@example.com", allowance=500)
        teen = make_user(session, "teen@example.com", allowance=-200)
        make_user(session, "none@example.com", allowance=0)
        make_user(session, "left@example.com", allowance=300, active=False)

        created = apply_weekly_allowance(session, MONDAY)
        assert len(created) == 2  # zero-allowance and inactive users skipped
        assert balance_for_user(session, kid.id) == 500
        assert balance_for_user(session, teen.id) == -200
        assert all(tx.created_by is None for tx in created)  # system rows
        assert all(tx.note == week_tag(MONDAY) for tx in created)

        # Re-run same day and later the same week: no double credit.
        assert apply_weekly_allowance(session, MONDAY) == []
        assert apply_weekly_allowance(session, datetime(2026, 7, 16, 9)) == []
        assert balance_for_user(session, kid.id) == 500

        # Next week pays again.
        created = apply_weekly_allowance(session, NEXT_MONDAY)
        assert len(created) == 2
        assert balance_for_user(session, kid.id) == 1000


def test_allowance_change_affects_future_weeks_only():
    with Session(engine) as session:
        kid = make_user(session, "kid@example.com", allowance=500)
        apply_weekly_allowance(session, MONDAY)
        kid.weekly_allowance = 700
        session.add(kid)
        session.commit()
        # Same week: already paid at the old rate, nothing more happens.
        assert apply_weekly_allowance(session, MONDAY) == []
        assert balance_for_user(session, kid.id) == 500
        # New week: new rate.
        apply_weekly_allowance(session, NEXT_MONDAY)
        assert balance_for_user(session, kid.id) == 1200
