"""Mirror the transaction ledger into a Google Sheet as a permanent,
append-only record: one tab per child plus a Totals tab (SPEC.md).

The database stays the source of truth. The sheet is its own high-water
mark — each child's tab is read for the highest Tx ID already present and
only newer transactions are appended — so a sync can run any number of
times, recovers by itself after a crash or Google outage, and backfills the
full history on first run. Nothing is ever written back to the transaction
table, which stays append-only.

Runs after every money-changing request (FastAPI background task) and from
cron every 10 minutes (scripts/sync_sheet.py) as a catch-up. A failure here
never blocks or fails a money write.
"""

import fcntl
import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlmodel import Session, or_, select

from .config import settings
from .database import engine
from .models import Chore, Claim, Transaction, TransactionType, User, UserRole, utcnow
from .sheets import GoogleSheetsClient, SheetsError, Tab, a1

log = logging.getLogger(__name__)

USER_KEY = "pmoney_user_id"
TOTALS_KEY = "pmoney_totals"
TOTALS_TITLE = "Totals"

LEDGER_HEADER = [
    "Tx ID",
    "Date",
    "Type",
    "Description",
    "Amount",
    "Balance",
    "Recorded by",
    "Claim ID",
]
LEDGER_CURRENCY_COLUMNS = [4, 5]  # Amount, Balance

TOTALS_HEADER = [
    "Child",
    "Balance (sheet)",
    "Balance (app)",
    "DB check",
    "Earned this week",
    "Spent this month",
    "Last entry",
    "Entries",
]
TOTALS_CURRENCY_COLUMNS = [1, 2, 4, 5]

TYPE_LABELS = {
    TransactionType.claim_payout: "Chore payout",
    TransactionType.penalty: "Penalty",
    TransactionType.withdrawal: "Withdrawal",
    TransactionType.adjustment: "Adjustment",
    TransactionType.allowance: "Allowance",
}


@dataclass
class SyncResult:
    appended: dict[int, int] = field(default_factory=dict)  # user_id → rows
    tabs_created: list[str] = field(default_factory=list)


def is_configured() -> bool:
    return bool(settings.google_sheet_id)


def make_client() -> GoogleSheetsClient:
    return GoogleSheetsClient.from_service_account_file(
        settings.google_sheet_id, settings.google_service_account_file
    )


def _currency_pattern() -> str:
    symbol = '"' + settings.currency_symbol.replace('"', "") + '"'
    return f"{symbol}#,##0.00;-{symbol}#,##0.00"


def _local(dt: datetime, tz: ZoneInfo) -> datetime:
    # SQLite hands back naive datetimes; everything is stored as UTC.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def _dollars(cents: int) -> float:
    return round(cents / 100, 2)


def _text(value: str) -> str:
    """Escape text written with USER_ENTERED so it can't become a formula."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "'") else value


def _name(user: User | None) -> str:
    if user is None:
        return "system"
    return user.name or user.email


def ledger_users(session: Session) -> list[User]:
    """Every child (role user, active or with history), plus anyone else —
    e.g. an admin — who has ledger entries."""
    with_history = select(Transaction.user_id).distinct()
    return session.exec(
        select(User)
        .where(
            or_(
                User.id.in_(with_history),
                (User.role == UserRole.user) & (User.is_active == True),  # noqa: E712
            )
        )
        .order_by(User.id)
    ).all()


def _description(session: Session, tx: Transaction) -> str:
    if tx.claim_id is not None:
        claim = session.get(Claim, tx.claim_id)
        if claim is not None:
            label = claim.adhoc_name or ""
            if claim.chore_id is not None:
                chore = session.get(Chore, claim.chore_id)
                label = chore.name if chore else label
            label = label or f"claim {claim.id}"
            return f"{label} — {claim.resolution_note}" if claim.resolution_note else label
    if tx.type == TransactionType.allowance:
        return f"Weekly allowance {tx.note}" if tx.note else "Weekly allowance"
    return tx.note or ""


def ledger_row(session: Session, tx: Transaction, balance: int, tz: ZoneInfo) -> list:
    return [
        tx.id,
        f"{_local(tx.created_at, tz):%Y-%m-%d %H:%M}",
        TYPE_LABELS.get(tx.type, tx.type.value),
        _description(session, tx),
        _dollars(tx.amount),
        _dollars(balance),
        _name(session.get(User, tx.created_by)) if tx.created_by else "system",
        tx.claim_id if tx.claim_id is not None else "",
    ]


def _last_synced_id(values: list[str]) -> int:
    ids = []
    for value in values:
        try:
            ids.append(int(float(value)))
        except ValueError:
            continue
    return max(ids, default=0)


def _unique_title(wanted: str, user_id: int, taken: set[str]) -> str:
    # Sheets titles: unique (case-insensitive), max 100 chars, no "Totals".
    title = (wanted.strip() or f"user {user_id}")[:90]
    if title.lower() in taken:
        title = f"{title} ({user_id})"
    return title


def _sync_user(
    session: Session, client, user: User, tab: Tab, tz: ZoneInfo
) -> int:
    last_id = _last_synced_id(client.read_column(tab.title))
    new = session.exec(
        select(Transaction)
        .where(Transaction.user_id == user.id, Transaction.id > last_id)
        .order_by(Transaction.id)
    ).all()
    if not new:
        return 0
    balance = session.exec(
        select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user.id, Transaction.id <= last_id
        )
    ).one()
    rows = []
    for tx in new:
        balance += tx.amount
        rows.append(ledger_row(session, tx, balance, tz))
    client.append_rows(tab.title, rows)
    return len(rows)


def totals_rows(
    session: Session, users_tabs: list[tuple[User, Tab]], now: datetime, tz: ZoneInfo
) -> list[list]:
    """Totals tab body (below its header). Sheet balance and entry count are
    formulas over the child's tab, so they always show what the ledger
    holds; "DB check" flags any drift from the app's own balance."""
    local_now = _local(now, tz)
    week_start = (local_now - timedelta(days=local_now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows: list[list] = []
    for index, (user, tab) in enumerate(users_tabs):
        row_number = index + 2  # header is row 1
        txs = session.exec(select(Transaction).where(Transaction.user_id == user.id)).all()
        balance = sum(tx.amount for tx in txs)
        earned = sum(
            tx.amount for tx in txs if tx.amount > 0 and _local(tx.created_at, tz) >= week_start
        )
        spent = -sum(
            tx.amount
            for tx in txs
            if tx.type == TransactionType.withdrawal and _local(tx.created_at, tz) >= month_start
        )
        last = max((tx.created_at for tx in txs), default=None)
        rows.append(
            [
                _text(_name(user)),
                f"=ROUND(SUM({a1(tab.title, 'E2:E')}),2)",
                _dollars(balance),
                f'=IF(ROUND(B{row_number}-C{row_number},2)=0,"✓","✗ mismatch")',
                _dollars(earned),
                _dollars(spent),
                f"{_local(last, tz):%Y-%m-%d %H:%M}" if last else "",
                f"=COUNT({a1(tab.title, 'A2:A')})",
            ]
        )
    rows.append([])
    rows.append(["Updated", f"{local_now:%Y-%m-%d %H:%M} ({settings.sheet_timezone})"])
    return rows


def sync_sheet(session: Session, client, now: datetime | None = None) -> SyncResult:
    now = now or utcnow()
    tz = ZoneInfo(settings.sheet_timezone)
    result = SyncResult()
    sheet_tz, tabs = client.get_spreadsheet()
    if sheet_tz != settings.sheet_timezone:
        # Only affects Sheets' own date functions; the ledger's dates are
        # converted by the app, so a rejected zone name is not fatal.
        try:
            client.set_timezone(settings.sheet_timezone)
        except SheetsError:
            log.warning("could not set spreadsheet timezone to %s", settings.sheet_timezone)

    by_user = {int(t.metadata[USER_KEY]): t for t in tabs if t.metadata.get(USER_KEY, "").isdigit()}
    totals_tab = next((t for t in tabs if TOTALS_KEY in t.metadata), None)
    taken = {t.title.lower() for t in tabs} | {TOTALS_TITLE.lower()}

    users_tabs: list[tuple[User, Tab]] = []
    for user in ledger_users(session):
        tab = by_user.get(user.id)
        if tab is None:
            title = _unique_title(_name(user), user.id, taken)
            tab = client.add_tab(
                title,
                USER_KEY,
                str(user.id),
                LEDGER_HEADER,
                LEDGER_CURRENCY_COLUMNS,
                _currency_pattern(),
            )
            taken.add(title.lower())
            result.tabs_created.append(title)
        appended = _sync_user(session, client, user, tab, tz)
        if appended:
            result.appended[user.id] = appended
        users_tabs.append((user, tab))

    if totals_tab is None:
        existing = {t.title.lower() for t in tabs}
        title = TOTALS_TITLE if TOTALS_TITLE.lower() not in existing else "Pocket Money totals"
        totals_tab = client.add_tab(
            title, TOTALS_KEY, "1", TOTALS_HEADER, TOTALS_CURRENCY_COLUMNS, _currency_pattern()
        )
        result.tabs_created.append(title)
    client.replace_values(totals_tab.title, totals_rows(session, users_tabs, now, tz))
    return result


@contextmanager
def _sync_lock():
    """One sync at a time across the web process and cron, so two runs
    can't both append the same rows."""
    with open(settings.sheet_lock_path, "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def run_sheet_sync(raise_errors: bool = False) -> SyncResult | None:
    """Sync if configured. Background tasks call this with errors swallowed
    (logged) — the cron catch-up retries; the script raises them."""
    if not is_configured():
        return None
    try:
        with _sync_lock(), Session(engine) as session:
            return sync_sheet(session, make_client())
    except Exception:
        if raise_errors:
            raise
        log.exception("Google Sheets ledger sync failed; the cron catch-up will retry")
        return None
