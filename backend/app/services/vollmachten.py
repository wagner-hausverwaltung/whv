"""Vollmacht (ETV proxy authorization) service — ADR-0017.

Create+sign (one step, in-app drawn signature → WHV-design PDF), revoke,
fetch, and the per-assembly proxy register for the Verwalter. Self-
contained: no DocuSeal (that flow is email-only/Pro-gated). The signature
image is composited into the PDF and not stored separately.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.integrations.pdf.assembly_document import render_vollmacht_pdf
from app.models import (
    AuditLog,
    Contact,
    ContactKind,
    EtvAgendaItem,
    EtvAssembly,
    EtvVollmacht,
    Property,
    User,
    VollmachtStatus,
)
from app.schemas.vollmacht import VollmachtResponse, VollmachtVotingInstruction


class VollmachtServiceError(ValueError):
    """Validation error mapped to HTTP 400/409 by the endpoints."""


def _contact_label(c: Contact) -> str:
    if c.kind == ContactKind.COMPANY and c.company_name:
        return c.company_name
    parts = [p for p in (c.first_name, c.last_name) if p]
    if parts:
        return " ".join(parts)
    return c.company_name or c.email or f"Kontakt {c.impower_id or c.id}"


def _format_address(p: Property | None) -> str | None:
    if p is None:
        return None
    street = " ".join(part for part in (p.street, p.number) if part).strip()
    zip_city = " ".join(part for part in (p.postal_code, p.city) if part).strip()
    combined = " · ".join(part for part in (street, zip_city) if part)
    return combined or None


async def _owner_display_name(session: AsyncSession, user: User) -> str:
    """Authoritative name for the Vollmacht — resolved from the user's
    Impower contact, falling back to their login email. Server-resolved so
    nobody can sign under a name they typed in."""
    if user.contact_id_impower is not None:
        contact = await session.scalar(
            select(Contact).where(
                Contact.impower_id == user.contact_id_impower,
                Contact.organization_id == user.organization_id,
                Contact.deleted_at.is_(None),
            )
        )
        if contact is not None:
            return _contact_label(contact)
    return user.email


def pdf_path(settings: Settings, vollmacht_id: uuid.UUID) -> Path:
    return Path(settings.vollmacht_pdf_dir) / f"{vollmacht_id}.pdf"


def to_response(v: EtvVollmacht, *, principal_email: str | None = None) -> VollmachtResponse:
    return VollmachtResponse(
        id=v.id,
        assembly_id=v.assembly_id,
        property_id=v.property_id,
        principal_user_id=v.principal_user_id,
        principal_name=v.principal_name,
        proxy_name=v.proxy_name,
        scope_note=v.scope_note,
        voting_instructions=[
            VollmachtVotingInstruction.model_validate(i) for i in (v.voting_instructions or [])
        ],
        status=v.status,
        signed_at=v.signed_at,
        revoked_at=v.revoked_at,
        has_pdf=bool(v.pdf_storage_url),
        principal_email=principal_email,
    )


async def get_active_for_user(
    session: AsyncSession, *, assembly_id: uuid.UUID, user_id: uuid.UUID
) -> EtvVollmacht | None:
    result: EtvVollmacht | None = await session.scalar(
        select(EtvVollmacht)
        .where(
            EtvVollmacht.assembly_id == assembly_id,
            EtvVollmacht.principal_user_id == user_id,
            EtvVollmacht.status == VollmachtStatus.SIGNED,
        )
        .order_by(EtvVollmacht.signed_at.desc())
    )
    return result


async def get_vollmacht(
    session: AsyncSession, *, vollmacht_id: uuid.UUID, organization_id: uuid.UUID
) -> EtvVollmacht | None:
    result: EtvVollmacht | None = await session.scalar(
        select(EtvVollmacht).where(
            EtvVollmacht.id == vollmacht_id,
            EtvVollmacht.organization_id == organization_id,
        )
    )
    return result


async def create_vollmacht(
    session: AsyncSession,
    *,
    assembly: EtvAssembly,
    actor: User,
    proxy_name: str,
    scope_note: str | None,
    signature_png: bytes | None,
    settings: Settings,
    voting_instructions: list[VollmachtVotingInstruction] | None = None,
) -> EtvVollmacht:
    if not proxy_name.strip():
        raise VollmachtServiceError("Bitte geben Sie an, wen Sie bevollmächtigen.")
    existing = await get_active_for_user(session, assembly_id=assembly.id, user_id=actor.id)
    if existing is not None:
        raise VollmachtServiceError(
            "Sie haben für diese Versammlung bereits eine Vollmacht erteilt. "
            "Bitte widerrufen Sie diese zuerst."
        )

    principal_name = await _owner_display_name(session, actor)
    prop = await session.get(Property, assembly.property_id)
    now = datetime.now(UTC)

    # Snapshot the Weisungen against the CURRENT agenda: an item from another
    # assembly is rejected outright, and position/title are taken from the DB
    # (not the client) so the signed PDF can't be forged via the payload.
    instructions: list[dict[str, Any]] = []
    if voting_instructions:
        rows = (
            await session.execute(
                select(EtvAgendaItem.id, EtvAgendaItem.position, EtvAgendaItem.title).where(
                    EtvAgendaItem.assembly_id == assembly.id
                )
            )
        ).all()
        agenda = {row_id: (pos, title) for row_id, pos, title in rows}
        for item in voting_instructions:
            found = agenda.get(item.agenda_item_id)
            if found is None:
                raise VollmachtServiceError(
                    "Ein Tagesordnungspunkt gehört nicht zu dieser Versammlung."
                )
            position, title = found
            instructions.append(
                {
                    "agenda_item_id": str(item.agenda_item_id),
                    "position": position,
                    "title": title,
                    "instruction": item.instruction.value,
                }
            )
        instructions.sort(key=lambda i: i["position"])

    vollmacht = EtvVollmacht(
        organization_id=actor.organization_id,
        assembly_id=assembly.id,
        property_id=assembly.property_id,
        principal_user_id=actor.id,
        principal_name=principal_name,
        proxy_name=proxy_name.strip(),
        scope_note=(scope_note.strip() if scope_note and scope_note.strip() else None),
        voting_instructions=instructions or None,
        status=VollmachtStatus.SIGNED,
        signed_at=now,
    )
    session.add(vollmacht)
    await session.flush()  # need the id for the file path

    pdf = await asyncio.to_thread(
        render_vollmacht_pdf,
        principal_name=principal_name,
        proxy_name=vollmacht.proxy_name,
        scope_note=vollmacht.scope_note,
        voting_instructions=instructions,
        assembly_title=assembly.title,
        property_name=(prop.name if prop is not None else "—"),
        property_address=_format_address(prop),
        assembly_start=assembly.scheduled_start,
        signed_at=now,
        signature_png=signature_png,
    )
    out = pdf_path(settings, vollmacht.id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pdf)
    vollmacht.pdf_storage_url = "local-disk:.pdf"

    session.add(
        AuditLog(
            organization_id=actor.organization_id,
            actor_user_id=actor.id,
            action="etv_vollmacht_created",
            target_type="etv_vollmachten",
            target_id=str(vollmacht.id),
            payload_json={
                "assembly_id": str(assembly.id),
                "proxy_name": vollmacht.proxy_name,
                "has_signature": bool(signature_png),
            },
        )
    )
    await session.commit()
    await session.refresh(vollmacht)
    return vollmacht


async def revoke_vollmacht(
    session: AsyncSession, *, vollmacht: EtvVollmacht, actor_id: uuid.UUID
) -> EtvVollmacht:
    if vollmacht.status == VollmachtStatus.REVOKED:
        return vollmacht
    vollmacht.status = VollmachtStatus.REVOKED
    vollmacht.revoked_at = datetime.now(UTC)
    session.add(
        AuditLog(
            organization_id=vollmacht.organization_id,
            actor_user_id=actor_id,
            action="etv_vollmacht_revoked",
            target_type="etv_vollmachten",
            target_id=str(vollmacht.id),
            payload_json={"assembly_id": str(vollmacht.assembly_id)},
        )
    )
    await session.commit()
    await session.refresh(vollmacht)
    return vollmacht


async def list_for_assembly(
    session: AsyncSession, *, assembly_id: uuid.UUID
) -> list[VollmachtResponse]:
    """The Verwalter's proxy register for a meeting — newest first, with the
    granting owner's login email resolved for contactability."""
    rows = list(
        (
            await session.scalars(
                select(EtvVollmacht)
                .where(EtvVollmacht.assembly_id == assembly_id)
                .order_by(EtvVollmacht.signed_at.desc())
            )
        ).all()
    )
    user_ids = {v.principal_user_id for v in rows if v.principal_user_id}
    emails: dict[uuid.UUID, str] = {}
    if user_ids:
        user_rows = (await session.scalars(select(User).where(User.id.in_(user_ids)))).all()
        emails = {u.id: u.email for u in user_rows}
    return [
        to_response(
            v,
            principal_email=(emails.get(v.principal_user_id) if v.principal_user_id else None),
        )
        for v in rows
    ]
