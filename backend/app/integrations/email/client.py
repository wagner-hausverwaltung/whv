from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx
from fastapi import Depends

from app.config import Settings, get_settings


class EmailError(Exception):
    """Send failed. `code` is a stable string the SPA can match on
    to render a specific failure mode (rate-limit, missing key, etc.)
    without parsing the free-text message. None when the caller
    didn't know enough to categorise — SPA falls back to a generic
    error message in that case."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


# Stable error-code constants. The SPA reads these to render
# user-facing copy — change them carefully, every reference is a
# product surface.
EMAIL_ERROR_RATE_LIMITED = "rate_limited"
EMAIL_ERROR_NO_API_KEY = "no_api_key"
EMAIL_ERROR_UPSTREAM = "upstream"


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
        to: str | list[str],
        subject: str,
        html: str,
        text: str,
        headers: dict[str, str] | None = None,
        attachments: list[dict[str, str]] | None = None,
        reply_to: str | None = None,
        from_address: str | None = None,
        from_name: str | None = None,
    ) -> str:
        """Send a single transactional email. Returns Resend's message id.

        `headers` lets callers add RFC 5322 threading headers (In-Reply-To,
        References) so replies thread correctly in Gmail / Outlook. Resend's
        REST API accepts a top-level `headers` object.

        `attachments` is the Resend attachments list — each item is
        `{"filename": ..., "content": <base64>}`. Callers base64-encode bytes
        before passing so the client doesn't need to know about specific
        attachment types (PDF, CSV, etc.).

        `reply_to` lets ticket-notification callers route Hit-Reply
        responses to the SES-monitored mailbox instead of the bounce-only
        `email_from_address`. Resend's REST API has a first-class
        `reply_to` field; we use it directly rather than smuggling a
        Reply-To header through `headers` (cleaner, and Resend then
        applies its own bounce/DKIM logic correctly).
        """
        if not self._settings.resend_api_key:
            raise EmailError(
                "RESEND_API_KEY is not configured",
                code=EMAIL_ERROR_NO_API_KEY,
            )

        # Per-call sender override (e.g. anfragen@ offer replies) — both parts
        # fall back to the global EMAIL_FROM_* settings. The address must be on
        # the Resend-verified domain.
        eff_from_name = from_name or self._settings.email_from_name
        eff_from_address = from_address or self._settings.email_from_address
        from_value = f"{eff_from_name} <{eff_from_address}>"
        # Resend's `to` field accepts a list of valid `email@host` (or
        # `Name <email@host>`) strings — NOT a single comma-joined
        # string. We used to do `",".join(recipients)` upstream which
        # Resend rejected with a 422 validation error ("Invalid `to`
        # field"). Normalising to a list here lets callers pass either
        # a bare string or a list without thinking about the wire shape.
        to_list = [to] if isinstance(to, str) else list(to)
        body: dict[str, Any] = {
            "from": from_value,
            "to": to_list,
            "subject": subject,
            "html": html,
            "text": text,
        }
        if headers:
            body["headers"] = headers
        if attachments:
            body["attachments"] = attachments
        if reply_to:
            body["reply_to"] = reply_to
        response = await self._client.post("/emails", json=body)
        if response.status_code != 200:
            # Resend returns 429 for rate-limit (free tier 100/day,
            # paid tiers higher). Marking it specifically lets the
            # SPA show "Tageslimit erreicht" instead of a generic
            # send error. Authoritative source: Resend's "rate_limit"
            # error.type in the JSON body, but we also accept any
            # 429 status as a defensive fallback for transient
            # gateway responses.
            code: str | None = EMAIL_ERROR_UPSTREAM
            if response.status_code == 429:
                code = EMAIL_ERROR_RATE_LIMITED
            else:
                try:
                    body_json = response.json()
                    err_type = body_json.get("type") if isinstance(body_json, dict) else None
                    if isinstance(err_type, str) and "rate" in err_type.lower():
                        code = EMAIL_ERROR_RATE_LIMITED
                except (ValueError, AttributeError):
                    pass
            raise EmailError(
                f"Resend returned {response.status_code}: {response.text[:200]}",
                code=code,
            )
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
