"""Chore recurrence and claimability.

Pure functions with no DB access: claim history is passed in as lightweight
`ClaimRecord`s, so every claim-mode edge case is unit-testable in isolation.
Claimability is computed from history, never stored (see DATA_MODEL.md).

Day boundaries are UTC for now; a family-timezone setting can shift them
later without changing any callers.
"""

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import Chore, ClaimMode, ScheduleKind

# Statuses that consume a claim slot; rejected/cancelled free it (SPEC.md).
BLOCKING_STATUSES = ("pending", "approved")


@dataclass(frozen=True)
class ClaimRecord:
    user_id: int
    submitted_at: datetime
    status: str


def validate_schedule(kind: ScheduleKind, config: dict | None) -> None:
    """Raise ValueError when schedule_config doesn't match the schedule kind."""
    if kind == ScheduleKind.weekly:
        weekdays = (config or {}).get("weekdays")
        if (
            not isinstance(weekdays, list)
            or not weekdays
            or not all(isinstance(d, int) and 0 <= d <= 6 for d in weekdays)
        ):
            raise ValueError(
                'weekly schedule needs schedule_config {"weekdays": [0-6, ...]} (Mon=0)'
            )
    elif kind == ScheduleKind.monthly:
        day = (config or {}).get("day_of_month")
        if not isinstance(day, int) or not 1 <= day <= 31:
            raise ValueError(
                'monthly schedule needs schedule_config {"day_of_month": 1-31}'
            )
    elif config:
        raise ValueError(f"{kind.value} schedule takes no schedule_config")


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _monthly_anchor(year: int, month: int, day_of_month: int) -> datetime:
    # Day 31 in a 30-day month clamps to the month's last day.
    day = min(day_of_month, calendar.monthrange(year, month)[1])
    return datetime(year, month, day)


def period_start(chore: Chore, now: datetime) -> datetime | None:
    """Start of the chore's current schedule period; None when unscheduled."""
    now = _naive(now)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if chore.schedule == ScheduleKind.none:
        return None
    if chore.schedule == ScheduleKind.daily:
        return midnight
    if chore.schedule == ScheduleKind.weekly:
        weekdays = set(chore.schedule_config["weekdays"])
        for offset in range(7):
            day = midnight - timedelta(days=offset)
            if day.weekday() in weekdays:
                return day
    if chore.schedule == ScheduleKind.monthly:
        target = chore.schedule_config["day_of_month"]
        anchor = _monthly_anchor(midnight.year, midnight.month, target)
        if anchor > midnight:
            year, month = (
                (midnight.year - 1, 12)
                if midnight.month == 1
                else (midnight.year, midnight.month - 1)
            )
            anchor = _monthly_anchor(year, month, target)
        return anchor
    raise ValueError(f"unknown schedule kind: {chore.schedule}")


def is_claimable(
    chore: Chore, user_id: int, claims: list[ClaimRecord], now: datetime
) -> bool:
    """Can user_id claim this chore right now, given its claim history?"""
    if not chore.is_active:
        return False
    if chore.assignee_ids and user_id not in chore.assignee_ids:
        return False
    now = _naive(now)
    blocking = [c for c in claims if c.status in BLOCKING_STATUSES]

    if chore.claim_mode == ClaimMode.open:
        window = now - timedelta(minutes=chore.cooldown_minutes)
        return not any(_naive(c.submitted_at) > window for c in blocking)

    if chore.claim_mode == ClaimMode.per_user:
        blocking = [c for c in blocking if c.user_id == user_id]

    start = period_start(chore, now)
    if start is None:
        # Unscheduled chores are always available; only an in-flight
        # (pending) claim blocks re-submission.
        return not any(c.status == "pending" for c in blocking)
    return not any(_naive(c.submitted_at) >= start for c in blocking)
