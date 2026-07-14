"""One-off importer for the previous chore app's plain-text export
(see backend/legacy_import.py for the parser).

Dry-run by default — prints exactly what would be created and does not
touch the database. Pass --commit to actually write.

For every distinct chore name found in an "earned" entry, get-or-creates
a real Chore row (schedule=none, claim_mode=per_user — the same defaults
the "New chore" form uses — so they show up in Manage Chores for you to
review and tune schedules/claim modes/assignees afterward) using the
value from that export. Every "earned" entry then becomes an approved
claim tied to that chore (kind=chore) plus its matching claim_payout
transaction. "Expired" entries are skipped (nothing was earned).
"Incomplete" entries (a name with no value or status at all) are always
skipped and reported — never guessed at. Pass --no-create-chores to
fall back to the old behaviour: ad-hoc claims only (kind=adhoc), no
Chore rows touched at all.

If the same chore name shows a different value on different days, that's
flagged rather than silently picking one — each entry's own value is
still used for its own claim either way; only the *new chore's* value
(which one it's initialized with) is ambiguous in that case.

--user-email and --admin-email are optional. The claim/transaction
user_id is a required foreign key (every dollar has to belong to
somebody — see DATA_MODEL.md), so if you don't want to attribute
entries to a real person yet, omit both and everything is imported
against a single auto-created placeholder user (PLACEHOLDER_EMAIL
below), which also stands in as the historical approver. Once you've
invited real family members, reassign it — e.g.
UPDATE claim SET user_id = <real id> WHERE user_id = <placeholder id>;
UPDATE "transaction" SET user_id = <real id> WHERE user_id = <placeholder id>;
(a one-time direct correction to the bootstrap data — not something the
app's normal claim flow ever needs, since claims are otherwise
immutable and the ledger append-only).

Idempotent: chores are matched/reused by exact name; each imported
claim's original_note is tagged "[legacy-import:YYYY-MM-DD:N]" and
re-running (even with --commit) skips any entry whose tag already
exists, so a partial run or accidental re-run can't double-credit or
duplicate chores.

Usage:
    # no real users yet — everything goes to one placeholder account
    python scripts/import_legacy_claims.py --input export.txt

    # after reviewing the dry-run output:
    python scripts/import_legacy_claims.py --input export.txt --commit

    # once real accounts exist, attribute properly instead:
    python scripts/import_legacy_claims.py --input export.txt \\
        --user-email kid@example.com --admin-email parent@example.com \\
        --name-map "Zinnia=other-kid@example.com" --commit
"""

import argparse
import pathlib
import sys
from collections import defaultdict
from datetime import datetime, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from backend.models import (  # noqa: E402
    Chore,
    ClaimKind,
    ClaimMode,
    ClaimStatus,
    ScheduleKind,
    Claim,
    Transaction,
    TransactionType,
    User,
)
from backend.database import engine  # noqa: E402
from backend.legacy_import import parse_legacy_export  # noqa: E402

PLACEHOLDER_EMAIL = "unassigned@legacy-import.local"


def tag_for(entry, index: int) -> str:
    return f"[legacy-import:{entry.date.isoformat()}:{index}]"


def parse_name_map(pairs: list[str]) -> dict[str, str]:
    mapping = {}
    for pair in pairs:
        name, _, email = pair.partition("=")
        if not email:
            raise SystemExit(f"--name-map expects NAME=email, got {pair!r}")
        mapping[name.strip()] = email.strip().lower()
    return mapping


def representative_values(earned: list) -> dict[str, int]:
    """One value per distinct chore name, for initializing a new Chore.
    Warns (doesn't guess wrong) if a name shows more than one value."""
    values_by_name: dict[str, set[int]] = defaultdict(set)
    for entry in earned:
        values_by_name[entry.chore_name].add(entry.value_cents)
    result = {}
    for name, values in values_by_name.items():
        if len(values) > 1:
            print(
                f"NOTE: {name!r} shows different values across entries {sorted(values)} "
                f"— using the highest for the new chore; each entry keeps its own value."
            )
        result[name] = max(values)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="path to the exported text file")
    parser.add_argument(
        "--user-email",
        default=None,
        help=f"default assignee for entries with no name note "
        f"(default: auto-create/use placeholder {PLACEHOLDER_EMAIL!r})",
    )
    parser.add_argument(
        "--admin-email",
        default=None,
        help="who historically approved these, resolved_by (default: same as --user-email)",
    )
    parser.add_argument(
        "--name-map",
        action="append",
        default=[],
        metavar="NAME=email",
        help='map an "(*Name)" note to a specific user, e.g. Zinnia=kid2@example.com (repeatable)',
    )
    parser.add_argument(
        "--default-time",
        default="12:00",
        help="HH:MM used for entries with no explicit 'Checked @time' (default: noon)",
    )
    parser.add_argument(
        "--no-create-chores",
        action="store_true",
        help="old behaviour: import as ad-hoc claims only, never create/touch Chore rows",
    )
    parser.add_argument("--commit", action="store_true", help="actually write to the database (default: dry run)")
    args = parser.parse_args()

    default_hour, default_minute = (int(x) for x in args.default_time.split(":"))
    name_map = parse_name_map(args.name_map)
    create_chores = not args.no_create_chores

    text = pathlib.Path(args.input).read_text()
    entries = parse_legacy_export(text)

    earned = [e for e in entries if e.status == "earned"]
    skipped_expired = [e for e in entries if e.status == "expired"]
    skipped_incomplete = [e for e in entries if e.status == "incomplete"]

    if skipped_incomplete:
        print("INCOMPLETE entries (no value/status — always skipped, review manually):")
        for e in skipped_incomplete:
            print(f"  {e.date} | {e.chore_name!r}")
        print()

    chore_values = representative_values(earned) if create_chores else {}

    user_email = (args.user_email or PLACEHOLDER_EMAIL).lower()
    admin_email = (args.admin_email or user_email).lower()
    creatable = {user_email} if user_email == PLACEHOLDER_EMAIL else set()

    with Session(engine) as session:

        def find_user(email: str) -> User | None:
            return session.exec(select(User).where(User.email == email)).first()

        def find_chore(name: str) -> Chore | None:
            return session.exec(select(Chore).where(Chore.name == name)).first()

        # Read-only pass: figure out what WOULD happen without writing anything,
        # so a dry run really does touch nothing in the database.
        report_cache: dict[str, str] = {}  # email -> display label
        chore_report_cache: dict[str, str] = {}  # chore name -> display label

        def check_email(email: str) -> None:
            if email in report_cache:
                return
            exists = find_user(email) is not None
            if not exists and email not in creatable:
                raise SystemExit(f"No user with email {email!r} — invite them in the app first.")
            report_cache[email] = email if exists else f"{email} (will be created)"

        def check_chore(name: str) -> None:
            if name in chore_report_cache:
                return
            exists = find_chore(name) is not None
            chore_report_cache[name] = "existing" if exists else "will be created"

        check_email(admin_email)

        planned = []
        for index, entry in enumerate(earned):
            target_email = name_map.get(entry.note, user_email)
            check_email(target_email)
            if create_chores:
                check_chore(entry.chore_name)
            timestamp = entry.checked_at or datetime.combine(entry.date, time(default_hour, default_minute))
            tag = tag_for(entry, index)
            already_imported = session.exec(select(Claim).where(Claim.original_note == tag)).first()
            planned.append((entry, target_email, timestamp, tag, already_imported))

        to_create = [p for p in planned if p[4] is None]
        already_done = [p for p in planned if p[4] is not None]

        print(f"Parsed: {len(entries)} entries — {len(earned)} earned, "
              f"{len(skipped_expired)} expired (skipped), {len(skipped_incomplete)} incomplete (skipped)")
        if already_done:
            print(f"Already imported previously, skipping: {len(already_done)}")

        if create_chores:
            print(f"\nChores ({len(chore_report_cache)} distinct):")
            for name, label in sorted(chore_report_cache.items()):
                print(f"  {name:<20} {label} (value ${chore_values[name] / 100:.2f}, schedule=none, per_user)")

        print(f"\n{'Date':<12} {'Chore':<20} {'To':<32} {'Amount':>8}  {'Timestamp'}")
        totals: dict[str, int] = {}
        for entry, target_email, timestamp, tag, _ in to_create:
            print(
                f"{entry.date.isoformat():<12} {entry.chore_name:<20} {report_cache[target_email]:<32} "
                f"${entry.value_cents / 100:>6.2f}  {timestamp.isoformat(timespec='minutes')}"
                + ("  (default time)" if entry.checked_at is None else "")
            )
            totals[target_email] = totals.get(target_email, 0) + entry.value_cents

        print("\nBalance impact:")
        for email, cents in totals.items():
            print(f"  {report_cache[email]}: +${cents / 100:.2f}")

        if not args.commit:
            print(f"\nDry run only — {len(to_create)} claim(s) NOT written. Pass --commit to apply.")
            return

        # Commit path: resolve for real now (get-or-create), all in one
        # transaction with the claims/transactions below.
        user_cache: dict[str, User] = {}
        chore_cache: dict[str, Chore] = {}

        def get_or_create_user(email: str) -> User:
            if email not in user_cache:
                found = find_user(email)
                if found is None:
                    found = User(email=email, name="Unassigned (legacy import)")
                    session.add(found)
                    session.flush()
                    print(f"Created placeholder user {email!r} (id={found.id}) — reassign later, see script docstring.")
                user_cache[email] = found
            return user_cache[email]

        def get_or_create_chore(name: str, admin_id: int) -> Chore:
            if name not in chore_cache:
                found = find_chore(name)
                if found is None:
                    found = Chore(
                        name=name,
                        value=chore_values[name],
                        schedule=ScheduleKind.none,
                        claim_mode=ClaimMode.per_user,
                        created_by=admin_id,
                    )
                    session.add(found)
                    session.flush()
                    print(f"Created chore {name!r} (id={found.id}, ${chore_values[name] / 100:.2f}) — "
                          f"review schedule/claim mode in Manage Chores.")
                chore_cache[name] = found
            return chore_cache[name]

        admin = get_or_create_user(admin_email)
        for entry, target_email, timestamp, tag, _ in to_create:
            target = get_or_create_user(target_email)
            chore = get_or_create_chore(entry.chore_name, admin.id) if create_chores else None
            claim = Claim(
                kind=ClaimKind.chore if chore else ClaimKind.adhoc,
                chore_id=chore.id if chore else None,
                adhoc_name=None if chore else entry.chore_name,
                user_id=target.id,
                submitted_by=admin.id,
                submitted_at=timestamp,
                original_value=entry.value_cents,
                original_note=tag,
                status=ClaimStatus.approved,
                approved_value=entry.value_cents,
                resolved_by=admin.id,
                resolved_at=timestamp,
            )
            session.add(claim)
            session.flush()
            session.add(
                Transaction(
                    user_id=target.id,
                    claim_id=claim.id,
                    type=TransactionType.claim_payout,
                    amount=entry.value_cents,
                    created_by=admin.id,
                    created_at=timestamp,
                )
            )
        session.commit()
        print(f"\nCommitted {len(to_create)} claim(s) + transaction(s)"
              f"{f' and {len(chore_cache)} chore(s)' if create_chores else ''}.")


if __name__ == "__main__":
    main()
