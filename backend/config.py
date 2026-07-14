from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """App configuration from environment variables (see DEVELOPMENT.md)."""

    database_url: str = "sqlite:///./pmoney.db"
    auth_enabled: bool = True
    google_client_id: str = ""
    jwt_secret: str = "dev-secret-change-me"
    allowed_emails: str = ""  # comma-separated bootstrap allowlist
    deploy_secret: str = ""
    currency_symbol: str = "$"
    # SMTP for the admin daily digest; unset host = log emails to stdout.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""


settings = Settings()
