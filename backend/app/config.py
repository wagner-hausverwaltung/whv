from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Look in cwd and one level up so the same .env works whether you
        # run from the repo root or from backend/.
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"

    database_url: str = Field(
        default="postgresql+asyncpg://whv:whv@localhost:5432/whv",
        description="Async DSN for Postgres",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )

    impower_api_base: str = "https://api.app.impower.de/v2/d"
    impower_api_token: str = ""

    resend_api_key: str = ""
    email_from_address: str = "noreply@wagner-hausverwaltung.com"
    email_from_name: str = "Wagner Hausverwaltung"

    jwt_secret: str = "change-me-in-prod"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    password_reset_ttl_minutes: int = 30

    # Absolute origin (scheme + host) of the admin UI. Used to build clickable
    # reset links in password-reset emails — needs to differ per environment
    # (localhost in dev, admin.wagner-hausverwaltung.com on staging/prod).
    admin_ui_base_url: str = "http://localhost:8000"

    # Absolute origin of the public Eigentümer/Mieter web portal. Used as the
    # allowed CORS origin for SPA requests.
    portal_base_url: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
