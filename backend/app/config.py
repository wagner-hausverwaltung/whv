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

    # Absolute origin of the public web portal (SPA). Used as the allowed
    # CORS origin for SPA requests and as the base for clickable reset
    # links in password-reset emails. The same SPA bundle hosts both the
    # customer portal and the Verwalter admin under /admin/*.
    portal_base_url: str = "http://localhost:5173"
    # Optional second CORS origin: the admin host serves the same SPA but
    # via a different DNS name (admin.wagner-hausverwaltung.com vs.
    # portal.wagner-hausverwaltung.com). When set, it joins portal_base_url
    # in the CORS allow-list. Empty in dev (single Vite origin).
    admin_base_url: str = ""

    # AWS SES inbound email pipeline. The SES receipt rule saves the full MIME
    # to s3://{s3_inbound_bucket}/{messageId} and publishes a notification to
    # SNS; the webhook handler fetches the body from S3 (since "Publish to SNS"
    # action caps at 150 KB — too small for any Outlook email with a signature).
    # Credentials use a dedicated IAM user scoped to the inbound bucket only.
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    s3_inbound_bucket: str = ""
    s3_inbound_region: str = "eu-central-1"

    # Where the Celery result-PDF task writes Umlaufbeschluss protocols on
    # disk. Phase 1 stores PDFs locally; §1.4d iter 2 will switch to Hetzner
    # Object Storage and replace this with bucket config. The dir is created
    # on first write — no need to provision it ahead of time.
    resolution_pdf_dir: str = "/var/lib/whv/resolutions"

    # User-uploaded avatar images. Stored as PNG (Pillow normalises every
    # upload to keep the static-mount URL stable). Same Hetzner-OS migration
    # path as resolution PDFs in §1.4d iter 2.
    avatar_dir: str = "/var/lib/whv/avatars"
    # Max size of an uploaded avatar in bytes. 4 MB is plenty for a face
    # photo; we resize down to 256x256 anyway before saving.
    avatar_max_bytes: int = 4 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
