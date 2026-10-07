"""Cron entry point — run every 10 minutes (see DEPLOYMENT.md), e.g.:

    */10 * * * *  cd /opt/pocketMoney && .venv/bin/python scripts/sync_sheet.py

Catch-up for the Google Sheets ledger mirror: appends any transactions not
yet in the sheet (the app also syncs after every money change) and
refreshes the Totals tab. Safe to run any time — the sheet's own highest
Tx ID per tab is the high-water mark. The first run backfills all history.
Does nothing when GOOGLE_SHEET_ID is unset.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.sheets_sync import is_configured, run_sheet_sync  # noqa: E402


def main() -> None:
    if not is_configured():
        print("GOOGLE_SHEET_ID not set — sheet sync disabled")
        return
    result = run_sheet_sync(raise_errors=True)
    rows = sum(result.appended.values())
    created = f", created tab(s): {', '.join(result.tabs_created)}" if result.tabs_created else ""
    print(f"appended {rows} row(s){created}")


if __name__ == "__main__":
    main()
