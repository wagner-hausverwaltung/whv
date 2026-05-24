import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

import jwt as jwt_lib
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import decode_token
from app.config import Settings, get_settings
from app.db import get_session
from app.models import User, UserRole

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(settings, credentials.credentials, "access")
    except jwt_lib.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt_lib.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    sub = payload.get("sub")
    if not isinstance(sub, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")
    try:
        user_id = uuid.UUID(sub)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token"
        ) from exc

    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None or user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_role(*allowed: UserRole) -> Callable[[User], Coroutine[Any, Any, User]]:
    """Build a FastAPI dependency that 403s if the authenticated user's role isn't in `allowed`.

    Usage:
        verwalter_only = require_role(UserRole.VERWALTER)
        @router.get(...)
        async def endpoint(user: Annotated[User, Depends(verwalter_only)]) -> ...:
            ...
    """

    async def _check(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden — role not allowed",
            )
        return user

    return _check
