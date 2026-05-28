"""Hausgeld-Anpassung owner notification (nightly poll).

Impower has no webhook for plan adjustments, and a suggestion's body
carries no contract/property id — so we poll per active owner contract:
for each, fetch its plan-adjustment suggestions, and when the Verwalter
has marked one as `ownerCommunicationState == INFORMED` (their explicit
"tell the owner now" signal), email + push the owner(s) on that
contract that their Hausgeld is changing. Per-suggestion Redis dedupe
stops re-notification on the next poll. Best-effort throughout.

Amount interpretation (verify on first real INFORMED suggestion on
staging): `previousCost` is the old amount; the new amount is
`userAmount` when the Verwalter set one, else `previousCost + amount`
(treating `amount` as the adjustment delta). The INFORMED gate means
Wagner controls the first send and can sanity-check the math.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Contact,
    Contract,
    ContractContact,
    ContractType,
    NotificationCategory,
    NotificationChannel,
    Property,
    User,
    UserRole,
)
from app.services.access import active_contract_filter

logger = logging.getLogger(__name__)

_NOTIFIED_TTL_SECONDS = 60 * 60 * 24 * 90  # 90 days


def _dec(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _eur(value: Decimal | None) -> str:
    if value is None:
        return "—"
    grouped = f"{value:,.2f}"  # 1,234.56
    swapped = grouped.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{swapped} €"


def _fmt_date(value: object) -> str:
    if not isinstance(value, str) or len(value) < 10:
        return "—"
    y, m, d = value[:4], value[5:7], value[8:10]
    return f"{d}.{m}.{y}"


def _content(raw: object) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, dict)]
    if isinstance(raw, dict):
        items = raw.get("content")
        if isinstance(items, list):
            return [r for r in items if isinstance(r, dict)]
    return []


async def _owner_users_for_contract(session: AsyncSession, contract: Contract) -> list[User]:
    """Active EIGENTUEMER/BEIRAT users party to this specific contract."""
    rows = await session.scalars(
        select(User)
        .join(Contact, Contact.impower_id == User.contact_id_impower)
        .join(ContractContact, ContractContact.contact_id == Contact.id)
        .where(
            User.organization_id == contract.organization_id,
            User.role.in_([UserRole.EIGENTUEMER, UserRole.BEIRAT]),
            User.deleted_at.is_(None),
            User.contact_id_impower.is_not(None),
            ContractContact.contract_id == contract.id,
            Contact.organization_id == contract.organization_id,
        )
        .distinct()
    )
    return list(rows.all())


async def notify_plan_adjustments(
    session: AsyncSession,
    *,
    client: object,
    redis: Redis,
    email_client: object,
) -> int:
    """Poll each active owner contract for INFORMED plan-adjustment
    suggestions and notify the owner(s). Returns the number of
    suggestions notified."""
    from app.integrations.email.client import EmailError
    from app.integrations.email.plan_adjustments import (
        render_plan_adjustment_notification_email,
    )
    from app.services import notification_prefs, push

    contracts = (
        await session.scalars(
            select(Contract).where(
                Contract.type.in_([ContractType.OWNER, ContractType.PROPERTY_OWNER]),
                Contract.impower_id.is_not(None),
                Contract.deleted_at.is_(None),
                active_contract_filter(),
            )
        )
    ).all()

    notified = 0
    for contract in contracts:
        if contract.impower_id is None:
            continue
        try:
            raw = await client.get_plan_adjustment_suggestions(  # type: ignore[attr-defined]
                contract_id=contract.impower_id
            )
        except Exception:
            logger.warning("plan-adjustment poll failed for contract=%s", contract.id)
            continue

        for suggestion in _content(raw):
            if suggestion.get("ownerCommunicationState") != "INFORMED":
                continue
            sid = suggestion.get("id")
            if not isinstance(sid, int):
                continue
            key = f"plan-adj:notified:{sid}"
            try:
                if await redis.exists(key):
                    continue
                # Mark handled up-front so a mid-loop failure doesn't
                # cause a re-notify next poll.
                await redis.set(key, "1", ex=_NOTIFIED_TTL_SECONDS)

                users = await _owner_users_for_contract(session, contract)
                if not users:
                    continue

                prop = (
                    await session.get(Property, contract.property_id)
                    if contract.property_id
                    else None
                )
                property_name = prop.name if prop else "—"

                previous = _dec(suggestion.get("previousCost"))
                adjustment = (
                    _dec(suggestion.get("userAmount"))
                    if suggestion.get("userAmount") is not None
                    else _dec(suggestion.get("amount"))
                )
                new_cost = (
                    previous + adjustment
                    if previous is not None and adjustment is not None
                    else None
                )
                effective = _fmt_date(suggestion.get("targetDate"))
                new_label = _eur(new_cost)

                subject, html_body, text_body = render_plan_adjustment_notification_email(
                    property_name=property_name,
                    previous_label=_eur(previous),
                    new_label=new_label,
                    effective_date=effective,
                )

                recipient_ids = [u.id for u in users]
                email_ok = set(
                    await notification_prefs.filter_user_ids(
                        session,
                        user_ids=recipient_ids,
                        category=NotificationCategory.PLAN_ADJUSTMENT,
                        channel=NotificationChannel.EMAIL,
                    )
                )
                push_ids = await notification_prefs.filter_user_ids(
                    session,
                    user_ids=recipient_ids,
                    category=NotificationCategory.PLAN_ADJUSTMENT,
                    channel=NotificationChannel.PUSH,
                )
                for u in users:
                    if not u.email or u.id not in email_ok:
                        continue
                    try:
                        await email_client.send(  # type: ignore[attr-defined]
                            to=u.email, subject=subject, html=html_body, text=text_body
                        )
                    except EmailError:
                        logger.warning("plan-adjustment email failed for %s", u.email)

                await push.notify_users(
                    session,
                    user_ids=push_ids,
                    title="Hausgeld-Anpassung",
                    body=f"{property_name}: neu {new_label} ab {effective}",
                    thread_id=f"plan-adj-{sid}",
                )
                notified += 1
            except Exception:
                logger.exception("plan-adjustment notify failed for suggestion=%s", sid)

    return notified
