import importlib.util
import pathlib
import sys
from datetime import date, datetime, timezone

import pytest
from sqlmodel import Session, select

from backend.database import engine
from backend.legacy_import import parse_legacy_export
from backend.models import Chore, Claim, ClaimStatus, Transaction, TransactionType

# Fictional data mirroring the real export's shape (not the family's actual
# chore list — synthetic fixtures so parsing tests don't hardcode real data).


def test_earned_entry_without_checked():
    text = """
MONDAY, MARCH 23, 2026

Sweep porch
+$1.00 *
"""
    entries = parse_legacy_export(text)
    assert len(entries) == 1
    e = entries[0]
    assert e.date == date(2026, 3, 23)
    assert e.chore_name == "Sweep porch"
    assert e.status == "earned"
    assert e.value_cents == 100
    assert e.checked_at is None
    assert e.note is None


def test_earned_entry_with_note_and_checked_time():
    text = """
MONDAY, MARCH 23, 2026

Water plants
(*Robin)
+$0.35 *
Checked
@7:29PM
"""
    entries = parse_legacy_export(text)
    e = entries[0]
    assert e.note == "Robin"
    assert e.value_cents == 35
    assert e.checked_at == datetime(2026, 3, 23, 19, 29)


def test_checked_time_am_and_noon_boundaries():
    text = """
MONDAY, MARCH 23, 2026

Feed cat
+$0.50 *
Checked
@12:05AM

Walk dog
+$0.50 *
Checked
@12:05PM
"""
    entries = parse_legacy_export(text)
    assert entries[0].checked_at == datetime(2026, 3, 23, 0, 5)
    assert entries[1].checked_at == datetime(2026, 3, 23, 12, 5)


def test_expired_entry_has_no_value():
    text = """
MONDAY, MARCH 23, 2026

Make Coffee
Expired
@12:00AM
"""
    e = parse_legacy_export(text)[0]
    assert e.status == "expired"
    assert e.value_cents is None
    assert e.checked_at is None


def test_incomplete_entry_with_only_a_name_is_flagged_not_guessed():
    text = """
MONDAY, MARCH 23, 2026

Sweep porch
+$1.00 *

Mystery item

Water plants
+$0.35 *
"""
    entries = parse_legacy_export(text)
    assert [e.chore_name for e in entries] == ["Sweep porch", "Mystery item", "Water plants"]
    mystery = entries[1]
    assert mystery.status == "incomplete"
    assert mystery.value_cents is None


def test_duplicate_same_day_same_name_both_kept():
    text = """
SATURDAY, MARCH 28, 2026

Wash car
+$4.00 *

Wash car
+$4.00 *
"""
    entries = parse_legacy_export(text)
    assert len(entries) == 2
    assert all(e.chore_name == "Wash car" and e.value_cents == 400 for e in entries)


def test_today_suffix_is_ignored():
    text = """
SUNDAY, MARCH 29, 2026 (Today)

Sweep porch
+$1.00 *
"""
    e = parse_legacy_export(text)[0]
    assert e.date == date(2026, 3, 29)


def test_multiple_days_split_correctly():
    text = """
MONDAY, MARCH 23, 2026

Sweep porch
+$1.00 *


TUESDAY, MARCH 24, 2026

Sweep porch
+$1.00 *

Water plants
+$0.35 *
"""
    entries = parse_legacy_export(text)
    by_date = {}
    for e in entries:
        by_date.setdefault(e.date, []).append(e.chore_name)
    assert by_date[date(2026, 3, 23)] == ["Sweep porch"]
    assert by_date[date(2026, 3, 24)] == ["Sweep porch", "Water plants"]


def test_no_day_headers_raises():
    with pytest.raises(ValueError, match="no day headers"):
        parse_legacy_export("just some text\nwith no headers")


def test_unrecognised_entry_shape_raises():
    text = """
MONDAY, MARCH 23, 2026

Sweep porch
some unexpected line
"""
    with pytest.raises(ValueError, match="unrecognised entry"):
        parse_legacy_export(text)


def test_local_to_utc_converts_family_wall_clock():
    from zoneinfo import ZoneInfo

    from backend.legacy_import import local_to_utc

    tz = ZoneInfo("Australia/Canberra")
    # AEDT (+11) before DST ends on 5 April 2026, AEST (+10) after.
    assert local_to_utc(datetime(2026, 3, 23, 19, 29), tz) == datetime(
        2026, 3, 23, 8, 29, tzinfo=timezone.utc
    )
    assert local_to_utc(datetime(2026, 6, 1, 7, 0), tz) == datetime(
        2026, 5, 31, 21, 0, tzinfo=timezone.utc
    )


# --- The importer script's --commit path, against the real test DB ---

EXPORT = """
MONDAY, MARCH 23, 2026

Water plants
(*Robin)
+$0.35 *
Checked
@7:29PM

Sweep porch
+$1.00 *

Make Coffee
Expired
@12:00AM
"""


def _run_importer(monkeypatch, tmp_path, *extra):
    script = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "import_legacy_claims.py"
    spec = importlib.util.spec_from_file_location("import_legacy_claims", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    export = tmp_path / "export.txt"
    export.write_text(EXPORT)
    monkeypatch.setattr(sys, "argv", ["import_legacy_claims.py", "--input", str(export), *extra])
    module.main()


def _utc(dt):
    # SQLite drops tzinfo on the way back out; everything stored is UTC.
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def test_importer_commit_writes_utc_claims_and_payouts(monkeypatch, tmp_path):
    _run_importer(monkeypatch, tmp_path, "--commit")

    with Session(engine) as session:
        claims = session.exec(select(Claim).order_by(Claim.id)).all()
        txs = session.exec(select(Transaction).order_by(Transaction.id)).all()
        chores = {c.id: c.name for c in session.exec(select(Chore)).all()}

    assert [(chores[c.chore_id], c.original_value, c.status) for c in claims] == [
        ("Water plants", 35, ClaimStatus.approved),
        ("Sweep porch", 100, ClaimStatus.approved),
    ]
    # 7:29 PM and the default noon, Canberra daylight time (+11), in UTC.
    water, porch = claims
    assert _utc(water.submitted_at) == datetime(2026, 3, 23, 8, 29, tzinfo=timezone.utc)
    assert _utc(water.resolved_at) == _utc(water.submitted_at)
    assert _utc(porch.submitted_at) == datetime(2026, 3, 23, 1, 0, tzinfo=timezone.utc)
    assert [(t.claim_id, t.type, t.amount, _utc(t.created_at)) for t in txs] == [
        (water.id, TransactionType.claim_payout, 35, _utc(water.submitted_at)),
        (porch.id, TransactionType.claim_payout, 100, _utc(porch.submitted_at)),
    ]


def test_importer_commit_rerun_and_dry_run_write_nothing_new(monkeypatch, tmp_path):
    _run_importer(monkeypatch, tmp_path)  # dry run
    with Session(engine) as session:
        assert session.exec(select(Claim)).all() == []

    _run_importer(monkeypatch, tmp_path, "--commit")
    _run_importer(monkeypatch, tmp_path, "--commit")
    with Session(engine) as session:
        assert len(session.exec(select(Claim)).all()) == 2
        assert len(session.exec(select(Transaction)).all()) == 2


def test_importer_timezone_flag(monkeypatch, tmp_path):
    _run_importer(monkeypatch, tmp_path, "--commit", "--timezone", "UTC")
    with Session(engine) as session:
        water = session.exec(select(Claim).order_by(Claim.id)).first()
    assert _utc(water.submitted_at) == datetime(2026, 3, 23, 19, 29, tzinfo=timezone.utc)

    with pytest.raises(SystemExit, match="Unknown --timezone"):
        _run_importer(monkeypatch, tmp_path, "--timezone", "Mars/Olympus")
