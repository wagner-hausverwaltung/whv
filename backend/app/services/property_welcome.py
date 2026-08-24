"""Begrüßungsmitteilung für neu übernommene Objekte.

When Impower hands us a new WEG or MV — the object appears and reaches
state READY — every owner (WEG) resp. owner + tenant (MV) should find a
short welcome waiting in the portal: what the portal and the app do, who
their contact is, and a nudge to check their contact details.

Deliberately NOT in here: Verwaltungsbeginn (Impower doesn't carry one, the
text says "ab sofort") and the Hausgeld-IBAN / SEPA mandate (Impower's API
exposes the property account only inside payment orders, which a brand-new
object doesn't have yet — those stay in the postal Anschreiben).

The announcement goes through the normal create path, so the existing
editorial delay applies and the publish worker fans it out; an object with
no portal users yet simply has nobody to notify, and its owners see the
message as soon as they redeem their invitation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Property, PropertyState, PropertyType, User, UserRole
from app.schemas.announcement import AnnouncementCreateRequest
from app.services.announcements import create_announcement

logger = logging.getLogger(__name__)

# Objects we welcome. SEV (STRATA) is a single owner's mandate and gets a
# personal hand-over, so it is deliberately out of scope.
_WELCOME_TYPES = (PropertyType.OWNER, PropertyType.RENTAL)

_CONTACT_NAME = "Dirk Ullrich"
_CONTACT_EMAIL = "ullrich@wagner-hausverwaltung.com"
_CONTACT_PHONE = "+49 156 79 062409"


def welcome_title(prop: Property) -> str:
    return f"Willkommen bei der Wagner Hausverwaltung — {prop.name}"


def welcome_body(prop: Property, *, settings: Settings) -> str:
    """The message text for one object. German, plain prose — the portal and
    the notification e-mail both render it as-is."""
    app_line = (
        f"Die App für iPhone finden Sie hier: {settings.app_store_url}"
        if settings.app_store_url
        else "Die App für iPhone finden Sie im App Store unter „Wagner Hausverwaltung“."
    )
    audience = (
        "Eigentümerinnen und Eigentümer"
        if prop.type == PropertyType.OWNER
        else "Eigentümerinnen, Eigentümer, Mieterinnen und Mieter"
    )
    paragraphs = [
        "Sehr geehrte Damen und Herren,",
        (
            f"ab sofort betreut die Wagner Hausverwaltung GmbH Ihr Objekt {prop.name}. "
            "Wir freuen uns auf die Zusammenarbeit und möchten Ihnen kurz zeigen, "
            "wie Sie uns am schnellsten erreichen."
        ),
        "Portal und App",
        (
            f"Im WHV-Portal finden {audience} alle Unterlagen an einem Ort: Dokumente, "
            "Abrechnungen, Versammlungen und Beschlüsse. Ein Anliegen melden Sie dort "
            "direkt und sehen jederzeit, wie weit die Bearbeitung ist. Dieselben "
            "Funktionen gibt es als App, die Sie zusätzlich benachrichtigt, sobald es "
            "etwas Neues für Sie gibt."
        ),
        f"Portal: {settings.portal_base_url}\n{app_line}",
        "Ihre Kontaktdaten",
        (
            "Für eine reibungslose Kommunikation brauchen wir Ihre aktuellen Daten. "
            "Bitte prüfen Sie nach der Anmeldung im Portal unter „Einstellungen“, ob "
            "Telefonnummer und E-Mail-Adresse stimmen, und ergänzen Sie sie "
            "gegebenenfalls."
        ),
        "Ihr Ansprechpartner",
        (
            f"Für operative Themen erreichen Sie {_CONTACT_NAME} unter "
            f"{_CONTACT_EMAIL} und {_CONTACT_PHONE}."
        ),
        (
            "Unterlagen wie den Wirtschaftsplan und die Jahresabrechnung erhalten Sie "
            "weiterhin zusätzlich per Post. Möchten Sie die Umwelt entlasten, können "
            "Sie bei uns eine rein digitale Kommunikation beantragen."
        ),
        "Bei Rückfragen stehen wir Ihnen jederzeit zur Verfügung.",
    ]
    return "\n\n".join(paragraphs)


async def _system_author(session: AsyncSession, organization_id: uuid.UUID) -> User | None:
    """The Verwalter the automatic announcement is attributed to — the
    organization's longest-standing one, so the author stays stable."""
    author: User | None = await session.scalar(
        select(User)
        .where(
            User.organization_id == organization_id,
            User.role == UserRole.VERWALTER,
            User.deleted_at.is_(None),
        )
        .order_by(User.created_at.asc())
        .limit(1)
    )
    return author


async def welcome_new_properties(session: AsyncSession, *, settings: Settings) -> int:
    """Post a welcome announcement in every newly handed-over WEG/MV.

    Picks up active WEG/MV objects that are READY and have no
    `welcome_sent_at` yet, and stamps that column in the same transaction —
    so a repeated nightly sync never posts twice. Returns the number of
    announcements created. Best effort per object: one failure is logged and
    the rest still get theirs.
    """
    candidates = list(
        (
            await session.scalars(
                select(Property).where(
                    Property.deleted_at.is_(None),
                    Property.welcome_sent_at.is_(None),
                    Property.state == PropertyState.READY,
                    Property.type.in_(_WELCOME_TYPES),
                )
            )
        ).all()
    )
    if not candidates:
        return 0

    created = 0
    for prop in candidates:
        author = await _system_author(session, prop.organization_id)
        if author is None:
            logger.warning(
                "welcome announcement skipped for property %s — no VERWALTER in org %s",
                prop.id,
                prop.organization_id,
            )
            continue
        try:
            create_announcement(
                session,
                organization_id=prop.organization_id,
                property_id=prop.id,
                author=author,
                payload=AnnouncementCreateRequest(
                    title=welcome_title(prop),
                    body=welcome_body(prop, settings=settings),
                    # WEG: owners + Beirat. MV: owners + tenants — the people
                    # who actually use the portal for a rental object.
                    audience_eigentuemer=True,
                    audience_beirat=prop.type == PropertyType.OWNER,
                    audience_mieter=prop.type == PropertyType.RENTAL,
                ),
            )
            prop.welcome_sent_at = datetime.now(UTC)
            await session.commit()
            created += 1
            logger.info("welcome announcement created for property %s (%s)", prop.id, prop.name)
        except Exception:
            await session.rollback()
            logger.exception("welcome announcement failed for property %s", prop.id)
    return created
