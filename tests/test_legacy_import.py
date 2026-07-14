from datetime import date, datetime

import pytest

from backend.legacy_import import parse_legacy_export

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
