from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
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

    jwt_secret: str = "change-me-in-prod"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
