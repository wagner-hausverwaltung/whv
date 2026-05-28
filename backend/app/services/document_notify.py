"""New-document notification.

Run as a post-sync pass: find relevant documents that just appeared
(Impower sync inserts them with `notified_at IS NULL`), figure out who
is allowed to SEE each one (same scoping the documents tab enforces),
and email + push those owners — honouring the per-user DOCUMENT
preference. Each processed doc is stamped `notified_at` so it never
fires twice.

Scope rules mirror `me._document_visibility_filter` exactly so "you
got notified" and "you can see it in your documents tab" never
disagree:
  * property-wide doc (no unit/contract/contact FK) → every non-
    Verwalter member of the property
  * unit / contract / contact-scoped doc → only the parties on that
    unit / contract / contact
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Contact,
    Contract,
    ContractContact,
    Document,
    DocumentKind,
    NotificationCategory,
    NotificationChannel,
    Property,
    User,
    UserRole,
)

logger = logging.getLogger(__name__)

# Owner-relevant kinds worth a nudge. Deliberately excludes RECHNUNG
# (vendor invoices — high volume, not owner-facing), VERTRAG,
# HAUSORDNUNG and the SONSTIGES catch-all (which is where
# OWNERS_MEETING_INVITATION lands — those notify via the dedicated ETV
# invitation path, so this avoids double-notifying).
MEANINGFUL_KINDS: tuple[DocumentKind, ...] = (
    DocumentKind.JAHRESABRECHNUNG,
    DocumentKind.WIRTSCHAFTSPLAN,
    DocumentKind.PROTOKOLL,
    DocumentKind.UMLAUFBESCHLUSS,
)

_KIND_LABELS: dict[DocumentKind, str] = {
    DocumentKind.JAHRESABRECHNUNG: "Jahresabrechnung",
    DocumentKind.WIRTSCHAFTSPLAN: "Wirtschaftsplan",
    DocumentKind.PROTOKOLL: "Protokoll",
    DocumentKind.UMLAUFBESCHLUSS: "Umlaufbeschluss",
}

# Backstop window: even though `notified_at` makes us idempotent, only
# consider docs first seen recently so a one-off backlog (e.g. after a
# re-sync that somehow cleared stamps) can't avalanche.
_DOCUMENT_NOTIFY_FRESHNESS_DAYS = 3


async def resolve_document_recipients(
    session: AsyncSession,
    *,
    document: Document,
) -> list[User]:
    """Non-Verwalter users who may see `document`, scoped the same way
    the documents tab is."""
    if document.property_id is None:
        return []

    stmt = (
        select(User)
        .join(Contact, Contact.impower_id == User.contact_id_impower)
        .join(ContractContact, ContractContact.contact_id == Contact.id)
        .join(Contract, Contract.id == ContractContact.contract_id)
        .where(
            User.organization_id == document.organization_id,
            User.deleted_at.is_(None),
            User.contact_id_impower.is_not(None),
            User.role != UserRole.VERWALTER,
            Contact.organization_id == document.organization_id,
            Contract.property_id == document.property_id,
        )
    )

    # Scope: a doc pinned to a unit/contract/contact only reaches the
    # parties on that unit/contract/contact. A property-wide doc (all
    # three NULL) reaches everyone on the property.
    scope_terms = []
    if document.unit_id is not None:
        scope_terms.append(Contract.unit_id == document.unit_id)
    if document.contract_id is not None:
        scope_terms.append(Contract.id == document.contract_id)
    if document.contact_id is not None:
        scope_terms.append(Contact.id == document.contact_id)
    if scope_terms:
        stmt = stmt.where(or_(*scope_terms))

    rows = (await session.scalars(stmt.distinct())).all()
    return list(rows)


async def notify_new_documents(
    session: AsyncSession,
    *,
    email_client: object,
    freshness_days: int = _DOCUMENT_NOTIFY_FRESHNESS_DAYS,
) -> int:
    """Email + push owners about freshly-synced relevant documents.
    Stamps `notified_at` on every doc it touches (even with zero
    recipients) so nothing re-fires. Best-effort per doc. Caller need
    not commit — we commit the stamps here. Returns docs notified."""
    from app.integrations.email.client import EmailError
    from app.integrations.email.documents import render_document_notification_email
    from app.services import notification_prefs, push

    cutoff = datetime.now(UTC) - timedelta(days=freshness_days)
    docs = (
        await session.scalars(
            select(Document)
            .where(
                Document.notified_at.is_(None),
                Document.deleted_at.is_(None),
                Document.kind.in_(MEANINGFUL_KINDS),
                Document.property_id.is_not(None),
                Document.created_at >= cutoff,
            )
            .limit(500)
        )
    ).all()

    notified = 0
    now = datetime.now(UTC)
    for doc in docs:
        try:
            # Stamp first so a mid-loop crash doesn't leave a doc that
            # re-notifies on the next run.
            doc.notified_at = now
            recipients = await resolve_document_recipients(session, document=doc)
            if not recipients:
                continue

            recipient_ids = [r.id for r in recipients]
            email_ok = set(
                await notification_prefs.filter_user_ids(
                    session,
                    user_ids=recipient_ids,
                    category=NotificationCategory.DOCUMENT,
                    channel=NotificationChannel.EMAIL,
                )
            )
            push_ids = await notification_prefs.filter_user_ids(
                session,
                user_ids=recipient_ids,
                category=NotificationCategory.DOCUMENT,
                channel=NotificationChannel.PUSH,
            )

            prop = await session.get(Property, doc.property_id)
            property_name = prop.name if prop else "—"
            kind_label = _KIND_LABELS.get(doc.kind, "Dokument")
            subject, html_body, text_body = render_document_notification_email(
                document_name=doc.name,
                kind_label=kind_label,
                property_name=property_name,
            )
            for r in recipients:
                if not r.email or r.id not in email_ok:
                    continue
                try:
                    await email_client.send(  # type: ignore[attr-defined]
                        to=r.email,
                        subject=subject,
                        html=html_body,
                        text=text_body,
                    )
                except EmailError:
                    logger.warning("document email failed for %s (document=%s)", r.email, doc.id)

            # No deep_link: the iOS app surfaces documents under the
            # property detail screen, not a dedicated route, so a tap
            # just opens the app. The portal email carries the link.
            await push.notify_users(
                session,
                user_ids=push_ids,
                title="Neues Dokument",
                body=f"{property_name}: {kind_label}",
                thread_id=f"document-{doc.property_id}",
            )
            notified += 1
        except Exception:
            logger.exception("document notify failed for document=%s", doc.id)

    await session.commit()
    return notified
