from datetime import datetime

import pytest

from backend.models import Chore, ClaimMode, ScheduleKind
from backend.schedule import ClaimRecord, is_claimable, period_start, validate_schedule

# A Wednesday, mid-afternoon.
NOW = datetime(2026, 7, 15, 15, 30)


def chore(**overrides):
    defaults = dict(
        id=1,
        name="Dishes",
        value=100,
        schedule=ScheduleKind.daily,
        claim_mode=ClaimMode.per_user,
        created_by=1,
    )
    defaults.update(overrides)
    return Chore(**defaults)


def claim(user_id=1, submitted_at=None, status="pending"):
    return ClaimRecord(
        user_id=user_id, submitted_at=submitted_at or NOW, status=status
    )


# --- period_start -----------------------------------------------------------


def test_daily_period_starts_at_midnight():
    assert period_start(chore(), NOW) == datetime(2026, 7, 15)


def test_weekly_period_starts_on_most_recent_scheduled_weekday():
    c = chore(schedule=ScheduleKind.weekly, schedule_config={"weekdays": [0]})  # Mon
    assert period_start(c, NOW) == datetime(2026, 7, 13)  # Monday this week


def test_weekly_period_on_the_scheduled_day_is_that_day():
    c = chore(schedule=ScheduleKind.weekly, schedule_config={"weekdays": [2]})  # Wed
    assert period_start(c, NOW) == datetime(2026, 7, 15)


def test_monthly_period_this_month():
    c = chore(schedule=ScheduleKind.monthly, schedule_config={"day_of_month": 1})
    assert period_start(c, NOW) == datetime(2026, 7, 1)


def test_monthly_period_rolls_back_to_previous_month():
    c = chore(schedule=ScheduleKind.monthly, schedule_config={"day_of_month": 20})
    assert period_start(c, NOW) == datetime(2026, 6, 20)


def test_monthly_day_clamps_to_short_months():
    c = chore(schedule=ScheduleKind.monthly, schedule_config={"day_of_month": 31})
    # 2026-07-15: anchor day 31 of June clamps to June 30.
    assert period_start(c, NOW) == datetime(2026, 6, 30)


def test_january_rollback_crosses_year():
    c = chore(schedule=ScheduleKind.monthly, schedule_config={"day_of_month": 25})
    assert period_start(c, datetime(2026, 1, 10)) == datetime(2025, 12, 25)


def test_unscheduled_has_no_period():
    assert period_start(chore(schedule=ScheduleKind.none), NOW) is None


def test_aware_datetime_is_normalised():
    from datetime import timezone

    aware = datetime(2026, 7, 15, 15, 30, tzinfo=timezone.utc)
    assert period_start(chore(), aware) == datetime(2026, 7, 15)


# --- is_claimable: per_user -------------------------------------------------


def test_per_user_fresh_chore_is_claimable():
    assert is_claimable(chore(), 1, [], NOW)


def test_per_user_own_claim_today_blocks():
    c = claim(user_id=1, submitted_at=datetime(2026, 7, 15, 8))
    assert not is_claimable(chore(), 1, [c], NOW)


def test_per_user_other_users_claim_does_not_block():
    c = claim(user_id=2, submitted_at=datetime(2026, 7, 15, 8))
    assert is_claimable(chore(), 1, [c], NOW)


def test_per_user_yesterdays_claim_does_not_block():
    c = claim(user_id=1, submitted_at=datetime(2026, 7, 14, 8), status="approved")
    assert is_claimable(chore(), 1, [c], NOW)


def test_rejected_and_cancelled_claims_free_the_slot():
    claims = [
        claim(user_id=1, submitted_at=datetime(2026, 7, 15, 8), status="rejected"),
        claim(user_id=1, submitted_at=datetime(2026, 7, 15, 9), status="cancelled"),
    ]
    assert is_claimable(chore(), 1, claims, NOW)


def test_weekly_claim_midweek_blocks_rest_of_period():
    c = chore(schedule=ScheduleKind.weekly, schedule_config={"weekdays": [0]})
    tuesday_claim = claim(user_id=1, submitted_at=datetime(2026, 7, 14, 9), status="approved")
    assert not is_claimable(c, 1, [tuesday_claim], NOW)


def test_weekly_claim_before_period_does_not_block():
    c = chore(schedule=ScheduleKind.weekly, schedule_config={"weekdays": [0]})
    sunday_claim = claim(user_id=1, submitted_at=datetime(2026, 7, 12, 9), status="approved")
    assert is_claimable(c, 1, [sunday_claim], NOW)


# --- is_claimable: shared ---------------------------------------------------


def test_shared_anyones_claim_blocks_everyone():
    c = chore(claim_mode=ClaimMode.shared)
    other = claim(user_id=2, submitted_at=datetime(2026, 7, 15, 8))
    assert not is_claimable(c, 1, [other], NOW)


def test_shared_new_period_frees_the_chore():
    c = chore(claim_mode=ClaimMode.shared)
    yesterday = claim(user_id=2, submitted_at=datetime(2026, 7, 14, 8), status="approved")
    assert is_claimable(c, 1, [yesterday], NOW)


# --- is_claimable: open -----------------------------------------------------


def test_open_blocks_within_cooldown():
    c = chore(claim_mode=ClaimMode.open, cooldown_minutes=5)
    recent = claim(user_id=2, submitted_at=datetime(2026, 7, 15, 15, 28))
    assert not is_claimable(c, 1, [recent], NOW)


def test_open_frees_after_cooldown():
    c = chore(claim_mode=ClaimMode.open, cooldown_minutes=5)
    older = claim(user_id=2, submitted_at=datetime(2026, 7, 15, 15, 20))
    assert is_claimable(c, 1, [older], NOW)


def test_open_same_user_can_reclaim_after_cooldown():
    c = chore(claim_mode=ClaimMode.open, cooldown_minutes=5)
    own = claim(user_id=1, submitted_at=datetime(2026, 7, 15, 15, 20), status="approved")
    assert is_claimable(c, 1, [own], NOW)


def test_open_recent_rejected_claim_does_not_block():
    c = chore(claim_mode=ClaimMode.open, cooldown_minutes=5)
    rejected = claim(user_id=2, submitted_at=datetime(2026, 7, 15, 15, 29), status="rejected")
    assert is_claimable(c, 1, [rejected], NOW)


# --- is_claimable: unscheduled ----------------------------------------------


def test_unscheduled_approved_claim_does_not_block():
    c = chore(schedule=ScheduleKind.none)
    done = claim(user_id=1, submitted_at=datetime(2026, 7, 15, 8), status="approved")
    assert is_claimable(c, 1, [done], NOW)


def test_unscheduled_pending_claim_blocks():
    c = chore(schedule=ScheduleKind.none)
    pending = claim(user_id=1, submitted_at=datetime(2026, 7, 15, 8))
    assert not is_claimable(c, 1, [pending], NOW)


def test_unscheduled_shared_pending_by_other_blocks():
    c = chore(schedule=ScheduleKind.none, claim_mode=ClaimMode.shared)
    pending = claim(user_id=2, submitted_at=datetime(2026, 7, 15, 8))
    assert not is_claimable(c, 1, [pending], NOW)


# --- gates -------------------------------------------------------------------


def test_inactive_chore_is_never_claimable():
    assert not is_claimable(chore(is_active=False), 1, [], NOW)


def test_assignee_restriction():
    c = chore(assignee_ids=[2, 3])
    assert not is_claimable(c, 1, [], NOW)
    assert is_claimable(c, 2, [], NOW)


# --- validate_schedule -------------------------------------------------------


def test_validate_weekly_requires_weekdays():
    with pytest.raises(ValueError):
        validate_schedule(ScheduleKind.weekly, None)
    with pytest.raises(ValueError):
        validate_schedule(ScheduleKind.weekly, {"weekdays": []})
    with pytest.raises(ValueError):
        validate_schedule(ScheduleKind.weekly, {"weekdays": [7]})
    validate_schedule(ScheduleKind.weekly, {"weekdays": [0, 5]})


def test_validate_monthly_requires_day():
    with pytest.raises(ValueError):
        validate_schedule(ScheduleKind.monthly, {})
    with pytest.raises(ValueError):
        validate_schedule(ScheduleKind.monthly, {"day_of_month": 0})
    validate_schedule(ScheduleKind.monthly, {"day_of_month": 31})


def test_validate_rejects_config_on_plain_schedules():
    with pytest.raises(ValueError):
        validate_schedule(ScheduleKind.daily, {"weekdays": [0]})
    validate_schedule(ScheduleKind.daily, None)
    validate_schedule(ScheduleKind.none, None)
