"""Booked-invoice owner notification.

Driven by the Impower `invoices` webhook (richer-webhooks feature): when
an invoice flips to state BOOKED, email + push the property's owners
(Eigentümer + Beirat) so they see what's being paid out of the WEG, then
record the invoice id in Redis so repeated UPDATE deliveries don't
re-notify. Honours the per-user INVOICE (Rechnungen) preference and is
best-effort throughout — a failure never breaks the webhook ack.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NotificationCategory, NotificationChannel, Property

logger = logging.getLogger(__name__)

# How long we remember "already notified about this invoice". A repeat
# BOOKED UPDATE inside this window is suppressed; after it (very rare) a
# re-notify is acceptable.
_NOTIFIED_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


def _format_eur(amount: object) -> str:
    """German-format a numeric amount as '1.234,56 €'. Falls back to a
    dash when the value isn't parseable."""
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError, TypeError):
        return "—"
    grouped = f"{value:,.2f}"  # 1,234.56
    swapped = grouped.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{swapped} €"


async def notify_booked_invoice(
    session: AsyncSession,
    *,
    client: object,
    invoice_id: int,
    email_client: object,
    redis: Redis,
) -> bool:
    """Fetch the invoice; if it's BOOKED and not yet announced, notify
    the property's owners. Returns True when a notification went out."""
    from app.integrations.email.client import EmailError
    from app.integrations.email.invoices import render_booked_invoice_notification_email
    from app.services import notification_prefs, push
    from app.services.access import owner_users_for_property

    inv = await client.get_invoice(invoice_id)  # type: ignore[attr-defined]
    if (inv.get("state") or "") != "BOOKED":
        return False

    property_impower_id = inv.get("propertyId")
    if not isinstance(property_impower_id, int):
        return False

    dedupe_key = f"invoice:notified:{invoice_id}"
    if await redis.exists(dedupe_key):
        return False

    prop = await session.scalar(
        select(Property).where(
            Property.impower_id == property_impower_id,
            Property.deleted_at.is_(None),
        )
    )
    if prop is None:
        # Property not mirrored yet — don't burn the dedupe key, a later
        # sync may bring it in and a subsequent event can notify.
        return False

    recipients = await owner_users_for_property(
        session, organization_id=prop.organization_id, property_id=prop.id
    )
    # Mark handled regardless of recipient count so we don't re-fetch this
    # invoice on every redelivery.
    await redis.set(dedupe_key, "1", ex=_NOTIFIED_TTL_SECONDS)
    if not recipients:
        return False

    recipient_ids = [r.id for r in recipients]
    email_ok = set(
        await notification_prefs.filter_user_ids(
            session,
            user_ids=recipient_ids,
            category=NotificationCategory.INVOICE,
            channel=NotificationChannel.EMAIL,
        )
    )
    push_ids = await notification_prefs.filter_user_ids(
        session,
        user_ids=recipient_ids,
        category=NotificationCategory.INVOICE,
        channel=NotificationChannel.PUSH,
    )

    property_name = prop.name
    vendor_name = inv.get("counterpartContactName") or "—"
    amount_label = _format_eur(inv.get("amount"))
    invoice_number = inv.get("name") if isinstance(inv.get("name"), str) else None

    subject, html_body, text_body = render_booked_invoice_notification_email(
        property_name=property_name,
        vendor_name=str(vendor_name),
        amount_label=amount_label,
        invoice_number=invoice_number,
    )
    for r in recipients:
        if not r.email or r.id not in email_ok:
            continue
        try:
            await email_client.send(  # type: ignore[attr-defined]
                to=r.email, subject=subject, html=html_body, text=text_body
            )
        except EmailError:
            logger.warning("invoice email failed for %s (invoice=%s)", r.email, invoice_id)

    # No deep_link: invoices live under the property's Dienstleister view,
    # which has no dedicated app route — the email carries the link.
    await push.notify_users(
        session,
        user_ids=push_ids,
        title="Neue Rechnung gebucht",
        body=f"{property_name}: {vendor_name} · {amount_label}",
        thread_id=f"invoice-{prop.id}",
    )
    return True
