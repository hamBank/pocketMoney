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


settings = Settings()
