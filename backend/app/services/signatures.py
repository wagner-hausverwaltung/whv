"""DocuSeal signature-request orchestration (ADR-0012).

Two entry points, both session-agnostic (caller commits):

  create_signature_request — store a row, call DocuSeal (template +
    submission → signer emailed via SES), record the ids, flip to SENT.

  complete_signature_request — the `form.completed` webhook path: find
    the row by DocuSeal submission id, download the signed PDF, store it
    back in the WHV document tree (kind SIGNATUR, PRIVATE so it's
    Verwalter-only), link it, flip to COMPLETED. Idempotent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.docuseal.client import DocuSealClient, DocuSealError
from app.integrations.storage.documents import write_document
from app.models import (
    Document,
    DocumentKind,
    DocumentVisibility,
    SignatureRequest,
    SignatureRequestStatus,
)


async def create_signature_request(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    created_by_user_id: uuid.UUID | None,
    property_id: uuid.UUID | None,
    pdf_bytes: bytes,
    filename: str,
    recipient_email: str,
    recipient_name: str | None,
    client: DocuSealClient,
) -> SignatureRequest:
    """Persist a request, then create the DocuSeal template + submission.
    On DocuSeal failure the row is flipped to FAILED and the error
    re-raised (caller maps to a 502). Does NOT commit."""
    row = SignatureRequest(
        organization_id=organization_id,
        property_id=property_id,
        recipient_email=recipient_email,
        recipient_name=recipient_name,
        source_filename=filename,
        status=SignatureRequestStatus.PENDING,
        created_by_user_id=created_by_user_id,
    )
    session.add(row)
    await session.flush()

    try:
        result = await client.create_signature_request(
            pdf_bytes=pdf_bytes,
            filename=filename,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
        )
    except DocuSealError:
        row.status = SignatureRequestStatus.FAILED
        await session.flush()
        raise

    tpl = result.get("template_id")
    sub = result.get("submission_id")
    row.docuseal_template_id = int(tpl) if isinstance(tpl, int) else None
    row.docuseal_submission_id = int(sub) if isinstance(sub, int) else None
    row.status = SignatureRequestStatus.SENT
    await session.flush()
    return row


async def complete_signature_request(
    session: AsyncSession,
    *,
    submission_id: int,
    signed_pdf_url: str,
    client: DocuSealClient,
) -> SignatureRequest | None:
    """Webhook completion: download the signed PDF + file it in the
    document tree, link it, flip to COMPLETED. Returns None if no row
    matches the submission id; idempotent if already completed. Does NOT
    commit."""
    row = await session.scalar(
        select(SignatureRequest).where(SignatureRequest.docuseal_submission_id == submission_id)
    )
    if row is None:
        return None
    if row.status == SignatureRequestStatus.COMPLETED:
        return row

    pdf = await client.download_document(signed_pdf_url)
    doc = Document(
        organization_id=row.organization_id,
        property_id=row.property_id,
        name=f"Signiert - {row.source_filename}",
        kind=DocumentKind.SIGNATUR,
        # PRIVATE: signed contracts/Vollmachten are sensitive — Verwalter
        # sees them in the admin tree; the portal visibility filter hides
        # them from owners/tenants/Beirat.
        visibility=DocumentVisibility.PRIVATE,
        mime_type="application/pdf",
        size_bytes=len(pdf),
        uploaded_at=datetime.now(UTC),
    )
    session.add(doc)
    await session.flush()
    _, suffix = write_document(doc.id, row.source_filename or "signed.pdf", pdf)
    doc.storage_url = f"local-disk:{suffix}"

    row.signed_document_id = doc.id
    row.status = SignatureRequestStatus.COMPLETED
    row.completed_at = datetime.now(UTC)
    await session.flush()
    return row
