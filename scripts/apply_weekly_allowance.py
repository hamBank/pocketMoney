"""Cron entry point — run Monday mornings (see DEPLOYMENT.md), e.g.:

    0 6 * * 1  cd /opt/pocketMoney && .venv/bin/python scripts/apply_weekly_allowance.py

Idempotent: at most one allowance transaction per user per ISO week, so
re-runs and late catch-up runs are safe.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlmodel import Session  # noqa: E402

from backend.allowance import apply_weekly_allowance  # noqa: E402
from backend.database import engine  # noqa: E402


def main() -> None:
    with Session(engine) as session:
        created = apply_weekly_allowance(session)
    print(f"applied {len(created)} allowance transaction(s)")


if __name__ == "__main__":
    main()
