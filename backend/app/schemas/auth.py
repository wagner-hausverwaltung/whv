import uuid

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class InviteRedeemRequest(BaseModel):
    code: str
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=10, max_length=200)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: str
    organization_id: uuid.UUID
    contact_id_impower: int | None = None
    avatar_url: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class InviteInfoResponse(BaseModel):
    """Returned by GET /auth/invite/{code} so clients can pre-fill the
    redemption form. Mirrors the InviteCode fields the user needs to
    see in order to know whether the code is theirs to redeem; we don't
    leak organization_id or contact_id_impower — name is human-
    readable, the rest are internal."""

    email: EmailStr
    role: str
    organization_name: str
    # ISO 8601; client uses it to show "noch X Tage gültig".
    expires_at: str
