"""Thin Google Sheets REST client for the ledger mirror (sheets_sync.py).

Authenticates as a Google Cloud service account — the spreadsheet must be
shared with the service account's email as an editor (DEPLOYMENT.md). Uses
google-auth's AuthorizedSession against the Sheets v4 REST API directly, so
no extra Google client library is needed.

Tabs are found by developer metadata (an invisible key/value tag on the
tab), never by title, so renaming a tab in the Sheets UI is harmless.
"""

from dataclasses import dataclass, field
from urllib.parse import quote

from .metrics import record_external_call

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
API = "https://sheets.googleapis.com/v4/spreadsheets"


class SheetsError(Exception):
    pass


@dataclass
class Tab:
    sheet_id: int
    title: str
    metadata: dict[str, str] = field(default_factory=dict)


def a1(title: str, cells: str) -> str:
    """A1 range on a tab, quoting the title ('O''Brien'!A2:A)."""
    return "'" + title.replace("'", "''") + "'!" + cells


class GoogleSheetsClient:
    def __init__(self, spreadsheet_id: str, session, editor_email: str | None = None):
        self.spreadsheet_id = spreadsheet_id
        self.session = session  # google.auth.transport.requests.AuthorizedSession
        self.editor_email = editor_email  # sole editor of protected ranges

    @classmethod
    def from_service_account_file(cls, spreadsheet_id: str, path: str) -> "GoogleSheetsClient":
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
        return cls(
            spreadsheet_id,
            AuthorizedSession(credentials),
            editor_email=credentials.service_account_email,
        )

    def _call(self, method: str, path: str, **kwargs) -> dict:
        url = f"{API}/{self.spreadsheet_id}{path}"
        try:
            response = self.session.request(method, url, timeout=30, **kwargs)
        except Exception as exc:  # network, TLS, auth refresh: the call never completed
            record_external_call("google_sheets", ok=False, error=type(exc).__name__)
            raise
        if response.status_code >= 400:
            # Status only: the path names tabs (children), which stay out of the log line.
            record_external_call("google_sheets", ok=False, error=f"{method} HTTP {response.status_code}")
            raise SheetsError(f"{method} {path}: {response.status_code} {response.text[:500]}")
        record_external_call("google_sheets", ok=True)
        return response.json() if response.content else {}

    def _batch_update(self, requests: list[dict]) -> dict:
        return self._call("POST", ":batchUpdate", json={"requests": requests})

    def get_spreadsheet(self) -> tuple[str, list[Tab]]:
        """(spreadsheet timezone, tabs with their developer metadata)."""
        data = self._call(
            "GET",
            "",
            params={
                "fields": "properties.timeZone,"
                "sheets(properties(sheetId,title),developerMetadata(metadataKey,metadataValue))"
            },
        )
        tabs = [
            Tab(
                sheet_id=sheet["properties"]["sheetId"],
                title=sheet["properties"]["title"],
                metadata={
                    m["metadataKey"]: m.get("metadataValue", "")
                    for m in sheet.get("developerMetadata", [])
                },
            )
            for sheet in data.get("sheets", [])
        ]
        return data.get("properties", {}).get("timeZone", ""), tabs

    def set_timezone(self, timezone: str) -> None:
        self._batch_update(
            [
                {
                    "updateSpreadsheetProperties": {
                        "properties": {"timeZone": timezone},
                        "fields": "timeZone",
                    }
                }
            ]
        )

    def add_tab(
        self,
        title: str,
        metadata_key: str,
        metadata_value: str,
        header: list[str],
        currency_columns: list[int],
        currency_pattern: str,
    ) -> Tab:
        """Create a tab with a bold frozen header row, currency-formatted
        columns, a metadata tag, and edit protection (service account only)."""
        reply = self._batch_update([{"addSheet": {"properties": {"title": title}}}])
        sheet_id = reply["replies"][0]["addSheet"]["properties"]["sheetId"]
        requests: list[dict] = [
            {
                "createDeveloperMetadata": {
                    "developerMetadata": {
                        "metadataKey": metadata_key,
                        "metadataValue": metadata_value,
                        "location": {"sheetId": sheet_id},
                        "visibility": "DOCUMENT",
                    }
                }
            },
            {
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                    "fields": "gridProperties.frozenRowCount",
                }
            },
            {
                "updateCells": {
                    "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
                    "rows": [
                        {
                            "values": [
                                {
                                    "userEnteredValue": {"stringValue": text},
                                    "userEnteredFormat": {"textFormat": {"bold": True}},
                                }
                                for text in header
                            ]
                        }
                    ],
                    "fields": "userEnteredValue,userEnteredFormat.textFormat.bold",
                }
            },
        ]
        for column in currency_columns:
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "startColumnIndex": column,
                            "endColumnIndex": column + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {"type": "CURRENCY", "pattern": currency_pattern}
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    }
                }
            )
        protected = {
            "range": {"sheetId": sheet_id},
            "description": "Pocket Money ledger — written by the app only",
            "warningOnly": False,
        }
        if self.editor_email:
            protected["editors"] = {"users": [self.editor_email]}
        requests.append({"addProtectedRange": {"protectedRange": protected}})
        self._batch_update(requests)
        return Tab(sheet_id=sheet_id, title=title, metadata={metadata_key: metadata_value})

    def read_column(self, title: str, cells: str = "A2:A") -> list[str]:
        data = self._call(
            "GET",
            f"/values/{quote(a1(title, cells), safe='')}",
            params={"majorDimension": "COLUMNS", "valueRenderOption": "UNFORMATTED_VALUE"},
        )
        columns = data.get("values", [])
        return [str(v) for v in columns[0]] if columns else []

    def append_rows(self, title: str, rows: list[list]) -> None:
        """Append as RAW — cell text is never interpreted as a formula."""
        self._call(
            "POST",
            f"/values/{quote(a1(title, 'A1'), safe='')}:append",
            params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
            json={"values": rows},
        )

    def replace_values(self, title: str, rows: list[list]) -> None:
        """Clear the tab below its header and write rows from A2, as
        USER_ENTERED so formulas evaluate (caller escapes plain text)."""
        self._call("POST", f"/values/{quote(a1(title, 'A2:Z'), safe='')}:clear", json={})
        if rows:
            self._call(
                "PUT",
                f"/values/{quote(a1(title, 'A2'), safe='')}",
                params={"valueInputOption": "USER_ENTERED"},
                json={"values": rows},
            )
