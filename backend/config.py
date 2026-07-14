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


settings = Settings()
