"""One-off importer for the previous chore app's plain-text export
(see backend/legacy_import.py for the parser).

Dry-run by default — prints exactly what would be created and does not
touch the database. Pass --commit to actually write.

Imports every "earned" entry as an approved ad-hoc claim (kind=adhoc,
no chore_id) plus its matching claim_payout transaction — ad-hoc so the
import never creates or modifies real Chore rows / the live chores
list. "Expired" entries are skipped (nothing was earned). "Incomplete"
entries (a name with no value or status at all) are always skipped and
reported — never guessed at.

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

Idempotent: each imported claim's original_note is tagged
"[legacy-import:YYYY-MM-DD:N]"; re-running (even with --commit) skips
any entry whose tag already exists, so a partial run or accidental
re-run can't double-credit.

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
from datetime import datetime, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlmodel import Session, select  # noqa: E402

from backend.database import engine  # noqa: E402
from backend.legacy_import import parse_legacy_export  # noqa: E402
from backend.models import Claim, ClaimKind, ClaimStatus, Transaction, TransactionType, User  # noqa: E402

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
    parser.add_argument("--commit", action="store_true", help="actually write to the database (default: dry run)")
    args = parser.parse_args()

    default_hour, default_minute = (int(x) for x in args.default_time.split(":"))
    name_map = parse_name_map(args.name_map)

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

    user_email = (args.user_email or PLACEHOLDER_EMAIL).lower()
    admin_email = (args.admin_email or user_email).lower()
    creatable = {user_email} if user_email == PLACEHOLDER_EMAIL else set()

    with Session(engine) as session:

        def find_user(email: str) -> User | None:
            return session.exec(select(User).where(User.email == email)).first()

        # Read-only pass: figure out what WOULD happen without writing anything,
        # so a dry run really does touch nothing in the database.
        report_cache: dict[str, str] = {}  # email -> display label

        def check_email(email: str) -> None:
            if email in report_cache:
                return
            exists = find_user(email) is not None
            if not exists and email not in creatable:
                raise SystemExit(f"No user with email {email!r} — invite them in the app first.")
            report_cache[email] = email if exists else f"{email} (will be created)"

        check_email(admin_email)

        planned = []
        for index, entry in enumerate(earned):
            target_email = name_map.get(entry.note, user_email)
            check_email(target_email)
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

        admin = get_or_create_user(admin_email)
        for entry, target_email, timestamp, tag, _ in to_create:
            target = get_or_create_user(target_email)
            claim = Claim(
                kind=ClaimKind.adhoc,
                adhoc_name=entry.chore_name,
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
        print(f"\nCommitted {len(to_create)} claim(s) + transaction(s).")


if __name__ == "__main__":
    main()
