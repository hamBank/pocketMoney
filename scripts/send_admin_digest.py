"""Cron entry point — run daily (see DEPLOYMENT.md), e.g.:

    0 18 * * *  cd /opt/pocketMoney && .venv/bin/python scripts/send_admin_digest.py

Emails every active admin the pending-claims queue plus the last 24h of
claim activity. Sends nothing when there is nothing pending and no
activity. With SMTP unconfigured the email is printed to stdout.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlmodel import Session  # noqa: E402

from backend.database import engine  # noqa: E402
from backend.digest import send_admin_digest  # noqa: E402


def main() -> None:
    with Session(engine) as session:
        sent = send_admin_digest(session)
    print("digest sent" if sent else "nothing to report — no email sent")


if __name__ == "__main__":
    main()
