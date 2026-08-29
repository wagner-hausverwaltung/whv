"""Freigabe-Schranke für Abrechnungsdokumente (B42-Vorfall, 2026-08-29).

Impower exportiert Hausgeldabrechnungen und Wirtschaftspläne in dem Moment,
in dem sie erzeugt werden — auch als Entwurf, mit ``state=READY`` und ohne
jeden Entwurfs-Marker. Der nächtliche Sync spiegelte solche Entwürfe ins
Portal und verschickte „Neues Dokument"-Mails; ein Eigentümer verglich den
Entwurf prompt mit der Abrechnung des Vorverwalters.

Darum entscheidet bei diesen beiden Arten der Verwalter: ``released_at``
NULL = zurückgehalten (für Eigentümer unsichtbar, keine Benachrichtigung),
gesetzt = freigegeben. Alle anderen Dokumentarten bleiben sofort sichtbar.
Der Impower-Sync fasst die Spalte nie an, eine Freigabe überlebt also jede
Sync-Runde — auch wenn Impower das finale PDF unter derselben Dokument-ID
nachliefert.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentKind

RELEASE_GATED_KINDS: tuple[DocumentKind, ...] = (
    DocumentKind.JAHRESABRECHNUNG,
    DocumentKind.WIRTSCHAFTSPLAN,
)


async def list_withheld(session: AsyncSession, *, organization_id: uuid.UUID) -> list[Document]:
    """Every gated document still waiting for release, oldest first."""
    return list(
        (
            await session.scalars(
                select(Document)
                .where(
                    Document.organization_id == organization_id,
                    Document.kind.in_(RELEASE_GATED_KINDS),
                    Document.released_at.is_(None),
                    Document.deleted_at.is_(None),
                )
                .order_by(Document.created_at.asc())
            )
        ).all()
    )


async def release(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    document_ids: list[uuid.UUID],
) -> list[Document]:
    """Mark the given gated documents as released. Returns the documents that
    actually flipped (already-released or foreign ids are skipped, not an
    error — the admin list may be stale). Caller commits."""
    docs = list(
        (
            await session.scalars(
                select(Document).where(
                    Document.id.in_(document_ids),
                    Document.organization_id == organization_id,
                    Document.kind.in_(RELEASE_GATED_KINDS),
                    Document.released_at.is_(None),
                    Document.deleted_at.is_(None),
                )
            )
        ).all()
    )
    now = datetime.now(UTC)
    for doc in docs:
        doc.released_at = now
    return docs
