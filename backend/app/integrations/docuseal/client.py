"""DocuSeal e-signature client (ADR-0012).

Self-hosted DocuSeal, called over its REST API with an `X-Auth-Token`
header. Two-step create: a template from the uploaded PDF, then a
submission with the single submitter — the submission send triggers
DocuSeal's email (routed through our SES SMTP, so it's from
wagner-hausverwaltung).

Gated like APNs/Resend: no base-url + key → `is_configured` is False and
callers short-circuit, so the feature ships dark until the instance is
provisioned.

NOTE: the exact endpoint/payload shapes follow DocuSeal's documented
public API and should be verified against the deployed version (see
ADR-0012). Centralised here so a version drift is a one-file fix.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.config import Settings


class DocuSealError(Exception):
    """Raised on a non-2xx DocuSeal response or transport failure."""


class DocuSealClient:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.docuseal_base_url.rstrip("/")
        self._key = settings.docuseal_api_key

    @property
    def is_configured(self) -> bool:
        return bool(self._base and self._key)

    async def create_signature_request(
        self,
        *,
        pdf_bytes: bytes,
        filename: str,
        recipient_email: str,
        recipient_name: str | None = None,
    ) -> dict[str, Any]:
        """Create a template from the PDF, then a submission for the one
        signer. Returns {"template_id", "submission_id", "raw"}.
        DocuSeal emails the signer on submission create."""
        if not self.is_configured:
            raise DocuSealError("DocuSeal is not configured")

        headers = {
            "X-Auth-Token": self._key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        encoded = base64.b64encode(pdf_bytes).decode("ascii")
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                tpl_resp = await client.post(
                    f"{self._base}/templates/pdf",
                    json={"name": filename, "documents": [{"name": filename, "file": encoded}]},
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                raise DocuSealError(f"template request failed: {exc}") from exc
            if tpl_resp.status_code >= 400:
                raise DocuSealError(
                    f"template create {tpl_resp.status_code}: {tpl_resp.text[:200]}"
                )
            template = tpl_resp.json()
            template_id = template.get("id")

            submitter: dict[str, Any] = {"email": recipient_email}
            if recipient_name:
                submitter["name"] = recipient_name
            try:
                sub_resp = await client.post(
                    f"{self._base}/submissions",
                    json={
                        "template_id": template_id,
                        "send_email": True,
                        "submitters": [submitter],
                    },
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                raise DocuSealError(f"submission request failed: {exc}") from exc
            if sub_resp.status_code >= 400:
                raise DocuSealError(
                    f"submission create {sub_resp.status_code}: {sub_resp.text[:200]}"
                )
            data = sub_resp.json()

        # DocuSeal returns a list of submitters; the submission id is on
        # each. Be defensive about shape.
        submission_id: int | None = None
        if isinstance(data, list) and data and isinstance(data[0], dict):
            sid = data[0].get("submission_id") or data[0].get("submissionId")
            if isinstance(sid, int):
                submission_id = sid
        elif isinstance(data, dict):
            sid = data.get("id") or data.get("submission_id")
            if isinstance(sid, int):
                submission_id = sid

        return {"template_id": template_id, "submission_id": submission_id, "raw": data}

    async def download_document(self, url: str) -> bytes:
        """Fetch a signed-document PDF (the `documents[].url` from the
        `form.completed` webhook). Sends the auth token in case the URL
        is gated; harmless if it's already a public/expiring link."""
        if not self.is_configured:
            raise DocuSealError("DocuSeal is not configured")
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                resp = await client.get(url, headers={"X-Auth-Token": self._key})
            except httpx.HTTPError as exc:
                raise DocuSealError(f"document download failed: {exc}") from exc
        if resp.status_code >= 400:
            raise DocuSealError(f"document download {resp.status_code}: {resp.text[:200]}")
        return resp.content


def get_docuseal_client(settings: Settings) -> DocuSealClient:
    return DocuSealClient(settings)
