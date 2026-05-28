"""Push-notification fan-out service.

Bridges the existing email-notification recipient logic to APNs.
Each notification site (ETV comment, ticket message, new ticket)
already resolves a `list[User]` of recipients; we hand the same
list here and this module:

  1. Loads each user's registered, non-deleted devices that match
     the APNs environment we're configured for (sandbox vs prod).
  2. Sends the alert to every token via APNSClient.
  3. Soft-deletes any token APNs reports as unregistered (410 /
     BadDeviceToken), so the next fan-out skips it.

Design choices:
* No-op when APNs isn't configured (empty .p8) — mirrors the
  Resend-disabled pattern. Callers don't have to guard.
* Best-effort: a send failure NEVER propagates to the request that
  triggered it. Email is the system of record; push is the nicety.
* Synchronous within the request for now (same as the email sends).
  If push volume grows we move both onto Celery; the interface
  here stays put.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.integrations.push.apns import APNSClient, APNSError
from app.models import DeviceEnvironment, UserDevice

logger = logging.getLogger(__name__)

# Process-wide APNs client. Cheap to hold — the heavy bit (the auth
# JWT) is cached inside it.
_CLIENT: APNSClient | None = None


def _client() -> APNSClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = APNSClient(get_settings())
    return _CLIENT


async def notify_users(
    session: AsyncSession,
    *,
    user_ids: list[uuid.UUID],
    title: str,
    body: str,
    deep_link: str | None = None,
    thread_id: str | None = None,
) -> None:
    """Fan a single alert out to every registered device of the
    given users. Best-effort: logs + swallows all failures so the
    caller's write path is never affected.

    `deep_link` is a whv:// URL the app routes on tap;
    `thread_id` groups related pushes in Notification Center.
    """
    client = _client()
    if not client.is_configured or not user_ids:
        return

    settings = get_settings()
    want_env = (
        DeviceEnvironment.SANDBOX if settings.apns_use_sandbox else DeviceEnvironment.PRODUCTION
    )

    try:
        rows = (
            await session.scalars(
                select(UserDevice).where(
                    UserDevice.user_id.in_(user_ids),
                    UserDevice.deleted_at.is_(None),
                    UserDevice.environment == want_env,
                )
            )
        ).all()
    except Exception:
        logger.exception("push: failed to load devices for users=%s", user_ids)
        return

    dead_tokens: list[str] = []
    for device in rows:
        try:
            result = await client.send(
                token=device.apns_token,
                title=title,
                body=body,
                deep_link=deep_link,
                thread_id=thread_id,
            )
        except APNSError:
            logger.warning("push: APNs transport error for token=%s", device.apns_token[:12])
            continue
        if result.unregistered:
            dead_tokens.append(device.apns_token)
        elif not result.ok:
            logger.warning(
                "push: delivery failed token=%s status=%s reason=%s",
                device.apns_token[:12],
                result.status_code,
                result.reason,
            )

    if dead_tokens:
        # Soft-delete dead tokens so we stop trying. A re-register
        # un-deletes via the upsert path in the /me/devices endpoint.
        try:
            await session.execute(
                update(UserDevice)
                .where(UserDevice.apns_token.in_(dead_tokens))
                .values(deleted_at=datetime.now(UTC))
            )
            await session.commit()
        except Exception:
            logger.exception("push: failed to prune dead tokens")
