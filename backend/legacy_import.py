"""Parses the plain-text chore/claim export format from the previous
family chore app (a day-by-day list copy-pasted from its UI) into
structured entries ready to import as historical claims.

Pure text -> data parsing, no DB access — see scripts/import_legacy_claims.py
for the importer that turns these into Claim/Transaction rows.

Expected format, one block per day:

    MONDAY, MARCH 23, 2026
    <blank line>
    <chore name>
    [(*attributed-to note)]
    [+$X.XX *]
    [Checked
    @H:MMAM/PM]
    <blank line>
    ... more entries ...
    <blank line>
    TUESDAY, MARCH 24, 2026
    ...

A day header may end with " (Today)"; that suffix is ignored. Within a
day, each entry is a name line optionally followed by an
"(*attributed-to)" note, then either "Expired" + a time, a "+$X.XX *"
value (optionally followed by "Checked" + a time), or nothing at all
(an incomplete/malformed entry — flagged, not guessed at).
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

MONTHS = {
    "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
    "APRIL": 4,
    "MAY": 5,
    "JUNE": 6,
    "JULY": 7,
    "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DECEMBER": 12,
}
WEEKDAYS = (
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
)

DAY_HEADER_RE = re.compile(
    r"^(?:" + "|".join(WEEKDAYS) + r"),\s*([A-Z]+)\s+(\d{1,2}),\s*(\d{4})"
    r"(?:\s*\(Today\))?\s*$"
)
VALUE_RE = re.compile(r"^\+\$(\d+(?:\.\d{1,2})?)\s*\*?\s*$")
TIME_RE = re.compile(r"^@(\d{1,2}):(\d{2})(AM|PM)$", re.IGNORECASE)
NOTE_RE = re.compile(r"^\(\*(.+)\)$")


@dataclass(frozen=True)
class LegacyEntry:
    date: date
    chore_name: str
    status: str  # "earned" | "expired" | "incomplete"
    value_cents: int | None  # None unless status == "earned"
    # Set only when an explicit "Checked @time" was present. Naive local
    # wall-clock time, exactly as the old app showed it — see local_to_utc.
    checked_at: datetime | None
    note: str | None  # e.g. "Zinnia" from an "(*Zinnia)" annotation
    raw: str  # original block text, for diagnosing "incomplete" entries


def _parse_time(day: date, line: str) -> datetime:
    match = TIME_RE.match(line)
    if not match:
        raise ValueError(f"expected a time line like '@7:29PM', got {line!r}")
    hour, minute, meridiem = int(match[1]), int(match[2]), match[3].upper()
    if hour == 12:
        hour = 0
    if meridiem == "PM":
        hour += 12
    return datetime(day.year, day.month, day.day, hour, minute)


def local_to_utc(wall_clock: datetime, tz: ZoneInfo) -> datetime:
    """The export's naive times are the family's local wall clock (copied
    from the old app's UI); the DB stores UTC-aware datetimes only."""
    return wall_clock.replace(tzinfo=tz).astimezone(timezone.utc)


def _parse_entry(day: date, block: str) -> LegacyEntry:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    chore_name = lines[0]
    rest = lines[1:]

    note = None
    if rest and (m := NOTE_RE.match(rest[0])):
        note = m[1]
        rest = rest[1:]

    if not rest:
        return LegacyEntry(day, chore_name, "incomplete", None, None, note, block)

    if rest[0] == "Expired":
        return LegacyEntry(day, chore_name, "expired", None, None, note, block)

    value_match = VALUE_RE.match(rest[0])
    if not value_match:
        raise ValueError(f"unrecognised entry for {chore_name!r} on {day}: {block!r}")
    value_cents = round(float(value_match[1]) * 100)
    rest = rest[1:]

    checked_at = None
    if rest[:1] == ["Checked"]:
        checked_at = _parse_time(day, rest[1])

    return LegacyEntry(day, chore_name, "earned", value_cents, checked_at, note, block)


def parse_legacy_export(text: str) -> list[LegacyEntry]:
    lines = text.splitlines()
    day_starts = [
        (i, DAY_HEADER_RE.match(line.strip()))
        for i, line in enumerate(lines)
        if DAY_HEADER_RE.match(line.strip())
    ]
    if not day_starts:
        raise ValueError("no day headers found (expected e.g. 'MONDAY, MARCH 23, 2026')")

    entries: list[LegacyEntry] = []
    for idx, (start_line, header_match) in enumerate(day_starts):
        end_line = day_starts[idx + 1][0] if idx + 1 < len(day_starts) else len(lines)
        month_name, day_num, year = header_match.groups()
        if month_name not in MONTHS:
            raise ValueError(f"unknown month {month_name!r}")
        day = date(int(year), MONTHS[month_name], int(day_num))

        body = "\n".join(lines[start_line + 1 : end_line])
        for block in re.split(r"\n\s*\n+", body.strip()):
            block = block.strip()
            if block:
                entries.append(_parse_entry(day, block))
    return entries
