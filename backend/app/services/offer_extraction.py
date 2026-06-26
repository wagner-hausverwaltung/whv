"""LLM extraction of an inbound anfragen@ inquiry into offer fields (ADR-0019).

Celery-free + provider-injectable like `etv_extraction`, so it unit-tests with
a stubbed provider. Reads the raw email body off the `OfferInquiry` row, asks
Gemini for the product line + object + units + desired start, writes those back
onto the row, and records one `llm_audit` entry per call. It does NOT send —
the Celery task decides (gated) whether to generate + email or park for review.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.llm import get_llm_provider
from app.integrations.llm.base import LLMProvider, LLMProviderUnavailableError
from app.models import OfferInquiry, OfferInquiryStatus, Organization
from app.schemas.offer import OfferGenerateRequest
from app.services import llm_audit

_PURPOSE = "offer.extract_inquiry"


class ExtractedInquiry(BaseModel):
    """What the LLM pulls from a prospect's inquiry email."""

    is_offer_request: bool = Field(
        description=(
            "True if this email is genuinely asking for a property-management "
            "offer (Angebot) for a WEG or a rental object. False for spam, "
            "newsletters, or unrelated mail."
        )
    )
    art: Literal["WEG", "MV", "UNKNOWN"] = Field(
        description=(
            "WEG if the inquiry concerns a Wohnungseigentümergemeinschaft / "
            "condominium association; MV for Mietverwaltung (a landlord's "
            "rental object/s); UNKNOWN if it cannot be told."
        )
    )
    units: int | None = Field(
        default=None,
        description="Number of units/Wohneinheiten if stated, else null. Never guess.",
    )
    object_street: str | None = Field(
        default=None,
        description="Street + house number of the managed object, e.g. 'Musterstraße 12'.",
    )
    object_plz_city: str | None = Field(
        default=None,
        description="Postcode + city of the managed object, e.g. '70123 Stuttgart'.",
    )
    desired_start: str | None = Field(
        default=None,
        description="Desired management start as ISO date YYYY-MM-DD if stated, else null.",
    )
    recipient_name: str | None = Field(
        default=None,
        description="The prospective client's name (Auftraggeber), if given.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Your overall confidence (0..1) that art + object address + units "
            "are correct. Be honest; a low value routes the inquiry to manual "
            "review rather than an automatic reply."
        ),
    )


_PROMPT = """Sie verarbeiten eine eingehende E-Mail an anfragen@ einer deutschen \
Hausverwaltung. Interessenten fragen hier ein Angebot für WEG-Verwaltung \
(Wohnungseigentümergemeinschaft) oder Mietverwaltung (MV) an.

Extrahieren Sie als JSON gemäß Schema:
- is_offer_request: true nur, wenn es wirklich eine Angebotsanfrage für eine \
  Hausverwaltung ist. Newsletter/Spam/Unzusammenhängendes → false.
- art: "WEG" oder "MV". "UNKNOWN", wenn nicht erkennbar.
- units: Anzahl der Einheiten/Wohneinheiten, falls genannt — sonst null. \
  NICHT raten.
- object_street / object_plz_city: Adresse des zu verwaltenden Objekts \
  (Straße + Nr. bzw. PLZ + Ort), falls genannt.
- desired_start: gewünschter Verwaltungsbeginn als ISO-Datum (YYYY-MM-DD), \
  falls genannt — sonst null.
- recipient_name: Name des Interessenten/Auftraggebers, falls genannt.
- confidence: Ihre ehrliche Gesamtsicherheit (0..1). Lieber niedrig als \
  geraten — ein niedriger Wert führt zur manuellen Prüfung statt zu einer \
  automatischen Antwort.

Geben Sie keine Felder zurück, die nicht ausdrücklich in der E-Mail stehen."""


async def extract_inquiry(
    session: AsyncSession,
    *,
    inquiry_id: uuid.UUID,
    provider: LLMProvider | None = None,
) -> Literal["extracted", "ignored", "skipped_provider_unavailable", "failed"]:
    """Run extraction over an inquiry's body, write fields + status + audit.

    Leaves status EXTRACTED (offer request) / IGNORED (not an offer request);
    the Celery task takes EXTRACTED rows to the send-or-review decision. Caller
    commits.
    """
    if provider is None:
        provider = get_llm_provider()

    inquiry = await session.get(OfferInquiry, inquiry_id)
    if inquiry is None:
        raise ValueError(f"OfferInquiry not found: {inquiry_id}")

    text = f"Betreff: {inquiry.subject}\n\n{inquiry.body}".strip()
    try:
        result = await provider.extract_from_text(
            text=text, prompt=_PROMPT, response_schema=ExtractedInquiry
        )
    except LLMProviderUnavailableError as exc:
        inquiry.status = OfferInquiryStatus.NEEDS_REVIEW.value
        inquiry.error = str(exc)
        await llm_audit.record(
            session,
            organization_id=inquiry.organization_id,
            purpose=_PURPOSE,
            provider=provider.name,
            status=llm_audit.status_for_exception(exc),
            subject_kind="offer_inquiry",
            subject_id=inquiry_id,
            error=str(exc),
        )
        return "skipped_provider_unavailable"
    except Exception as exc:
        inquiry.status = OfferInquiryStatus.NEEDS_REVIEW.value
        inquiry.error = str(exc)
        await llm_audit.record(
            session,
            organization_id=inquiry.organization_id,
            purpose=_PURPOSE,
            provider=provider.name,
            status=llm_audit.status_for_exception(exc),
            subject_kind="offer_inquiry",
            subject_id=inquiry_id,
            error=str(exc),
        )
        await session.commit()
        raise

    payload = result.payload
    inquiry.extraction_json = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
    inquiry.confidence = Decimal(str(round(payload.confidence, 3)))
    inquiry.units = payload.units
    inquiry.art = payload.art if payload.art in ("WEG", "MV") else None
    inquiry.object_address = _join_address(payload.object_street, payload.object_plz_city)
    inquiry.desired_start = _parse_date(payload.desired_start)
    if payload.recipient_name and not inquiry.sender_name:
        inquiry.sender_name = payload.recipient_name

    if not payload.is_offer_request:
        inquiry.status = OfferInquiryStatus.IGNORED.value
        outcome: Literal["extracted", "ignored"] = "ignored"
    else:
        inquiry.status = OfferInquiryStatus.EXTRACTED.value
        outcome = "extracted"

    await llm_audit.record(
        session,
        organization_id=inquiry.organization_id,
        purpose=_PURPOSE,
        provider=provider.name,
        status="ok",
        stats=result.stats,
        subject_kind="offer_inquiry",
        subject_id=inquiry_id,
    )
    return outcome


def build_offer_request(inquiry: OfferInquiry) -> OfferGenerateRequest | None:
    """Map a (post-extraction) inquiry onto an OfferGenerateRequest.

    Returns None when the extracted fields can't satisfy the request schema
    (e.g. unknown art / missing units / missing object) — the caller then
    routes the inquiry to manual review instead of auto-sending.
    """
    extra = _extraction(inquiry)
    if inquiry.art not in ("WEG", "MV") or not inquiry.units:
        return None
    street = extra.get("object_street")
    plz_city = extra.get("object_plz_city")
    try:
        if inquiry.art == "WEG":
            # The object address is optional — a WEG offer only needs the unit
            # count to be priced; a missing street/PLZ just renders blank.
            return OfferGenerateRequest(
                art="WEG",
                units=inquiry.units,
                start_date=inquiry.desired_start,
                object_street=street or "",
                object_plz_city=plz_city or "",
            )
        # MV needs a recipient + object; from a bare inquiry we rarely have the
        # recipient's postal address, so MV usually falls through to review.
        recipient = inquiry.sender_name
        if not recipient or not street:
            return None
        return OfferGenerateRequest(
            art="MV",
            units=inquiry.units,
            start_date=inquiry.desired_start,
            recipient_name=recipient,
            recipient_street=street,
            recipient_plz_city=plz_city or "",
            salutation=f"Sehr geehrte/r {recipient},",
            objects=[_join_address(street, plz_city) or street],
        )
    except ValueError:
        return None


def auto_send_allowed(inquiry: OfferInquiry, *, org: Organization) -> bool:
    """Gate: the inquiry's organization has "Auto-Modus" enabled.

    Per the chosen policy, auto-send fires for *anything that parses* — i.e.
    any inquiry we can turn into a valid offer. Completeness (art/units/object)
    is enforced separately by :func:`build_offer_request` returning ``None``,
    and non-offer mail is already marked IGNORED at extraction time. So the only
    remaining gate here is whether the org opted in. Extraction confidence is
    intentionally NOT a gate.
    """
    return bool(org.offer_auto_send_enabled)


# --- helpers ------------------------------------------------------------------


def _extraction(inquiry: OfferInquiry) -> dict[str, Any]:
    if not inquiry.extraction_json:
        return {}
    try:
        data = json.loads(inquiry.extraction_json)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def _join_address(street: str | None, plz_city: str | None) -> str | None:
    parts = [p for p in (street, plz_city) if p]
    return ", ".join(parts) if parts else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
