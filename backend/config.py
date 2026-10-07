from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """App configuration from environment variables (see DEVELOPMENT.md)."""

    database_url: str = "sqlite:///./pmoney.db"
    auth_enabled: bool = True
    google_client_id: str = ""
    jwt_secret: str = "dev-secret-change-me"
    allowed_emails: str = ""  # comma-separated bootstrap allowlist
    deploy_secret: str = ""
    deploy_trigger_path: str = ".deploy-trigger"
    currency_symbol: str = "$"
    # Gmail SMTP relay for the admin daily digest (see DEPLOYMENT.md for
    # App Password setup); unset smtp_user = log emails to stdout instead
    # of sending, so local dev and tests never need real credentials.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    # Google Sheets ledger mirror (see DEPLOYMENT.md for service-account
    # setup); unset google_sheet_id = mirror disabled, so local dev and
    # tests never need real credentials.
    google_sheet_id: str = ""
    google_service_account_file: str = ""
    sheet_timezone: str = "Australia/Canberra"
    sheet_lock_path: str = ".sheet-sync.lock"

    @field_validator("sheet_timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        # Fail at startup, not by writing wrong dates into the ledger.
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown timezone {value!r}") from exc
        return value


settings = Settings()
