from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx
from fastapi import Depends

from app.config import Settings, get_settings


class EmailError(Exception):
    pass


class EmailClient:
    """Thin async wrapper around the Resend REST API.

    Resend ships a sync Python SDK; we use httpx directly to stay async-native
    and avoid the extra dep. Per-request client (cheap for low-volume admin
    endpoints; the cold-connect overhead doesn't matter for invite emails).
    """

    BASE_URL = "https://api.resend.com"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            timeout=10.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
    ) -> str:
        """Send a single transactional email. Returns Resend's message id."""
        if not self._settings.resend_api_key:
            raise EmailError("RESEND_API_KEY is not configured")

        from_value = f"{self._settings.email_from_name} <{self._settings.email_from_address}>"
        body: dict[str, Any] = {
            "from": from_value,
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text,
        }
        response = await self._client.post("/emails", json=body)
        if response.status_code != 200:
            raise EmailError(f"Resend returned {response.status_code}: {response.text[:200]}")
        payload: dict[str, Any] = response.json()
        message_id = payload.get("id")
        if not isinstance(message_id, str):
            raise EmailError(f"Resend response missing 'id': {payload}")
        return message_id


async def get_email_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[EmailClient]:
    client = EmailClient(settings)
    try:
        yield client
    finally:
        await client.aclose()
