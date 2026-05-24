import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt

from app.config import Settings

ACCESS_TYPE = "access"
REFRESH_TYPE = "refresh"


def encode_access_token(
    settings: Settings,
    user_id: uuid.UUID,
    role: str,
    organization_id: uuid.UUID,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=settings.access_token_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "org": str(organization_id),
        "typ": ACCESS_TYPE,
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, exp


def encode_refresh_token(settings: Settings, user_id: uuid.UUID) -> tuple[str, datetime, str]:
    now = datetime.now(UTC)
    exp = now + timedelta(days=settings.refresh_token_ttl_days)
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "typ": REFRESH_TYPE,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, exp, jti


def decode_token(
    settings: Settings,
    token: str,
    expected_type: Literal["access", "refresh"],
) -> dict[str, Any]:
    payload: dict[str, Any] = jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
    if payload.get("typ") != expected_type:
        raise jwt.InvalidTokenError(f"Expected {expected_type} token, got {payload.get('typ')}")
    return payload


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
