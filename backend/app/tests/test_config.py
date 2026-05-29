"""Settings hardening: outside dev the app must refuse to boot with the
default or empty `jwt_secret` — a publicly known signing key would let
anyone forge a VERWALTER access token and impersonate any user."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import DEFAULT_JWT_SECRET, Settings


@pytest.mark.parametrize("app_env", ["staging", "prod"])
@pytest.mark.parametrize("secret", ["", DEFAULT_JWT_SECRET])
def test_default_or_empty_jwt_secret_rejected_outside_dev(app_env: str, secret: str) -> None:
    # `_env_file=None` keeps the test hermetic — it ignores any repo .env so
    # the assertion depends only on the kwargs we pass.
    with pytest.raises(ValidationError, match="jwt_secret"):
        Settings(_env_file=None, app_env=app_env, jwt_secret=secret)


def test_dev_allows_default_jwt_secret() -> None:
    # Dev keeps the convenient default so local runs + the test suite need
    # no extra setup.
    s = Settings(_env_file=None, app_env="dev", jwt_secret=DEFAULT_JWT_SECRET)
    assert s.jwt_secret == DEFAULT_JWT_SECRET


@pytest.mark.parametrize("app_env", ["dev", "staging", "prod"])
def test_real_secret_accepted_everywhere(app_env: str) -> None:
    s = Settings(
        _env_file=None,
        app_env=app_env,
        jwt_secret="a-strong-random-secret-value",
        # Pass a real https origin so the prod CORS guard (below) is satisfied;
        # harmless for dev/staging where that guard is a no-op.
        portal_base_url="https://portal.example.com",
    )
    assert s.app_env == app_env


def test_prod_rejects_localhost_cors_origin() -> None:
    with pytest.raises(ValidationError, match="CORS origin"):
        Settings(
            _env_file=None,
            app_env="prod",
            jwt_secret="a-strong-random-secret-value",
            portal_base_url="http://localhost:5173",
        )


def test_prod_rejects_plain_http_admin_origin() -> None:
    with pytest.raises(ValidationError, match="CORS origin"):
        Settings(
            _env_file=None,
            app_env="prod",
            jwt_secret="a-strong-random-secret-value",
            portal_base_url="https://portal.example.com",
            admin_base_url="http://admin.example.com",
        )


def test_prod_accepts_https_origins() -> None:
    s = Settings(
        _env_file=None,
        app_env="prod",
        jwt_secret="a-strong-random-secret-value",
        portal_base_url="https://portal.example.com",
        admin_base_url="https://admin.example.com",
    )
    assert s.admin_base_url == "https://admin.example.com"


def test_staging_allows_localhost_cors_origin() -> None:
    # The CORS guard is prod-only; staging keeps the localhost defaults usable.
    s = Settings(
        _env_file=None,
        app_env="staging",
        jwt_secret="a-strong-random-secret-value",
        portal_base_url="http://localhost:5173",
    )
    assert s.app_env == "staging"
