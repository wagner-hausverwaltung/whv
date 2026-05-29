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
    )
    assert s.app_env == app_env
