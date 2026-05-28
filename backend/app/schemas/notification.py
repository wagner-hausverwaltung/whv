"""Schemas for the per-user notification preference matrix.

Shared verbatim by the web portal and the iOS app via
`GET/PUT /me/notification-settings`. Each item is one category with
its two independent channel switches.
"""

from pydantic import BaseModel

from app.models import NotificationCategory


class NotificationSetting(BaseModel):
    # NotificationCategory is a StrEnum, so it serializes to its string
    # value ("ANNOUNCEMENT", …) and parses back from the same — no
    # use_enum_values needed, and the service keeps real enum members.
    category: NotificationCategory
    push: bool
    email: bool


class NotificationSettingsResponse(BaseModel):
    items: list[NotificationSetting]


class UpdateNotificationSettingsRequest(BaseModel):
    items: list[NotificationSetting]
