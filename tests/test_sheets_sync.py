from datetime import datetime, timezone

import pytest
from conftest import auth_headers, sign_in
from sqlmodel import Session

from backend import sheets_sync
from backend.config import Settings, settings
from backend.database import engine
from backend.models import (
    Chore,
    Claim,
    ClaimStatus,
    Transaction,
    TransactionType,
    User,
    UserRole,
)
from backend.sheets import GoogleSheetsClient, SheetsError, Tab
from backend.sheets_sync import TOTALS_KEY, USER_KEY, run_sheet_sync, sync_sheet

NOW = datetime(2026, 10, 7, 2, 0, tzinfo=timezone.utc)  # Wed 7 Oct 2026, 13:00 in Canberra (AEDT)


class FakeSheets:
    """In-memory spreadsheet with the same interface as GoogleSheetsClient."""

    def __init__(self, timezone="Australia/Canberra"):
        self.timezone = timezone
        self.tabs: list[Tab] = []
        self.rows: dict[int, list[list]] = {}  # sheet_id → rows below header
        self.headers: dict[int, list[str]] = {}
        self.calls: list[str] = []

    def _tab(self, title):
        return next(t for t in self.tabs if t.title == title)

    def get_spreadsheet(self):
        return self.timezone, [Tab(t.sheet_id, t.title, dict(t.metadata)) for t in self.tabs]

    def set_timezone(self, timezone):
        self.calls.append(f"set_timezone {timezone}")
        self.timezone = timezone

    def add_tab(self, title, key, value, header, currency_columns, pattern):
        assert title.lower() not in {t.title.lower() for t in self.tabs}
        tab = Tab(len(self.tabs) + 100, title, {key: value})
        self.tabs.append(tab)
        self.rows[tab.sheet_id] = []
        self.headers[tab.sheet_id] = header
        return tab

    def read_column(self, title, cells="A2:A"):
        return [str(r[0]) for r in self.rows[self._tab(title).sheet_id] if r]

    def append_rows(self, title, rows):
        self.calls.append(f"append {title} {len(rows)}")
        self.rows[self._tab(title).sheet_id].extend(rows)

    def replace_values(self, title, rows):
        self.rows[self._tab(title).sheet_id] = rows

    # test helpers
    def ledger(self, user_id):
        tab = next(t for t in self.tabs if t.metadata.get(USER_KEY) == str(user_id))
        return self.rows[tab.sheet_id]

    def totals(self):
        tab = next(t for t in self.tabs if TOTALS_KEY in t.metadata)
        return self.rows[tab.sheet_id]


def add_user(session, email, name="", role=UserRole.user, active=True):
    user = User(email=email, name=name, role=role, is_active=active)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def add_tx(session, user, amount, type=TransactionType.adjustment, note="x", at=NOW, **kw):
    at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)  # test times are UTC
    tx = Transaction(user_id=user.id, amount=amount, type=type, note=note, created_at=at, **kw)
    session.add(tx)
    session.commit()
    session.refresh(tx)
    return tx


def test_first_run_backfills_with_running_balance_and_rerun_is_noop():
    sheet = FakeSheets()
    with Session(engine) as session:
        mum = add_user(session, "mum@example.com", "Mum", role=UserRole.admin)
        kid = add_user(session, "kid@example.com", "Alice")
        chore = Chore(name="Unload dishwasher", value=200, created_by=mum.id)
        session.add(chore)
        session.commit()
        claim = Claim(
            chore_id=chore.id, user_id=kid.id, submitted_by=kid.id, original_value=200,
            status=ClaimStatus.approved, approved_value=250, resolution_note="extra tidy",
            resolved_by=mum.id,
        )
        session.add(claim)
        session.commit()
        add_tx(session, kid, 1000, note="starting balance", created_by=mum.id)
        add_tx(session, kid, 250, type=TransactionType.claim_payout, note=None,
               claim_id=claim.id, created_by=mum.id)
        add_tx(session, kid, -300, type=TransactionType.withdrawal, note="spent at shop",
               created_by=mum.id)
        add_tx(session, kid, 500, type=TransactionType.allowance, note="2026-W41")

        result = sync_sheet(session, sheet, now=NOW)
        assert result.appended == {kid.id: 4}
        assert result.tabs_created == ["Alice", "Totals"]  # admin w/o history: no tab
        rows = sheet.ledger(kid.id)
        assert [r[2:6] for r in rows] == [
            ["Adjustment", "starting balance", 10.0, 10.0],
            ["Chore payout", "Unload dishwasher — extra tidy", 2.5, 12.5],
            ["Withdrawal", "spent at shop", -3.0, 9.5],
            ["Allowance", "Weekly allowance 2026-W41", 5.0, 14.5],
        ]
        assert rows[0][6] == "Mum" and rows[3][6] == "system"
        assert rows[1][7] == claim.id and rows[0][7] == ""

        # Re-running appends nothing.
        sheet.calls.clear()
        assert sync_sheet(session, sheet, now=NOW).appended == {}
        assert not [c for c in sheet.calls if c.startswith("append")]
        assert len(sheet.ledger(kid.id)) == 4


def test_only_new_rows_are_appended_and_balance_continues():
    sheet = FakeSheets()
    with Session(engine) as session:
        kid = add_user(session, "kid@example.com", "Alice")
        add_tx(session, kid, 1000)
        sync_sheet(session, sheet, now=NOW)
        add_tx(session, kid, -250, type=TransactionType.withdrawal, note="lollies")
        assert sync_sheet(session, sheet, now=NOW).appended == {kid.id: 1}
        assert [r[4:6] for r in sheet.ledger(kid.id)] == [[10.0, 10.0], [-2.5, 7.5]]


def test_renamed_tab_is_found_by_metadata_not_title():
    sheet = FakeSheets()
    with Session(engine) as session:
        kid = add_user(session, "kid@example.com", "Alice")
        add_tx(session, kid, 100)
        sync_sheet(session, sheet, now=NOW)
        sheet.tabs[0].title = "Alice's money"  # renamed in the Sheets UI
        kid.name = "Ali"
        session.add(kid)
        session.commit()
        add_tx(session, kid, 100)
        result = sync_sheet(session, sheet, now=NOW)
        assert result.tabs_created == []
        assert len(sheet.ledger(kid.id)) == 2
        assert "'Alice''s money'!E2:E" in sheet.totals()[0][1]  # quoted title


def test_new_child_and_admin_with_history_get_tabs_and_totals():
    sheet = FakeSheets()
    with Session(engine) as session:
        mum = add_user(session, "mum@example.com", "Mum", role=UserRole.admin)
        alice = add_user(session, "alice@example.com", "Alice")
        add_user(session, "gone@example.com", "Gone", active=False)  # no history: skipped
        sync_sheet(session, sheet, now=NOW)
        assert [t.title for t in sheet.tabs] == ["Alice", "Totals"]

        bob = add_user(session, "bob@example.com", "Alice")  # same name → disambiguated
        add_tx(session, mum, 50)
        result = sync_sheet(session, sheet, now=NOW)
        assert result.tabs_created == ["Mum", f"Alice ({bob.id})"]
        totals = sheet.totals()
        assert [row[0] for row in totals[:3]] == ["Mum", "Alice", "Alice"]
        assert totals[0][2] == 0.5 and totals[1][2] == 0.0
        assert totals[0][1] == "=ROUND(SUM('Mum'!E2:E),2)"
        assert totals[0][3] == '=IF(ROUND(B2-C2,2)=0,"✓","✗ mismatch")'
        assert totals[2][3].startswith("=IF(ROUND(B4-C4")
        assert totals[0][7] == "=COUNT('Mum'!A2:A)"
        assert totals[-1][0] == "Updated"
        assert alice.id != bob.id


def test_child_called_totals_does_not_clash_with_totals_tab():
    sheet = FakeSheets()
    with Session(engine) as session:
        kid = add_user(session, "kid@example.com", "Totals")
        sync_sheet(session, sheet, now=NOW)
        assert sorted(t.title for t in sheet.tabs) == ["Totals", f"Totals ({kid.id})"]


def test_dates_are_canberra_local_including_dst_changeover():
    sheet = FakeSheets()
    with Session(engine) as session:
        kid = add_user(session, "kid@example.com", "Alice")
        # AEST (+10) until 2am Sun 4 Oct 2026 (= 16:00 UTC Sat 3 Oct), then AEDT (+11).
        add_tx(session, kid, 1, at=datetime(2026, 10, 3, 15, 0))
        add_tx(session, kid, 1, at=datetime(2026, 10, 3, 17, 0))
        add_tx(session, kid, 1, at=datetime(2026, 10, 6, 13, 30))  # just after midnight local
        sync_sheet(session, sheet, now=NOW)
        assert [r[1] for r in sheet.ledger(kid.id)] == [
            "2026-10-04 01:00",
            "2026-10-04 04:00",
            "2026-10-07 00:30",
        ]


def test_week_and_month_totals_use_local_boundaries():
    sheet = FakeSheets()
    with Session(engine) as session:
        kid = add_user(session, "kid@example.com", "Alice")
        # Sun 4 Oct 23:30 local = previous week; Mon 5 Oct 00:30 local = this week.
        add_tx(session, kid, 100, at=datetime(2026, 10, 4, 12, 30))
        add_tx(session, kid, 200, at=datetime(2026, 10, 4, 13, 30))
        add_tx(session, kid, -50, type=TransactionType.withdrawal, at=datetime(2026, 10, 5))
        # 30 Sep 23:00 local = September, not this month.
        add_tx(session, kid, -70, type=TransactionType.withdrawal, at=datetime(2026, 9, 30, 13))
        add_tx(session, kid, -10, type=TransactionType.penalty, at=datetime(2026, 10, 5))
        sync_sheet(session, sheet, now=NOW)
        row = sheet.totals()[0]
        assert row[2] == 1.7  # app balance
        assert row[4] == 2.0  # earned this week (credits only)
        assert row[5] == 0.5  # spent this month (withdrawals only)
        assert row[6] == "2026-10-05 11:00"


def test_names_that_look_like_formulas_are_escaped_in_totals():
    sheet = FakeSheets()
    with Session(engine) as session:
        add_user(session, "kid@example.com", "=HYPERLINK(\"x\")")
        sync_sheet(session, sheet, now=NOW)
        assert sheet.totals()[0][0] == "'=HYPERLINK(\"x\")"


def test_spreadsheet_timezone_is_set_and_rejection_is_not_fatal():
    sheet = FakeSheets(timezone="America/New_York")
    with Session(engine) as session:
        add_user(session, "kid@example.com", "Alice")
        sync_sheet(session, sheet, now=NOW)
        assert sheet.timezone == "Australia/Canberra"

        sheet.timezone = "Etc/UTC"
        sheet.set_timezone = lambda tz: (_ for _ in ()).throw(SheetsError("bad zone"))
        sync_sheet(session, sheet, now=NOW)  # still syncs


@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "google_sheet_id", "sheet-123")
    monkeypatch.setattr(settings, "sheet_lock_path", str(tmp_path / "sync.lock"))
    sheet = FakeSheets()
    monkeypatch.setattr(sheets_sync, "make_client", lambda: sheet)
    return sheet


def test_run_sheet_sync_is_noop_when_unconfigured(monkeypatch):
    monkeypatch.setattr(sheets_sync, "make_client", lambda: pytest.fail("should not connect"))
    assert run_sheet_sync() is None


def test_run_sheet_sync_swallows_errors_unless_asked(configured, monkeypatch):
    def broken():
        raise SheetsError("Google is down")

    monkeypatch.setattr(sheets_sync, "make_client", broken)
    assert run_sheet_sync() is None
    with pytest.raises(SheetsError):
        run_sheet_sync(raise_errors=True)


def test_money_routes_sync_the_sheet_after_commit(client, monkeypatch, configured):
    admin_token = sign_in(client, monkeypatch, "parent@example.com")["token"]
    kid = client.post(
        "/users/invite",
        json={"email": "kid@example.com", "name": "Kid"},
        headers=auth_headers(admin_token),
    ).json()
    client.post(
        "/transactions",
        json={"user_id": kid["id"], "type": "adjustment", "amount": 1000, "note": "start"},
        headers=auth_headers(admin_token),
    )
    assert [r[3] for r in configured.ledger(kid["id"])] == ["start"]

    claim = client.post(
        "/claims",
        json={"user_id": kid["id"], "kind": "adhoc", "name": "Wash car", "value": 500},
        headers=auth_headers(admin_token),
    ).json()
    assert len(configured.ledger(kid["id"])) == 1  # pending: no money moved yet
    client.post(f"/claims/{claim['id']}/approve", json={}, headers=auth_headers(admin_token))
    assert [r[3:6] for r in configured.ledger(kid["id"])][-1] == ["Wash car", 5.0, 15.0]

    client.post(
        "/claims",
        json={"user_id": kid["id"], "kind": "penalty", "name": "Rude", "value": -100,
              "auto_approve": True},
        headers=auth_headers(admin_token),
    )
    assert configured.ledger(kid["id"])[-1][2:6] == ["Penalty", "Rude", -1.0, 14.0]


def test_money_write_succeeds_even_if_sheet_sync_fails(client, monkeypatch, configured):
    monkeypatch.setattr(
        sheets_sync, "make_client", lambda: (_ for _ in ()).throw(SheetsError("down"))
    )
    admin_token = sign_in(client, monkeypatch, "parent@example.com")["token"]
    me = client.get("/auth/me", headers=auth_headers(admin_token)).json()
    response = client.post(
        "/transactions",
        json={"user_id": me["id"], "type": "adjustment", "amount": 100, "note": "ok"},
        headers=auth_headers(admin_token),
    )
    assert response.status_code == 201


def test_invalid_timezone_rejected_at_startup():
    with pytest.raises(ValueError, match="Unknown timezone"):
        Settings(sheet_timezone="Australia/Atlantis")
    assert Settings().sheet_timezone == "Australia/Canberra"


class RecordingSession:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        body = self.replies.pop(0) if self.replies else {}

        class Response:
            status_code = 200
            content = b"{}"
            text = ""

            @staticmethod
            def json():
                return body

        return Response()


def test_google_client_requests():
    session = RecordingSession([{"replies": [{"addSheet": {"properties": {"sheetId": 7}}}]}])
    client = GoogleSheetsClient("abc", session, editor_email="sa@proj.iam.gserviceaccount.com")
    tab = client.add_tab("O'Brien", USER_KEY, "3", ["Tx ID"], [4], '"$"#,##0.00')
    assert tab.sheet_id == 7
    setup = session.requests[1][2]["json"]["requests"]
    kinds = [next(iter(r)) for r in setup]
    assert kinds == [
        "createDeveloperMetadata",
        "updateSheetProperties",
        "updateCells",
        "repeatCell",
        "addProtectedRange",
    ]
    assert setup[-1]["addProtectedRange"]["protectedRange"]["editors"] == {
        "users": ["sa@proj.iam.gserviceaccount.com"]
    }

    client.append_rows("O'Brien", [[1, "x"]])
    method, url, kwargs = session.requests[-1]
    assert method == "POST"
    assert url.endswith("/abc/values/%27O%27%27Brien%27%21A1:append")
    assert kwargs["params"]["valueInputOption"] == "RAW"
