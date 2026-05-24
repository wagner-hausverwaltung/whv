"""Pure helpers + the close-and-tally pipeline for Umlaufbeschluss.

Two entry points share the same finalize logic so manual close (admin endpoint)
and scheduled close (Celery beat) converge:

  finalize_resolution(session, resolution, email_client, *, trigger)
    Tally → decide outcome → write status / decided_at / result / result_pdf_url
    → render PDF to disk → send result email to all eligible-owner accounts
    → write audit log entry.

  open_due_resolutions(session)
    Flip ENTWURF → OFFEN for any resolution whose `opens_at` has passed. Used
    by the same beat tick that closes expired ones.

These functions are deliberately session-agnostic — they don't commit, the
caller commits. That lets the API endpoint roll back on a 4xx without writing
a half-finalized state, and lets the Celery task commit once per resolution.
"""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.integrations.email.client import EmailClient, EmailError
from app.integrations.email.resolutions import render_result_email
from app.integrations.pdf.resolution_result import render_result_pdf
from app.models import (
    AuditLog,
    CircularResolution,
    CircularVote,
    Contact,
    Contract,
    ContractContact,
    ContractType,
    Property,
    ResolutionMode,
    ResolutionStatus,
    User,
    VoteChoice,
)
from app.schemas.circular import ResolutionTally

logger = logging.getLogger(__name__)


async def eligible_owner_impower_ids(
    session: AsyncSession,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
) -> set[int]:
    rows = (
        await session.scalars(
            select(Contact.impower_id)
            .join(ContractContact, ContractContact.contact_id == Contact.id)
            .join(Contract, Contract.id == ContractContact.contract_id)
            .where(
                Contract.organization_id == organization_id,
                Contract.property_id == property_id,
                Contract.type == ContractType.OWNER,
                Contract.deleted_at.is_(None),
                Contact.deleted_at.is_(None),
                Contact.impower_id.is_not(None),
            )
            .distinct()
        )
    ).all()
    return {int(r) for r in rows if r is not None}


async def eligible_owner_emails(
    session: AsyncSession,
    organization_id: uuid.UUID,
    property_id: uuid.UUID,
) -> list[str]:
    eligible = await eligible_owner_impower_ids(session, organization_id, property_id)
    if not eligible:
        return []
    rows = (
        await session.scalars(
            select(User.email).where(
                User.organization_id == organization_id,
                User.contact_id_impower.in_(eligible),
                User.deleted_at.is_(None),
            )
        )
    ).all()
    return list(rows)


async def tally(session: AsyncSession, resolution: CircularResolution) -> ResolutionTally:
    eligible = await eligible_owner_impower_ids(
        session, resolution.organization_id, resolution.property_id
    )
    votes = (
        await session.scalars(
            select(CircularVote).where(CircularVote.resolution_id == resolution.id)
        )
    ).all()
    ja = sum(1 for v in votes if v.choice == VoteChoice.JA)
    nein = sum(1 for v in votes if v.choice == VoteChoice.NEIN)
    enth = sum(1 for v in votes if v.choice == VoteChoice.ENTHALTUNG)
    cast = ja + nein + enth
    voted_ids = {v.owner_contact_id_impower for v in votes}
    unanimous = bool(eligible) and eligible.issubset(voted_ids) and nein == 0 and enth == 0
    return ResolutionTally(
        eligible_voters=len(eligible),
        cast=cast,
        ja=ja,
        nein=nein,
        enthaltung=enth,
        quorum_met=cast >= resolution.required_quorum,
        unanimous_yes=unanimous,
    )


def decide_outcome(mode: ResolutionMode, t: ResolutionTally) -> ResolutionStatus:
    if mode == ResolutionMode.KLASSISCH:
        return ResolutionStatus.ANGENOMMEN if t.unanimous_yes else ResolutionStatus.ABGELEHNT
    if not t.quorum_met:
        return ResolutionStatus.ABGELEHNT
    return ResolutionStatus.ANGENOMMEN if t.ja > t.cast / 2 else ResolutionStatus.ABGELEHNT


def summarize_result(t: ResolutionTally, status: ResolutionStatus) -> str:
    return (
        f"{t.ja} JA · {t.nein} NEIN · {t.enthaltung} Enthaltung "
        f"(von {t.eligible_voters} stimmberechtigt) — {status.value}"
    )


def write_result_pdf(
    *,
    resolution_id: uuid.UUID,
    pdf_bytes: bytes,
) -> str:
    """Write PDF bytes to RESOLUTION_PDF_DIR/{id}.pdf. Returns the API URL.

    The directory is created on first write. We store a stable API-relative
    URL like '/admin/resolutions/{id}/result.pdf' on the model so clients
    fetch through the visibility-aware endpoint, not the raw filesystem.
    """
    settings = get_settings()
    base = Path(settings.resolution_pdf_dir)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{resolution_id}.pdf"
    path.write_bytes(pdf_bytes)
    return f"/admin/resolutions/{resolution_id}/result.pdf"


def resolve_result_pdf_path(resolution_id: uuid.UUID) -> Path:
    """Where the result PDF lives on disk. Caller must check existence."""
    settings = get_settings()
    return Path(settings.resolution_pdf_dir) / f"{resolution_id}.pdf"


async def finalize_resolution(
    session: AsyncSession,
    resolution: CircularResolution,
    email_client: EmailClient | None,
    *,
    trigger: str,
    actor_user_id: uuid.UUID | None = None,
) -> ResolutionTally:
    """Close + tally + write PDF + send result emails. Does NOT commit.

    Idempotency: caller checks status before invoking — this function assumes
    the resolution is in OFFEN (or being force-closed from ENTWURF). If a PDF
    already exists for this id, it's overwritten.

    `trigger` is recorded in the audit log ("admin_manual", "beat_scheduled")
    so we can tell early closes from scheduled ones. `email_client` is
    optional — pass None to skip the result-email fan-out (useful for tests).
    """
    now = datetime.now(UTC)
    t = await tally(session, resolution)
    outcome = decide_outcome(resolution.mode, t)
    summary = summarize_result(t, outcome)

    resolution.status = outcome
    resolution.result = summary
    resolution.decided_at = now

    # Render + persist the protocol PDF. ReportLab is CPU-bound; on staging
    # one PDF takes <50 ms so we don't bother with asyncio.to_thread here.
    prop = await session.scalar(select(Property).where(Property.id == resolution.property_id))
    property_name = prop.name if prop else "—"
    pdf_bytes = render_result_pdf(
        resolution_title=resolution.title,
        property_name=property_name,
        mode_label=resolution.mode.value,
        status_label=outcome.value,
        opens_at=resolution.opens_at,
        closes_at=resolution.closes_at,
        decided_at=now,
        eligible_voters=t.eligible_voters,
        ja=t.ja,
        nein=t.nein,
        enthaltung=t.enthaltung,
        required_quorum=resolution.required_quorum,
        summary_line=summary,
    )
    resolution.result_pdf_url = write_result_pdf(resolution_id=resolution.id, pdf_bytes=pdf_bytes)

    session.add(
        AuditLog(
            organization_id=resolution.organization_id,
            actor_user_id=actor_user_id,
            action="resolution_closed",
            target_type="circular_resolutions",
            target_id=str(resolution.id),
            payload_json={
                "outcome": outcome.value,
                "ja": t.ja,
                "nein": t.nein,
                "enthaltung": t.enthaltung,
                "eligible_voters": t.eligible_voters,
                "via": trigger,
            },
        )
    )

    # Result email fan-out — attach the protocol PDF. Best-effort: one failed
    # recipient doesn't block the others or roll back the close.
    if email_client is not None:
        recipients = await eligible_owner_emails(
            session, resolution.organization_id, resolution.property_id
        )
        pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
        attachments = [{"filename": "Beschluss-Protokoll.pdf", "content": pdf_b64}]
        for recipient in recipients:
            try:
                subject, html, text = render_result_email(
                    resolution_title=resolution.title,
                    property_name=property_name,
                    outcome_label=outcome.value,
                    summary=summary,
                    resolution_id=str(resolution.id),
                )
                await email_client.send(
                    to=recipient,
                    subject=subject,
                    html=html,
                    text=text,
                    attachments=attachments,
                )
            except EmailError as exc:
                logger.warning(
                    "result email failed for resolution=%s recipient=%s: %s",
                    resolution.id,
                    recipient,
                    exc,
                )

    return t


async def open_due_resolutions(session: AsyncSession) -> int:
    """Flip ENTWURF → OFFEN for resolutions whose opens_at has passed.

    Run on the same beat tick that closes expired ones. Returns the count
    of rows opened. Does NOT commit.
    """
    now = datetime.now(UTC)
    rows = (
        await session.scalars(
            select(CircularResolution).where(
                CircularResolution.status == ResolutionStatus.ENTWURF,
                CircularResolution.opens_at <= now,
            )
        )
    ).all()
    for r in rows:
        r.status = ResolutionStatus.OFFEN
    return len(rows)


async def find_expired_open_resolutions(
    session: AsyncSession,
) -> list[CircularResolution]:
    now = datetime.now(UTC)
    return list(
        (
            await session.scalars(
                select(CircularResolution).where(
                    CircularResolution.status == ResolutionStatus.OFFEN,
                    CircularResolution.closes_at <= now,
                )
            )
        ).all()
    )
