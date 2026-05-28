"""Schemas for push-device registration."""

from typing import Literal

from pydantic import BaseModel, Field


class RegisterDeviceRequest(BaseModel):
    """POST /me/devices body. The iOS app sends its APNs token after
    `didRegisterForRemoteNotificationsWithDeviceToken`.

    `environment` tells the backend which APNs host minted the token
    — a Debug/Xcode build gets a sandbox token, a TestFlight / App
    Store build gets a production one. The push service only sends
    to tokens matching the host it's configured for, so getting this
    right is what makes pushes actually arrive.
    """

    apns_token: str = Field(..., min_length=8, max_length=200)
    environment: Literal["SANDBOX", "PRODUCTION"] = "PRODUCTION"
