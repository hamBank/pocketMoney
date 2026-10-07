# Pocket Money — Google Sheets ledger setup

> One-time setup for the optional Google Sheets mirror of the ledger
> (behaviour in [SPEC.md](SPEC.md); code in `backend/sheets_sync.py`).
> About 15 minutes. Everything here is free.

## What you're setting up

The app writes to the sheet as a Google Cloud **service account** — a robot
Google identity with its own email address (`…@….iam.gserviceaccount.com`)
and a **JSON key file** that proves it is that robot. You share one Google
Sheet with that email, and the app can then edit that sheet and nothing
else in your Google account.

This is **not** an "API key": Google API keys can only read public data and
cannot edit a sheet. It is also separate from the other two Google
credentials the app uses:

| Credential | Used for | Set in `.env` as |
|---|---|---|
| OAuth client ID | family members signing in | `GOOGLE_CLIENT_ID` |
| Gmail App Password | sending the admin digest | `SMTP_USER` / `SMTP_PASSWORD` |
| **Service account key** (this doc) | writing the ledger sheet | `GOOGLE_SERVICE_ACCOUNT_FILE` |

## Before you start

- Signed in to Google as the parent who should **own** the spreadsheet (a
  personal account is ideal — see Troubleshooting if you use Google
  Workspace).
- SSH access to the server (`camelidcastle.hups.club`) with `sudo`.
- PR #20 (or later) deployed, so `scripts/sync_sheet.py` exists.

## 1. Google Cloud project

1. Open <https://console.cloud.google.com/>.
2. Use the project that already holds the OAuth client for sign-in (project
   picker, top left) — or **New project**, name it "Pocket Money". Either is
   fine; reusing keeps everything in one place.

## 2. Enable the Google Sheets API

1. **APIs & Services → Library**, search **Google Sheets API**, open it.
2. Click **Enable**. (Only the Sheets API is needed — not Drive.)

## 3. Create the service account

1. **IAM & Admin → Service Accounts → + Create service account**.
2. Name: `pocket-money-sheets`. The ID and email fill themselves in —
   e.g. `pocket-money-sheets@pocket-money-123456.iam.gserviceaccount.com`.
   **Copy this email**; you need it in step 5.
3. Click **Create and continue**. On "Grant this service account access to
   project", **leave roles empty** — it needs no project permissions, only
   access to the one sheet you share with it. Click **Continue → Done**.

## 4. Create and download the JSON key

1. Click the new service account → **Keys** tab → **Add key → Create new
   key → JSON → Create**.
2. A file like `pocket-money-123456-abcdef123456.json` downloads. Google
   keeps no copy — if you lose it, delete the key and create another.
3. Treat it like a password: don't email it, commit it, or leave it in
   Downloads after step 6.

## 5. Create the spreadsheet and share it

1. Create a blank sheet at <https://sheets.new>, name it e.g.
   "Pocket Money ledger".
2. **Share** → paste the service account email from step 3 → role
   **Editor** → untick **Notify people** (the robot has no inbox) → **Share**.
3. Copy the **sheet ID** from the address bar — the long part between
   `/d/` and `/edit`:

   ```
   https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdEFG/edit#gid=0
                                          └──────────── GOOGLE_SHEET_ID ────────────┘
   ```

Share it (as Viewer) with anyone else in the family who should see it.
Don't add other editors — the app protects its tabs anyway, but the sheet
is meant to be a record only the app writes.

## 6. Install the key on the server

From your computer, copy the key up, then move it into place owned by the
app user and readable only by it:

```bash
scp ~/Downloads/pocket-money-*.json camelidcastle.hups.club:/tmp/sa.json

ssh camelidcastle.hups.club
sudo install -o pocketMoney -g pocketMoney -m 600 /tmp/sa.json \
  /opt/pocketMoney/google-service-account.json
rm /tmp/sa.json
```

Then delete the downloaded copy from your computer (or move it into your
password manager as an attachment, if you want a backup). The path is
already in `.gitignore`, so `git pull` during deploys never touches it.

## 7. Configure `.env`

Add to `/opt/pocketMoney/.env` (`sudo -u pocketMoney nano /opt/pocketMoney/.env`):

```
GOOGLE_SHEET_ID=1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdEFG
GOOGLE_SERVICE_ACCOUNT_FILE=/opt/pocketMoney/google-service-account.json
SHEET_TIMEZONE=Australia/Canberra
```

`SHEET_TIMEZONE` is any IANA zone name (default `Australia/Canberra`); the
app refuses to start if it's misspelled, rather than writing wrong dates.

## 8. Restart and backfill

```bash
sudo systemctl restart pmoney
cd /opt/pocketMoney
sudo -u pocketMoney bash -c 'set -a && source .env && .venv/bin/python scripts/sync_sheet.py'
```

Expected output on the first run:

```
appended 137 row(s), created tab(s): Alice, Bob, Totals
```

Run it again — it should say `appended 0 row(s)`. That's the idempotency
guarantee: it's always safe to run.

## 9. Check the sheet

- One tab per child, header row frozen, amounts in currency format, and a
  running **Balance** column that ends at the child's balance in the app.
- A **Totals** tab: every row's **DB check** column shows ✓.
- Tabs are protected: only the app (and you, as the sheet's owner — Google
  never locks out the owner) can edit them. Don't type in them; corrections
  belong in the app as adjustments, which then appear as new rows.
- You can delete the empty "Sheet1" Google created; the app ignores it.
- Renaming or reordering tabs is fine — the app finds them by a hidden tag.

From now on each approval, withdrawal, adjustment or allowance shows up
within seconds, and the cron entry (`*/10 * * * *` in
`deploy/pocketmoney.cron`) catches up anything missed.

## Troubleshooting

Errors from the instant sync go to `journalctl -u pmoney`; the cron
catch-up logs to `/var/log/pocketMoney-cron.log`. The fastest diagnosis is
running the step-8 command by hand — it prints the full error.

| Symptom | Cause / fix |
|---|---|
| `GOOGLE_SHEET_ID not set — sheet sync disabled` | `.env` not loaded or the line is missing — check step 7 and that you used the `set -a && source .env` form. |
| `403 … has not been used in project … or it is disabled` | Sheets API not enabled in the project the key belongs to — step 2 (allow a few minutes after enabling). |
| `403 … The caller does not have permission` | Sheet not shared with the service account email, or shared as Viewer — step 5. |
| `404 … Requested entity was not found` | Wrong `GOOGLE_SHEET_ID` — copy just the part between `/d/` and `/edit`. |
| `FileNotFoundError` / `PermissionError` on the JSON file | Wrong path in `GOOGLE_SERVICE_ACCOUNT_FILE`, or the file isn't owned by `pocketMoney` — redo step 6. |
| App won't start: `Unknown timezone` | Typo in `SHEET_TIMEZONE` — e.g. `Australia/Canberra`, `Australia/Sydney`. |
| Totals shows **✗ mismatch** | The sheet is behind the database (e.g. Google was down). Run the step-8 command; if it persists, check the logs. |
| A tab was deleted by mistake | Nothing to do — the next sync recreates it and backfills that child's full history. |
| Workspace: "Service account key creation is disabled" | Your Workspace org blocks key creation (`iam.disableServiceAccountKeyCreation`). Use a personal Google account for the project, or have the Workspace admin lift the policy for this project. |
| Workspace: can't share the sheet with the service account | The org restricts sharing outside the domain. Create the sheet in a personal account, or allowlist the service account. |

## Rotating or revoking the key

- **Rotate** (e.g. yearly, or if the file may have leaked): in the service
  account's **Keys** tab, **Add key** → install the new file over the old
  one (step 6) → `sudo systemctl restart pmoney` → run the step-8 command to
  confirm → **delete** the old key in the console.
- **Revoke access immediately**: delete the key in the console, or remove
  the service account from the sheet's sharing.
- **Turn the mirror off**: blank `GOOGLE_SHEET_ID` in `.env` and restart.
  The sheet stays as it is; set the ID again later and the next sync
  catches up from where it left off.

## Trying it locally (optional)

Point a dev checkout at a *separate test sheet* shared with the same
service account — never the family's real one:

```bash
export GOOGLE_SHEET_ID=<test sheet id>
export GOOGLE_SERVICE_ACCOUNT_FILE=~/keys/pocket-money-sa.json
python scripts/seed_dev_data.py
python scripts/sync_sheet.py
```
