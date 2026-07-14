"""Admin daily digest: pending claims + the day's claim activity (SPEC.md).
"The day" is the 24h before `now` — matching the daily cron cadence."""

from datetime import datetime, timedelta

from sqlmodel import Session, select

from .config import settings
from .emails import send_email
from .models import Chore, Claim, ClaimStatus, User, UserRole, utcnow


def _money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{settings.currency_symbol}{abs(cents) / 100:.2f}"


def _label(session: Session, claim: Claim) -> str:
    if claim.chore_id is not None:
        chore = session.get(Chore, claim.chore_id)
        if chore:
            return chore.name
    return claim.adhoc_name or f"claim {claim.id}"


def _user_name(session: Session, user_id: int | None) -> str:
    if user_id is None:
        return "system"
    user = session.get(User, user_id)
    return (user.name or user.email) if user else f"user {user_id}"


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def build_digest(session: Session, since: datetime, now: datetime) -> str | None:
    """The digest body, or None when there is nothing pending AND no
    activity in the window — the caller then sends no email."""
    since, now = _naive(since), _naive(now)
    pending = session.exec(
        select(Claim).where(Claim.status == ClaimStatus.pending).order_by(Claim.submitted_at)
    ).all()
    submitted = session.exec(
        select(Claim).where(Claim.submitted_at >= since).order_by(Claim.submitted_at)
    ).all()
    resolved = [
        c
        for c in session.exec(
            select(Claim)
            .where(Claim.resolved_at != None)  # noqa: E711
            .order_by(Claim.resolved_at)
        ).all()
        if _naive(c.resolved_at) >= since
        and c.status in (ClaimStatus.approved, ClaimStatus.rejected)
    ]
    if not pending and not submitted and not resolved:
        return None

    lines: list[str] = []
    if pending:
        lines.append(f"PENDING APPROVAL ({len(pending)})")
        for claim in pending:
            lines.append(
                f"  - {_user_name(session, claim.user_id)}: {_label(session, claim)}"
                f" ({_money(claim.original_value)})"
                f" — submitted {_naive(claim.submitted_at):%a %d %b %H:%M}"
            )
        lines.append("")

    if submitted:
        lines.append(f"SUBMITTED IN THE LAST 24H ({len(submitted)})")
        for claim in submitted:
            by = ""
            if claim.submitted_by != claim.user_id:
                by = f" (lodged by {_user_name(session, claim.submitted_by)})"
            lines.append(
                f"  - {_user_name(session, claim.user_id)} claimed"
                f" {_label(session, claim)} ({_money(claim.original_value)}){by}"
            )
        lines.append("")

    if resolved:
        lines.append(f"RESOLVED IN THE LAST 24H ({len(resolved)})")
        for claim in resolved:
            who = _user_name(session, claim.user_id)
            resolver = _user_name(session, claim.resolved_by)
            label = _label(session, claim)
            if claim.status == ClaimStatus.approved:
                edited = ""
                if claim.approved_value != claim.original_value:
                    edited = f" (claimed {_money(claim.original_value)})"
                lines.append(
                    f"  - {who}: {label} approved by {resolver}"
                    f" at {_money(claim.approved_value)}{edited}"
                )
            else:
                lines.append(f"  - {who}: {label} rejected by {resolver}")
            if claim.resolution_note:
                lines.append(f'      note: "{claim.resolution_note}"')
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def send_admin_digest(session: Session, now: datetime | None = None) -> bool:
    """Send the digest to every active admin. Returns True when sent."""
    now = now or utcnow()
    body = build_digest(session, since=now - timedelta(hours=24), now=now)
    if body is None:
        return False
    admins = session.exec(
        select(User).where(User.role == UserRole.admin, User.is_active == True)  # noqa: E712
    ).all()
    recipients = [a.email for a in admins if "@" in a.email]
    if not recipients:
        return False
    pending_count = body.count("\n  -", 0, body.find("\n\n")) if body.startswith("PENDING") else 0
    subject = "Pocket Money digest"
    if pending_count:
        subject += f" — {pending_count} claim{'s' if pending_count != 1 else ''} awaiting approval"
    send_email(recipients, subject, body)
    return True
