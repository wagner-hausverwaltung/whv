from datetime import UTC, datetime
from typing import Annotated

import jwt as jwt_lib
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import (
    decode_token,
    encode_access_token,
    encode_refresh_token,
    hash_refresh_token,
)
from app.auth.passwords import hash_password, verify_password
from app.config import Settings, get_settings
from app.db import get_session
from app.models import InviteCode, Session, User
from app.schemas.auth import (
    InviteRedeemRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue_tokens(settings: Settings, user: User, session: AsyncSession) -> TokenResponse:
    """Issue a new (access, refresh) pair and record the refresh in the sessions table.

    Caller is responsible for committing the session.
    """
    access_token, _access_exp = encode_access_token(
        settings, user.id, user.role.value, user.organization_id
    )
    refresh_token, refresh_exp, _jti = encode_refresh_token(settings, user.id)

    session.add(
        Session(
            user_id=user.id,
            refresh_token_hash=hash_refresh_token(refresh_token),
            expires_at=refresh_exp,
        )
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_ttl_minutes * 60,
        user=UserResponse(
            id=user.id,
            email=user.email,
            role=user.role.value,
            organization_id=user.organization_id,
            contact_id_impower=user.contact_id_impower,
        ),
    )


@router.post("/invite/redeem", response_model=TokenResponse)
async def redeem_invite(
    req: InviteRedeemRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    invite = await session.scalar(
        select(InviteCode).where(
            InviteCode.code == req.code,
            InviteCode.email == req.email.lower(),
            InviteCode.consumed_at.is_(None),
            InviteCode.expires_at > datetime.now(UTC),
        )
    )
    if invite is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite invalid, expired, or already used",
        )

    existing = await session.scalar(select(User).where(User.email == req.email.lower()))
    if existing is not None and existing.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account already exists for this email",
        )

    user = User(
        organization_id=invite.organization_id,
        email=req.email.lower(),
        password_hash=hash_password(req.password),
        role=invite.role,
        contact_id_impower=invite.contact_id_impower,
    )
    session.add(user)
    await session.flush()

    invite.consumed_at = datetime.now(UTC)
    tokens = _issue_tokens(settings, user, session)
    await session.commit()
    return tokens


@router.post("/login", response_model=TokenResponse)
async def login(
    req: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    user = await session.scalar(select(User).where(User.email == req.email.lower()))
    if user is None or user.deleted_at is not None or user.password_hash is None:
        # Dummy hash to keep timing similar between unknown-user and wrong-password.
        hash_password("__dummy__")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    user.last_login_at = datetime.now(UTC)
    tokens = _issue_tokens(settings, user, session)
    await session.commit()
    return tokens


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    req: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    try:
        decode_token(settings, req.refresh_token, "refresh")
    except jwt_lib.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        ) from exc

    token_hash = hash_refresh_token(req.refresh_token)
    db_session = await session.scalar(
        select(Session).where(
            Session.refresh_token_hash == token_hash,
            Session.revoked_at.is_(None),
            Session.expires_at > datetime.now(UTC),
        )
    )
    if db_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked or expired",
        )

    user = await session.scalar(select(User).where(User.id == db_session.user_id))
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    db_session.revoked_at = datetime.now(UTC)
    tokens = _issue_tokens(settings, user, session)
    await session.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    req: LogoutRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    token_hash = hash_refresh_token(req.refresh_token)
    await session.execute(
        update(Session)
        .where(Session.refresh_token_hash == token_hash, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()
