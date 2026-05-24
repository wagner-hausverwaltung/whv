import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt as jwt_lib
from fastapi import APIRouter, Depends, HTTPException, Response, status
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
from app.integrations.email.client import EmailClient, EmailError, get_email_client
from app.integrations.email.password_reset import render_password_reset_email
from app.models import AuditLog, InviteCode, PasswordResetToken, Session, User
from app.schemas.auth import (
    ForgotPasswordRequest,
    InviteRedeemRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(
    req: ForgotPasswordRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    email_client: Annotated[EmailClient, Depends(get_email_client)],
) -> Response:
    """Issue a single-use password-reset token.

    Always returns 204 regardless of whether the email matches a user — this
    prevents email enumeration. If a user exists, a sha256-hashed token is
    stored and the raw token is emailed to them. Failures (no user, email
    send failure) are silently absorbed; the response is the same.
    """
    user = await session.scalar(select(User).where(User.email == req.email.lower()))

    if user is not None and user.deleted_at is None:
        raw_token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=settings.password_reset_ttl_minutes)
        session.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=_hash_reset_token(raw_token),
                expires_at=expires_at,
            )
        )
        await session.commit()

        try:
            subject, html, text = render_password_reset_email(
                email=user.email,
                token=raw_token,
                ttl_minutes=settings.password_reset_ttl_minutes,
            )
            await email_client.send(to=user.email, subject=subject, html=html, text=text)
        except EmailError:
            # Don't leak whether email was sent; user can request another reset.
            # The token row exists and is redeemable until expiry.
            pass

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    req: ResetPasswordRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Redeem a password-reset token to set a new password.

    On success:
    - users.password_hash updated
    - all active sessions for the user revoked (force re-login everywhere)
    - token marked consumed
    - audit_log row written
    """
    now = datetime.now(UTC)
    token = await session.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == _hash_reset_token(req.token),
            PasswordResetToken.consumed_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
    )
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Token invalid, expired, or used"
        )

    user = await session.scalar(select(User).where(User.id == token.user_id))
    if user is None or user.deleted_at is not None:
        # The user was deleted between issue + reset; nothing to do.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Token invalid, expired, or used"
        )

    user.password_hash = hash_password(req.new_password)
    token.consumed_at = now

    await session.execute(
        update(Session)
        .where(Session.user_id == user.id, Session.revoked_at.is_(None))
        .values(revoked_at=now)
    )

    session.add(
        AuditLog(
            organization_id=user.organization_id,
            actor_user_id=user.id,
            action="user_password_reset",
            target_type="users",
            target_id=str(user.id),
        )
    )

    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
