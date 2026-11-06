from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Public (it's in the source): only usable with auth disabled, see below.
DEFAULT_JWT_SECRET = "dev-secret-change-me"


class Settings(BaseSettings):
    """App configuration from environment variables (see DEVELOPMENT.md)."""

    # A validation error would otherwise quote every value it was given,
    # secrets included, into the journal and the deploy log.
    model_config = SettingsConfigDict(hide_input_in_errors=True)

    database_url: str = "sqlite:///./pmoney.db"
    auth_enabled: bool = True
    google_client_id: str = ""
    jwt_secret: str = DEFAULT_JWT_SECRET
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

    @model_validator(mode="after")
    def _auth_needs_a_private_secret(self):
        # Fleet spec CFG-2: the default is in the source, so anyone could
        # forge a login token. Refuse to start rather than run that way.
        if self.auth_enabled and self.jwt_secret in ("", DEFAULT_JWT_SECRET):
            raise ValueError(
                "JWT_SECRET is unset or still the public default; set it to a "
                "long random string, e.g. `openssl rand -hex 32`"
            )
        return self


settings = Settings()
