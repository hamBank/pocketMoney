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

Idempotent: each imported claim's original_note is tagged
"[legacy-import:YYYY-MM-DD:N]"; re-running (even with --commit) skips
any entry whose tag already exists, so a partial run or accidental
re-run can't double-credit.

Usage:
    python scripts/import_legacy_claims.py --input export.txt \\
        --user-email kid@example.com --admin-email parent@example.com \\
        --name-map "Zinnia=other-kid@example.com"

    # after reviewing the dry-run output:
    python scripts/import_legacy_claims.py --input export.txt \\
        --user-email kid@example.com --admin-email parent@example.com \\
        --commit
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
    parser.add_argument("--user-email", required=True, help="default assignee for entries with no name note")
    parser.add_argument("--admin-email", required=True, help="who historically approved these (resolved_by)")
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

    with Session(engine) as session:
        admin = session.exec(select(User).where(User.email == args.admin_email.lower())).first()
        if admin is None:
            raise SystemExit(f"No user with email {args.admin_email!r} — invite them in the app first.")

        user_cache: dict[str, User] = {}

        def resolve_user(email: str) -> User:
            if email not in user_cache:
                found = session.exec(select(User).where(User.email == email)).first()
                if found is None:
                    raise SystemExit(f"No user with email {email!r} — invite them in the app first.")
                user_cache[email] = found
            return user_cache[email]

        planned = []
        for index, entry in enumerate(earned):
            target_email = name_map.get(entry.note, args.user_email.lower())
            target = resolve_user(target_email)
            timestamp = entry.checked_at or datetime.combine(entry.date, time(default_hour, default_minute))
            tag = tag_for(entry, index)
            already_imported = session.exec(
                select(Claim).where(Claim.original_note == tag)
            ).first()
            planned.append((entry, target, timestamp, tag, already_imported))

        to_create = [p for p in planned if p[4] is None]
        already_done = [p for p in planned if p[4] is not None]

        print(f"Parsed: {len(entries)} entries — {len(earned)} earned, "
              f"{len(skipped_expired)} expired (skipped), {len(skipped_incomplete)} incomplete (skipped)")
        if already_done:
            print(f"Already imported previously, skipping: {len(already_done)}")
        print(f"\n{'Date':<12} {'Chore':<20} {'To':<24} {'Amount':>8}  {'Timestamp'}")
        totals: dict[str, int] = {}
        for entry, target, timestamp, tag, _ in to_create:
            print(
                f"{entry.date.isoformat():<12} {entry.chore_name:<20} {target.email:<24} "
                f"${entry.value_cents / 100:>6.2f}  {timestamp.isoformat(timespec='minutes')}"
                + ("  (default time)" if entry.checked_at is None else "")
            )
            totals[target.email] = totals.get(target.email, 0) + entry.value_cents

        print("\nBalance impact:")
        for email, cents in totals.items():
            print(f"  {email}: +${cents / 100:.2f}")

        if not args.commit:
            print(f"\nDry run only — {len(to_create)} claim(s) NOT written. Pass --commit to apply.")
            return

        for entry, target, timestamp, tag, _ in to_create:
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
