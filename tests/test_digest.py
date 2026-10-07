from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from backend.database import engine
from backend.digest import build_digest, send_admin_digest
from backend.models import Chore, Claim, ClaimKind, ClaimStatus, User, UserRole

NOW = datetime(2026, 7, 15, 18, 0, tzinfo=timezone.utc)
SINCE = NOW - timedelta(hours=24)


def seed(session):
    parent = User(email="parent@example.com", name="Parent", role=UserRole.admin)
    kid = User(email="kid@example.com", name="Kid")
    session.add(parent)
    session.add(kid)
    session.commit()
    session.refresh(parent)
    session.refresh(kid)
    chore = Chore(name="Dishes", value=150, created_by=parent.id)
    session.add(chore)
    session.commit()
    session.refresh(chore)
    return parent, kid, chore


def add_claim(session, **kwargs):
    claim = Claim(**kwargs)
    session.add(claim)
    session.commit()
    session.refresh(claim)
    return claim


def test_quiet_day_returns_none():
    with Session(engine) as session:
        seed(session)
        assert build_digest(session, since=SINCE, now=NOW) is None


def test_digest_sections_and_edited_value_flag():
    with Session(engine) as session:
        parent, kid, chore = seed(session)
        # Pending, submitted within the window.
        add_claim(
            session,
            chore_id=chore.id,
            user_id=kid.id,
            submitted_by=kid.id,
            submitted_at=NOW - timedelta(hours=2),
            original_value=150,
        )
        # Approved within the window at an edited value.
        add_claim(
            session,
            kind=ClaimKind.adhoc,
            adhoc_name="Wash car",
            user_id=kid.id,
            submitted_by=parent.id,
            submitted_at=NOW - timedelta(hours=5),
            original_value=300,
            status=ClaimStatus.approved,
            approved_value=200,
            resolved_by=parent.id,
            resolved_at=NOW - timedelta(hours=4),
            resolution_note="only half washed",
        )
        # Rejected within the window.
        add_claim(
            session,
            chore_id=chore.id,
            user_id=kid.id,
            submitted_by=kid.id,
            submitted_at=NOW - timedelta(hours=8),
            original_value=150,
            status=ClaimStatus.rejected,
            resolved_by=parent.id,
            resolved_at=NOW - timedelta(hours=7),
        )
        # Old resolved claim — outside the window, must not appear as activity.
        add_claim(
            session,
            chore_id=chore.id,
            user_id=kid.id,
            submitted_by=kid.id,
            submitted_at=NOW - timedelta(days=3),
            original_value=150,
            status=ClaimStatus.approved,
            approved_value=150,
            resolved_by=parent.id,
            resolved_at=NOW - timedelta(days=3),
        )

        body = build_digest(session, since=SINCE, now=NOW)
        assert "PENDING APPROVAL (1)" in body
        assert "Kid: Dishes ($1.50)" in body
        assert "SUBMITTED IN THE LAST 24H (3)" in body
        assert "lodged by Parent" in body
        assert "RESOLVED IN THE LAST 24H (2)" in body
        assert "Wash car approved by Parent at $2.00 (claimed $3.00)" in body
        assert 'note: "only half washed"' in body
        assert "Dishes rejected by Parent" in body
        # The 3-day-old approval appears in no section.
        assert body.count("approved by") == 1


def test_send_admin_digest_targets_active_admins_only(monkeypatch):
    sent = {}
    monkeypatch.setattr(
        "backend.digest.send_email",
        lambda to, subject, body: sent.update(to=to, subject=subject, body=body),
    )
    with Session(engine) as session:
        parent, kid, chore = seed(session)
        retired = User(
            email="retired@example.com", role=UserRole.admin, is_active=False
        )
        session.add(retired)
        session.commit()
        assert send_admin_digest(session, now=NOW) is False  # quiet — no email
        assert sent == {}

        add_claim(
            session,
            chore_id=chore.id,
            user_id=kid.id,
            submitted_by=kid.id,
            submitted_at=NOW - timedelta(hours=1),
            original_value=150,
        )
        assert send_admin_digest(session, now=NOW) is True
        assert sent["to"] == ["parent@example.com"]  # kid + inactive admin excluded
        assert "awaiting approval" in sent["subject"]
        assert "Dishes" in sent["body"]
